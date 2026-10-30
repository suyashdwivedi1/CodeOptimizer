from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    source: str = Field(..., description="C or C++ source text")
    language: Literal["c", "cpp"] = "c"
    filename: str | None = Field(None, max_length=255)


class OptimizeRequest(AnalyzeRequest):
    label: str | None = Field(None, max_length=255)
    stdin: str = ""
    mode: Literal["quick", "rigorous"] = "quick"
    repetitions: int | None = Field(None, ge=3, le=200)
    use_ml: bool = True


class OptimizeResponse(BaseModel):
    experiment_id: str
    events_url: str
    results_url: str


class WhatIfRequest(BaseModel):
    strategies: list[str] = Field(..., min_length=1, max_length=12)


class TrainRequest(BaseModel):
    mode: Literal["quick", "full"] = "quick"
    reps: int | None = Field(None, ge=3, le=30)
    skip_collect: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | list | None = None
