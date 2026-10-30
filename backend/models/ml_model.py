from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .experiment import utcnow


class MLModelRecord(Base):
    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dataset_version: Mapped[str] = mapped_column(String(64))
    dataset_size: Mapped[int] = mapped_column(Integer)
    model_type: Mapped[str] = mapped_column(String(64))
    feature_schema_version: Mapped[str] = mapped_column(String(16))
    training_mode: Mapped[str] = mapped_column(String(16), default="quick")
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="ready")
    training_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class BenchmarkSample(Base):
    """One measured (program, input, strategy) cell collected while building the training set."""

    __tablename__ = "benchmark_samples"
    __table_args__ = (Index("ix_samples_run_program", "benchmark_id", "program_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_id: Mapped[str] = mapped_column(String(64), index=True)
    program_id: Mapped[str] = mapped_column(String(128))
    family: Mapped[str] = mapped_column(String(64))
    input_id: Mapped[str] = mapped_column(String(64), default="default")
    strategy_id: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    times_ms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    median_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    binary_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compile_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    correctness_status: Mapped[str] = mapped_column(String(20))
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    environment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
