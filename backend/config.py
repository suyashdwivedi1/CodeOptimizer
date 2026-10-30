"""Centralised configuration. Everything is overridable through environment variables
or a `.env` file in the project root (see `.env.example`)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is optional at import time
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    p = Path(raw).expanduser() if raw else default
    return p if p.is_absolute() else (ROOT / p)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", ROOT / "data"))
    artifacts_dir: Path = field(default_factory=lambda: _path("ARTIFACTS_DIR", ROOT / "artifacts"))
    results_dir: Path = field(default_factory=lambda: _path("RESULTS_DIR", ROOT / "results"))

    # Toolchain overrides (leave empty to auto-detect on PATH / common install dirs)
    llvm_bin_dir: str = os.environ.get("LLVM_BIN_DIR", "")
    clang_path: str = os.environ.get("CLANG_PATH", "")
    clangxx_path: str = os.environ.get("CLANGXX_PATH", "")
    opt_path: str = os.environ.get("OPT_PATH", "")
    llc_path: str = os.environ.get("LLC_PATH", "")

    # Limits (treat as best-effort protections, not a sandbox)
    max_source_bytes: int = _int("MAX_SOURCE_BYTES", 200_000)
    max_stdin_bytes: int = _int("MAX_STDIN_BYTES", 100_000)
    compile_timeout_s: float = _float("COMPILE_TIMEOUT_S", 60.0)
    run_timeout_s: float = _float("RUN_TIMEOUT_S", 10.0)
    max_output_bytes: int = _int("MAX_OUTPUT_BYTES", 1_000_000)
    run_memory_limit_mb: int = _int("RUN_MEMORY_LIMIT_MB", 1024)

    # Benchmark modes
    quick_reps: int = _int("QUICK_REPS", 7)
    quick_warmup: int = _int("QUICK_WARMUP", 1)
    rigorous_reps: int = _int("RIGOROUS_REPS", 25)
    rigorous_warmup: int = _int("RIGOROUS_WARMUP", 3)
    benchmark_budget_quick_s: float = _float("BENCH_BUDGET_QUICK_S", 60.0)
    benchmark_budget_rigorous_s: float = _float("BENCH_BUDGET_RIGOROUS_S", 240.0)
    reliable_min_ms: float = _float("RELIABLE_MIN_MS", 5.0)
    noise_tie_pct: float = _float("NOISE_TIE_PCT", 3.0)

    # Candidate selection
    max_candidates: int = _int("MAX_CANDIDATES", 8)
    min_distinct_valid: int = _int("MIN_DISTINCT_VALID", 4)
    build_workers: int = _int("BUILD_WORKERS", max(1, min(4, (os.cpu_count() or 2))))
    max_concurrent_experiments: int = _int("MAX_CONCURRENT_EXPERIMENTS", 2)

    cors_origins: tuple = tuple(
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
        if o.strip()
    )

    @property
    def db_url(self) -> str:
        return os.environ.get("DATABASE_URL") or f"sqlite:///{(self.results_dir / 'app.db').as_posix()}"

    @property
    def experiments_dir(self) -> Path:
        return self.results_dir / "experiments"

    @property
    def work_dir(self) -> Path:
        return self.results_dir / "work"

    @property
    def benchmarks_dir(self) -> Path:
        return self.data_dir / "benchmarks"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def model_path(self) -> Path:
        return self.artifacts_dir / "model.joblib"

    def ensure_dirs(self) -> None:
        for d in (self.artifacts_dir, self.results_dir, self.experiments_dir, self.work_dir,
                  self.benchmarks_dir, self.processed_dir, self.samples_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()

settings.ensure_dirs()
