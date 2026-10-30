"""Correctness oracle: every variant must reproduce the baseline's exit code and stdout exactly."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from .process import ProcResult, run


@dataclass
class Reference:
    inputs: list[bytes]
    outputs: list[ProcResult] = field(default_factory=list)
    ok: bool = True
    reason: str | None = None


def run_exe(exe: Path, stdin: bytes, timeout: float | None = None) -> ProcResult:
    return run([str(exe)], cwd=exe.parent, timeout=timeout or settings.run_timeout_s, stdin=stdin,
               limit_resources=True)


def build_reference(exe: Path, inputs: list[bytes]) -> Reference:
    ref = Reference(inputs=inputs)
    for data in inputs:
        r = run_exe(exe, data)
        ref.outputs.append(r)
        if r.timed_out:
            ref.ok, ref.reason = False, f"baseline timed out after {settings.run_timeout_s:g}s"
            return ref
        if r.output_truncated:
            ref.ok, ref.reason = False, "baseline output exceeded the output-size limit"
            return ref
        if r.error:
            ref.ok, ref.reason = False, r.error
            return ref
    return ref


def check_against(ref: Reference, exe: Path) -> tuple[bool, str | None]:
    for idx, data in enumerate(ref.inputs):
        r = run_exe(exe, data)
        base = ref.outputs[idx]
        if r.timed_out:
            return False, f"timed out on test input {idx + 1}"
        if r.error:
            return False, r.error
        if r.returncode != base.returncode:
            return False, f"exit code {r.returncode} != baseline {base.returncode} (input {idx + 1})"
        if r.stdout != base.stdout:
            return False, f"stdout differs from baseline on test input {idx + 1}"
    return True, None
