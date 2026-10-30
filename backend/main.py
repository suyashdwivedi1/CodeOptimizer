from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import analyze, experiments, health, ml, optimize
from .compiler import detection
from .config import settings
from .database import init_db, session_scope
from .models import Experiment


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    detection.detect()
    with session_scope() as s:  # experiments interrupted by a server restart can never finish
        for e in s.query(Experiment).filter(Experiment.status.in_(["queued", "running"])).all():
            e.status, e.error_summary = "failed", "Server restarted while the experiment was running"
    yield


app = FastAPI(title="AI-Driven Adaptive Compiler Optimization", version=__version__, lifespan=lifespan,
              description="Compiles, optimises (LLVM), benchmarks and ML-ranks C/C++ programs.")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])
for r in (health.router, analyze.router, optimize.router, experiments.router, ml.router):
    app.include_router(r)


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def validation_exc(_: Request, exc: RequestValidationError):
    errs = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Invalid request", "details": errs}})


DIST = settings.root / "frontend" / "dist"
if DIST.is_dir():  # optional: serve the production UI from the same process
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api"):
            raise HTTPException(404, detail={"code": "not_found", "message": "Unknown API route"})
        f = (DIST / path).resolve()
        return FileResponse(f if f.is_file() and DIST.resolve() in f.parents else DIST / "index.html")
