from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..analysis import diagnostics as dg
from ..compiler import detection
from ..config import settings
from ..schemas import AnalyzeRequest
from ..services import analysis_service

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    d = detection.detect()
    if not (d["can_compile_cpp"] if req.language == "cpp" else d["can_compile_c"]):
        raise HTTPException(503, detail={"code": "compiler_missing", "message": "; ".join(d["problems"]) or "Compiler not found"})
    try:
        return await run_in_threadpool(analysis_service.analyze_source, req.source, req.language, req.filename)
    except dg.ValidationError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)})


@router.post("/upload")
async def upload(file: UploadFile = File(...), language: str | None = Form(None)):
    """Validate an uploaded file (extension, size, encoding, NUL bytes) and return its text for editing in the UI."""
    name = Path(file.filename or "").name
    lang = dg.language_from_filename(name)
    if lang is None:
        raise HTTPException(422, detail={"code": "bad_extension", "message": f"Unsupported extension '{Path(name).suffix or '(none)'}'. Allowed: .c, .cpp, .cc, .cxx"})
    raw = await file.read(settings.max_source_bytes + 1)
    if len(raw) > settings.max_source_bytes:
        raise HTTPException(413, detail={"code": "too_large", "message": f"File exceeds {settings.max_source_bytes} bytes"})
    if b"\x00" in raw:
        raise HTTPException(422, detail={"code": "binary", "message": "File contains NUL bytes; it does not look like source code."})
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, detail={"code": "bad_encoding", "message": "File is not valid UTF-8 text."})
    if not text.strip():
        raise HTTPException(422, detail={"code": "empty", "message": "File is empty."})
    return {"filename": name, "language": lang, "source": text, "bytes": len(raw)}


@router.get("/samples")
def samples():
    out = []
    for p in sorted(settings.samples_dir.glob("*")):
        if p.suffix.lower() in dg.EXT_LANG:
            first = p.read_text(encoding="utf-8").splitlines()[0:1]
            out.append({"name": p.name, "language": dg.EXT_LANG[p.suffix.lower()],
                        "title": first[0].lstrip("/ *").strip() if first else p.name})
    return out


@router.get("/samples/{name}")
def sample(name: str):
    p = settings.samples_dir / Path(name).name  # strips any directory component
    if not p.is_file() or p.suffix.lower() not in dg.EXT_LANG:
        raise HTTPException(404, detail={"code": "not_found", "message": "No such sample"})
    stdin_p = p.with_suffix(".stdin")
    return {"name": p.name, "language": dg.EXT_LANG[p.suffix.lower()], "source": p.read_text(encoding="utf-8"),
            "stdin": stdin_p.read_text(encoding="utf-8") if stdin_p.exists() else ""}
