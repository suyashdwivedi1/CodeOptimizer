"""Per-experiment progress events. Pipeline threads `emit`; the SSE endpoint polls `events_after`.
Events are mirrored to results/experiments/<id>/events.jsonl so reconnects (and server restarts) can replay them."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings

STAGES = [
    ("source_received", "Source received"),
    ("input_validation", "Input validation"),
    ("compiler_check", "Compiler availability check"),
    ("compilation", "Compilation & syntax validation"),
    ("ir_generation", "LLVM IR generation"),
    ("feature_extraction", "Feature extraction"),
    ("ml_inference", "ML inference"),
    ("candidate_generation", "Candidate strategy generation"),
    ("optimization", "Optimization execution"),
    ("variant_compilation", "Compilation of variants"),
    ("correctness", "Correctness checks"),
    ("benchmark", "Benchmark execution"),
    ("ranking", "Result ranking"),
    ("report", "Report generation"),
]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class Bus:
    def __init__(self, exp_id: str):
        self.exp_id = exp_id
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.terminal = False
        self.t0 = time.perf_counter()
        d = settings.experiments_dir / exp_id
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / "events.jsonl"


_buses: dict[str, Bus] = {}
_buses_lock = threading.Lock()


def get_bus(exp_id: str, create: bool = True) -> Bus | None:
    with _buses_lock:
        b = _buses.get(exp_id)
        if b is None and create:
            b = Bus(exp_id)
            _buses[exp_id] = b
        return b


def emit(exp_id: str, stage: str, status: str, message: str = "", data: dict | None = None,
         elapsed_ms: float | None = None) -> dict:
    b = get_bus(exp_id)
    with b.lock:
        ev = {"seq": len(b.events) + 1, "experiment_id": exp_id, "stage": stage, "status": status, "message": message,
              "ts": datetime.now(timezone.utc).isoformat(), "t_ms": round((time.perf_counter() - b.t0) * 1000, 1),
              "elapsed_ms": None if elapsed_ms is None else round(elapsed_ms, 1), "data": data or {}}
        b.events.append(ev)
        if stage == "experiment" and status in TERMINAL_STATUSES:
            b.terminal = True
        try:
            with open(b.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        except OSError:
            pass
    return ev


def _load_from_disk(exp_id: str) -> list[dict]:
    p = settings.experiments_dir / exp_id / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def events_after(exp_id: str, after: int = 0) -> tuple[list[dict], bool]:
    """Return (events with seq > after, is_terminal)."""
    with _buses_lock:
        b = _buses.get(exp_id)
    if b is not None:
        with b.lock:
            return [e for e in b.events if e["seq"] > after], b.terminal
    evs = _load_from_disk(exp_id)
    term = any(e["stage"] == "experiment" and e["status"] in TERMINAL_STATUSES for e in evs)
    return [e for e in evs if e["seq"] > after], term


def request_cancel(exp_id: str) -> bool:
    b = get_bus(exp_id, create=False)
    if b is None or b.terminal:
        return False
    b.cancel.set()
    return True


def forget(exp_id: str) -> None:
    with _buses_lock:
        _buses.pop(exp_id, None)
