"""Benchmark corpus generator + real measurement collector.

Programs are ORIGINAL (parametric templates written for this project, no third-party licences involved). All are
deterministic and free of undefined behaviour (unsigned wrap-around, in-bounds indexing). Workload sizes derive from
`argc` so the compiler cannot constant-fold the whole computation away. The correctness oracle for a program is the
stdout/exit code of its -O0 build (and each template prints a checksum of all work done)."""
from __future__ import annotations

import csv
import json
import platform
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..analysis.features import FEATURE_NAMES, public_features, vectorize
from ..benchmark.runner import benchmark_many
from ..compiler import compilation as cc
from ..compiler import correctness as co
from ..compiler import passes as reg
from ..config import settings
from ..services import analysis_service as an
from ..services.candidates import compile_candidate, prepare_candidate

DATASET_VERSION = "ds-1"


# ----------------------------------------------------------------------------------------------- templates
def t_arith(p):
    return f"""#include <stdio.h>
#include <stdint.h>
int main(int argc, char **argv) {{
    (void)argv;
    uint64_t x = 88172645463325252ULL + (uint64_t)argc, acc = 0;
    long n = {p['n']} + argc - 1;
    for (long i = 0; i < n; i++) {{
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        acc += (x % {p['mod']}) * (uint64_t)(i & 3) + (x >> {p['shift']});
    }}
    printf("%llu\\n", (unsigned long long)acc);
    return 0;
}}
"""


def t_saxpy(p):
    return f"""#include <stdio.h>
#define M {p['m']}
static float a[M], b[M];
int main(int argc, char **argv) {{
    (void)argv;
    int reps = {p['reps']} + argc - 1;
    for (int i = 0; i < M; i++) {{ a[i] = (float)(i % 17) * 0.5f; b[i] = (float)(i % 13); }}
    for (int r = 0; r < reps; r++)
        for (int i = 0; i < M; i++) b[i] = b[i] * 0.999f + a[i] * {p['k']}f;
    double s = 0.0;
    for (int i = 0; i < M; i++) s += b[i];
    printf("%.3f\\n", s);
    return 0;
}}
"""


def t_reduce(p):
    return f"""#include <stdio.h>
#define M {p['m']}
static int v[M];
int main(int argc, char **argv) {{
    (void)argv;
    int reps = {p['reps']} + argc - 1;
    unsigned s = 12345u;
    for (int i = 0; i < M; i++) {{ s = s * 1103515245u + 12345u; v[i] = (int)((s >> 8) % 1000) - 500; }}
    long long sum = 0; int mn = v[0], mx = v[0], pos = 0;
    for (int r = 0; r < reps; r++) {{
        for (int i = 0; i < M; i++) {{
            sum += v[i] {p['op']} r;
            if (v[i] < mn) mn = v[i];
            if (v[i] > mx) mx = v[i];
            pos += v[i] > 0;
        }}
    }}
    printf("%lld %d %d %d\\n", sum, mn, mx, pos);
    return 0;
}}
"""


def t_matmul(p):
    n, ty = p["n"], p["type"]
    fmt = "%.4f" if ty == "double" else "%lld"
    cast = "" if ty == "double" else "(long long)"
    if p["order"] == "ijk":
        loop = "for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) { T acc = 0; for (int k = 0; k < N; k++) acc += A[i][k] * B[k][j]; C[i][j] = acc; }"
    else:
        loop = "for (int i = 0; i < N; i++) for (int k = 0; k < N; k++) { T aik = A[i][k]; for (int j = 0; j < N; j++) C[i][j] += aik * B[k][j]; }"
    return f"""#include <stdio.h>
#define N {n}
typedef {ty} T;
static T A[N][N], B[N][N], C[N][N];
int main(int argc, char **argv) {{
    (void)argv;
    for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) {{ A[i][j] = (T)((i * 7 + j * 3 + argc) % 11); B[i][j] = (T)((i * 5 + j * 2) % 13); C[i][j] = 0; }}
    {loop}
    T tr = 0;
    for (int i = 0; i < N; i++) tr += C[i][i] + C[i][N - 1 - i];
    printf("{fmt}\\n", {cast}tr);
    return 0;
}}
"""


def t_bsearch(p):
    return f"""#include <stdio.h>
#define M {p['m']}
static int arr[M];
static int find(int key) {{
    int lo = 0, hi = M - 1;
    while (lo <= hi) {{
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] == key) return mid;
        if (arr[mid] < key) lo = mid + 1; else hi = mid - 1;
    }}
    return -1;
}}
int main(int argc, char **argv) {{
    (void)argv;
    for (int i = 0; i < M; i++) arr[i] = i * {p['stride']};
    unsigned s = 7u + (unsigned)argc; long hits = 0, idxsum = 0;
    long q = {p['q']} + argc - 1;
    for (long i = 0; i < q; i++) {{
        s = s * 1664525u + 1013904223u;
        int r = find((int)((s >> 4) % (unsigned)(M * {p['stride']})));
        if (r >= 0) {{ hits++; idxsum += r; }}
    }}
    printf("%ld %ld\\n", hits, idxsum);
    return 0;
}}
"""


def t_sort(p):
    if p["algo"] == "insertion":
        body = """for (int i = 1; i < N; i++) { int key = v[i]; int j = i - 1; while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; j--; } v[j + 1] = key; }"""
        pre = ""
    else:
        pre = "static int cmp(const void *a, const void *b) { int x = *(const int *)a, y = *(const int *)b; return (x > y) - (x < y); }\n"
        body = "qsort(v, N, sizeof(int), cmp);"
    return f"""#include <stdio.h>
#include <stdlib.h>
#define N {p['n']}
static int v[N];
{pre}int main(int argc, char **argv) {{
    (void)argv;
    unsigned s = 99u + (unsigned)argc;
    for (int i = 0; i < N; i++) {{ s = s * 1103515245u + 12345u; v[i] = (int)((s >> 10) % 100000); }}
    {body}
    long long chk = 0;
    for (int i = 0; i < N; i++) chk = chk * 31 + v[i];
    printf("%d %d %lld\\n", v[0], v[N - 1], chk);
    return 0;
}}
"""


def t_string(p):
    return f"""#include <stdio.h>
#define L {p['l']}
static char buf[L + 1];
int main(int argc, char **argv) {{
    (void)argv;
    unsigned s = 5u + (unsigned)argc;
    for (int i = 0; i < L; i++) {{ s = s * 1103515245u + 12345u; buf[i] = (char)('a' + (s >> 16) % {p['alpha']}); }}
    buf[L] = 0;
    unsigned long h = 5381; long vowels = 0, runs = 0;
    int reps = {p['reps']} + argc - 1;
    for (int r = 0; r < reps; r++) {{
        for (int i = 0; i < L; i++) {{
            char c = buf[i];
            h = ((h << 5) + h) + (unsigned char)c;
            switch (c) {{ case 'a': case 'e': case 'i': case 'o': case 'u': vowels++; break; default: break; }}
            if (i > 0 && buf[i - 1] == c) runs++;
        }}
    }}
    printf("%lu %ld %ld\\n", h, vowels, runs);
    return 0;
}}
"""


def t_numeric(p):
    if p["kind"] == "integrate":
        core = f"""double h = 1.0 / (double)n, s = 0.0;
    for (long i = 0; i < n; i++) {{ double x = (double)i * h; s += (x * x * x - 2.0 * x + 1.0) * h; }}
    printf("%.6f\\n", s);"""
    elif p["kind"] == "newton":
        core = f"""double tot = 0.0;
    for (long i = 1; i <= n / 20; i++) {{ double v = (double)i, g = v / 2.0; for (int k = 0; k < 20; k++) g = 0.5 * (g + v / g); tot += g; }}
    printf("%.6f\\n", tot);"""
    else:
        core = f"""unsigned s = 17u + (unsigned)argc; long in = 0;
    for (long i = 0; i < n; i++) {{ s = s * 1103515245u + 12345u; double x = (double)(s >> 8) / 16777216.0; s = s * 1103515245u + 12345u; double y = (double)(s >> 8) / 16777216.0; if (x * x + y * y <= 1.0) in++; }}
    printf("%ld\\n", in);"""
    return f"""#include <stdio.h>
int main(int argc, char **argv) {{
    (void)argv;
    long n = {p['n']} + argc - 1;
    {core}
    return 0;
}}
"""


def t_branch(p):
    if p["kind"] == "collatz":
        core = """for (long i = 1; i <= lim; i++) { unsigned long long x = (unsigned long long)i; while (x != 1) { x = (x & 1) ? 3 * x + 1 : x >> 1; steps++; } }"""
    else:
        core = """for (long i = 0; i < lim; i++) { long m = i % 15; if (m == 0) steps += 15; else if (m % 5 == 0) steps += 5; else if (m % 3 == 0) steps += 3; else if ((i ^ (i >> 3)) & 1) steps += 2; else steps += 1; }"""
    return f"""#include <stdio.h>
int main(int argc, char **argv) {{
    (void)argv;
    long lim = {p['lim']} + argc - 1; unsigned long long steps = 0;
    {core}
    printf("%llu\\n", steps);
    return 0;
}}
"""


def t_memory(p):
    return f"""#include <stdio.h>
#define M {p['m']}
static unsigned nxt[M];
static unsigned data[M];
int main(int argc, char **argv) {{
    (void)argv;
    unsigned s = 3u + (unsigned)argc;
    for (unsigned i = 0; i < M; i++) {{ nxt[i] = i; data[i] = i * 2654435761u; }}
    for (unsigned i = M - 1; i > 0; i--) {{ s = s * 1103515245u + 12345u; unsigned j = (s >> 8) % i; unsigned t = nxt[i]; nxt[i] = nxt[j]; nxt[j] = t; }}
    unsigned p = 0; unsigned long long acc = 0;
    long steps = {p['steps']} + argc - 1;
    for (long i = 0; i < steps; i++) {{ p = nxt[p]; acc += data[p]; }}
    unsigned long long strided = 0;
    for (int r = 0; r < {p['sreps']}; r++) for (unsigned i = 0; i < M; i += {p['stride']}) strided += data[i];
    printf("%llu %llu\\n", acc, strided);
    return 0;
}}
"""


def t_calls(p):
    if p["kind"] == "fib":
        return f"""#include <stdio.h>
static int fib(int n) {{ return n < 2 ? n : fib(n - 1) + fib(n - 2); }}
int main(int argc, char **argv) {{
    (void)argv;
    printf("%d\\n", fib({p['n']} + argc - 1));
    return 0;
}}
"""
    return f"""#include <stdio.h>
#include <stdint.h>
static uint64_t mulmod(uint64_t a, uint64_t b, uint64_t m) {{ return (a * b) % m; }}
static uint64_t addmod(uint64_t a, uint64_t b, uint64_t m) {{ uint64_t s = a + b; return s >= m ? s - m : s; }}
static uint64_t step(uint64_t x, uint64_t m) {{ return addmod(mulmod(x, x, m), 1, m); }}
int main(int argc, char **argv) {{
    (void)argv;
    uint64_t x = 2 + (uint64_t)argc, m = {p['mod']}ULL, acc = 0;
    long n = {p['n']} + argc - 1;
    for (long i = 0; i < n; i++) {{ x = step(x, m); acc ^= x + (uint64_t)i; }}
    printf("%llu\\n", (unsigned long long)acc);
    return 0;
}}
"""


def t_tiny(p):
    return f"""#include <stdio.h>
int main(int argc, char **argv) {{
    (void)argv;
    long s = 0; int n = {p['n']} + argc - 1;
    for (int i = 0; i < n; i++) s += (i * {p['k']}) % 7;
    printf("%ld\\n", s);
    return 0;
}}
"""


# family -> (template, parameter sets). Quick mode uses the first `QUICK_PER_FAMILY` sets; full mode uses all.
FAMILIES: dict[str, tuple[Callable[[dict], str], list[dict]]] = {
    "arith_loop": (t_arith, [dict(n=30_000_000, mod=1000003, shift=7), dict(n=20_000_000, mod=97, shift=11),
                             dict(n=40_000_000, mod=65521, shift=3), dict(n=25_000_000, mod=1009, shift=17),
                             dict(n=35_000_000, mod=8191, shift=5), dict(n=15_000_000, mod=999983, shift=13)]),
    "array_float": (t_saxpy, [dict(m=4096, reps=40000, k="0.01"), dict(m=1024, reps=40000, k="0.5"),
                              dict(m=16384, reps=10000, k="0.25"), dict(m=65536, reps=2500, k="0.1"),
                              dict(m=2048, reps=80000, k="0.75"), dict(m=8192, reps=20000, k="0.3")]),
    "array_reduce": (t_reduce, [dict(m=8192, reps=12000, op="+"), dict(m=2048, reps=50000, op="^"),
                                dict(m=32768, reps=3000, op="-"), dict(m=1024, reps=100000, op="+"),
                                dict(m=16384, reps=6000, op="^"), dict(m=65536, reps=1500, op="+")]),
    "matmul": (t_matmul, [dict(n=300, type="double", order="ijk"), dict(n=256, type="int", order="ikj"),
                          dict(n=320, type="double", order="ikj"), dict(n=280, type="int", order="ijk"),
                          dict(n=224, type="double", order="ijk"), dict(n=288, type="int", order="ikj")]),
    "searching": (t_bsearch, [dict(m=1 << 16, q=750_000, stride=3), dict(m=1 << 12, q=1_200_000, stride=2),
                              dict(m=1 << 18, q=500_000, stride=5), dict(m=1 << 10, q=1_500_000, stride=7),
                              dict(m=1 << 14, q=1_000_000, stride=4), dict(m=1 << 20, q=400_000, stride=3)]),
    "sorting": (t_sort, [dict(algo="insertion", n=12000), dict(algo="qsort", n=600_000), dict(algo="insertion", n=8000),
                         dict(algo="qsort", n=300_000), dict(algo="insertion", n=16000), dict(algo="qsort", n=900_000)]),
    "string_proc": (t_string, [dict(l=100_000, alpha=26, reps=150), dict(l=10_000, alpha=5, reps=1500),
                               dict(l=400_000, alpha=26, reps=40), dict(l=2_000, alpha=3, reps=8000),
                               dict(l=50_000, alpha=10, reps=300), dict(l=200_000, alpha=7, reps=80)]),
    "numeric": (t_numeric, [dict(kind="integrate", n=15_000_000), dict(kind="newton", n=6_000_000),
                            dict(kind="montecarlo", n=25_000_000), dict(kind="integrate", n=8_000_000),
                            dict(kind="newton", n=3_000_000), dict(kind="montecarlo", n=15_000_000)]),
    "branch_heavy": (t_branch, [dict(kind="collatz", lim=300_000), dict(kind="fizz", lim=20_000_000),
                                dict(kind="collatz", lim=150_000), dict(kind="fizz", lim=10_000_000),
                                dict(kind="collatz", lim=500_000), dict(kind="fizz", lim=30_000_000)]),
    "memory_bound": (t_memory, [dict(m=1 << 19, steps=2_000_000, sreps=4, stride=16), dict(m=1 << 16, steps=4_000_000, sreps=40, stride=8),
                                dict(m=1 << 20, steps=1_000_000, sreps=2, stride=32), dict(m=1 << 18, steps=3_000_000, sreps=12, stride=4),
                                dict(m=1 << 19, steps=1_500_000, sreps=3, stride=64), dict(m=1 << 14, steps=6_000_000, sreps=120, stride=2)]),
    "call_heavy": (t_calls, [dict(kind="fib", n=36), dict(kind="mod", n=30_000_000, mod=1000000007),
                             dict(kind="fib", n=34), dict(kind="mod", n=20_000_000, mod=998244353),
                             dict(kind="fib", n=37), dict(kind="mod", n=40_000_000, mod=4294967291)]),
    "tiny_kernel": (t_tiny, [dict(n=2000, k=3), dict(n=500, k=5), dict(n=8000, k=11), dict(n=100, k=2),
                             dict(n=4000, k=13), dict(n=1000, k=7)]),
}
QUICK_PER_FAMILY = 3


@dataclass
class Program:
    program_id: str
    family: str
    params: dict
    path: Path


def generate_programs(data_dir: Path, mode: str = "quick") -> list[Program]:
    """Deterministically write the corpus to `data_dir/<family>/<id>.c` plus `manifest.json`."""
    per = QUICK_PER_FAMILY if mode == "quick" else 6
    progs: list[Program] = []
    for fam, (tmpl, sets) in FAMILIES.items():
        d = data_dir / fam
        d.mkdir(parents=True, exist_ok=True)
        for idx, params in enumerate(sets[:per]):
            pid = f"{fam}_{idx + 1:02d}"
            path = d / f"{pid}.c"
            text = tmpl(params)
            if not path.exists() or path.read_text() != text:
                path.write_text(text)
            progs.append(Program(pid, fam, params, path))
    (data_dir / "manifest.json").write_text(json.dumps(
        {"dataset_version": DATASET_VERSION, "mode": mode,
         "programs": [{"id": p.program_id, "family": p.family, "params": p.params,
                       "path": str(p.path.relative_to(data_dir))} for p in progs]}, indent=2))
    return progs


# ----------------------------------------------------------------------------------------------- measurement
MEASURE_COLUMNS = ["program_id", "family", "strategy_id", "median_ms", "iqr_ms", "n", "binary_size", "compile_ms",
                   "correctness", "duplicate_of", "failure"]


def measure_program(prog: Program, reps: int, warmup: int, strategies: list[reg.Strategy], work_root: Path,
                    build_workers: int) -> dict:
    """Compile + verify + time every strategy for one program. Returns dict(features, rows)."""
    wd = Path(tempfile.mkdtemp(prefix=f"{prog.program_id}-", dir=work_root))
    try:
        src = wd / "program.c"
        shutil.copyfile(prog.path, src)
        unopt = wd / "unoptimized.ll"
        ir_ok = cc.emit_unoptimized_ir(src, "c", unopt).ok and (cc.verify_ir(unopt).ok or reg.availability(
            reg.get("ir-scalar"), "c")[0] is False)
        feats, _ = an.compute_features(src, "c", unopt if ir_ok else None, wd)
        builds = [prepare_candidate(s, "c", src, unopt if ir_ok else None, wd) for s in strategies]
        with ThreadPoolExecutor(max_workers=build_workers) as pool:
            builds = list(pool.map(compile_candidate, builds))
        by = {b.strategy.id: b for b in builds}
        base = by[reg.BASELINE_ID]
        rows: list[dict] = []
        if base.status != "ok":
            return {"features": feats, "rows": [], "error": f"baseline failed: {base.failure}"}
        ref = co.build_reference(base.exe, [b""])
        if not ref.ok:
            return {"features": feats, "rows": [], "error": f"reference unusable: {ref.reason}"}
        first: dict[str, str] = {}
        valid = {}
        for b in builds:
            sid = b.strategy.id
            row = dict(program_id=prog.program_id, family=prog.family, strategy_id=sid, median_ms="", iqr_ms="", n=0,
                       binary_size=b.exe.stat().st_size if b.exe else "", compile_ms=round(b.compile_ms, 2) if b.compile_ms else "",
                       correctness="n/a", duplicate_of="", failure=b.failure or "")
            if b.status == "ok":
                ok, why = (True, None) if sid == reg.BASELINE_ID else co.check_against(ref, b.exe)
                row["correctness"] = "passed" if ok else "failed"
                row["failure"] = why or ""
                if ok:
                    if b.exe_hash in first:
                        row["duplicate_of"] = first[b.exe_hash]
                    else:
                        first[b.exe_hash] = sid
                        valid[sid] = b
            rows.append(row)
        res = benchmark_many({k: v.exe for k, v in valid.items()}, b"", reps, warmup, budget_s=30)
        by_row = {r["strategy_id"]: r for r in rows}
        for sid, r in res.items():
            if r.ok:
                by_row[sid].update(median_ms=round(r.stats["median"], 4), iqr_ms=round(r.stats["iqr"], 4), n=r.reps_done)
            else:
                by_row[sid]["failure"] = r.failure or "benchmark failed"
        # duplicates inherit the measurement of the binary they are identical to (same machine code)
        for r in rows:
            if r["duplicate_of"] and by_row[r["duplicate_of"]]["median_ms"] != "":
                src_row = by_row[r["duplicate_of"]]
                r.update(median_ms=src_row["median_ms"], iqr_ms=src_row["iqr_ms"], n=src_row["n"])
        return {"features": feats, "rows": rows}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def collect_measurements(programs: list[Program], out_dir: Path, reps: int, warmup: int,
                         progress: Callable[[str, int, int, str], None] | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    avail, skipped = reg.available_strategies("c")
    work_root = settings.work_dir
    work_root.mkdir(parents=True, exist_ok=True)
    all_rows, feats_rows, failures = [], [], []
    t0 = time.time()
    for i, prog in enumerate(programs):
        if progress:
            progress("collect", i, len(programs), f"{prog.program_id}")
        out = measure_program(prog, reps, warmup, avail, work_root, settings.build_workers)
        if out.get("error"):
            failures.append({"program_id": prog.program_id, "reason": out["error"]})
            continue
        all_rows += out["rows"]
        fr = {"program_id": prog.program_id, "family": prog.family}
        fr.update({n: out["features"].get(n, 0.0) for n in FEATURE_NAMES})
        feats_rows.append(fr)
        for r in out["rows"]:
            if r["failure"] or r["correctness"] == "failed":
                failures.append({"program_id": prog.program_id, "strategy_id": r["strategy_id"], "reason": r["failure"]})
    _write_csv(out_dir / "measurements.csv", MEASURE_COLUMNS, all_rows)
    _write_csv(out_dir / "features.csv", ["program_id", "family"] + FEATURE_NAMES, feats_rows)
    _write_csv(out_dir / "failures.csv", ["program_id", "strategy_id", "reason"], failures)
    meta = {"dataset_version": DATASET_VERSION, "programs": len(programs), "reps": reps, "warmup": warmup,
            "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - t0, 1),
            "platform": platform.platform(), "cpu_count": settings.build_workers,
            "unavailable_strategies": skipped, "n_rows": len(all_rows), "n_failures": len(failures)}
    (out_dir / "dataset_meta.json").write_text(json.dumps(meta, indent=2))
    _store_samples(all_rows, meta)
    if progress:
        progress("collect", len(programs), len(programs), "done")
    return meta


def _write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _store_samples(rows: list[dict], meta: dict) -> None:
    from ..database import init_db, session_scope
    from ..models import BenchmarkSample

    init_db()
    bid = "bench-" + time.strftime("%Y%m%d-%H%M%S")
    env = {"platform": meta["platform"], "reps": meta["reps"], "warmup": meta["warmup"]}
    with session_scope() as s:
        for r in rows:
            s.add(BenchmarkSample(benchmark_id=bid, program_id=r["program_id"], family=r["family"], strategy_id=r["strategy_id"],
                                  median_ms=float(r["median_ms"]) if r["median_ms"] != "" else None,
                                  binary_size=int(r["binary_size"]) if r["binary_size"] != "" else None,
                                  compile_time_ms=float(r["compile_ms"]) if r["compile_ms"] != "" else None,
                                  correctness_status=r["correctness"], failure_reason=(r["failure"] or None) and r["failure"][:500],
                                  config={"duplicate_of": r["duplicate_of"] or None}, environment=env))
