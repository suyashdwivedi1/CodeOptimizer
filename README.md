# AI-Driven Adaptive Compiler Optimization (work in progress)

STATUS (honest): backend compiler engine, feature extraction, benchmarking, SSE pipeline, ML training code and REST API
are written; the end-to-end pipeline was smoke-tested on one program. NOT done: React frontend, pytest suite, scripts/,
full README, verification of the API layer (written but never run), model evaluation results.

Setup: python -m venv .venv; pip install -r requirements.txt; needs clang/clang++/opt/llc (LLVM 18 tested on Linux).
Train:  python -m backend.ml.train --mode quick
Run:    python -m uvicorn backend.main:app --port 8000   (docs at /docs)

## Run (frontend added)
Terminal 1: python -m uvicorn backend.main:app --port 8000
Terminal 2: cd frontend && npm install && npm run dev   -> http://127.0.0.1:5173
(or `npm run build` once; the backend then serves the UI itself at http://127.0.0.1:8000)
