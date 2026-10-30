from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    language: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    stdin_text: Mapped[str] = mapped_column(Text, default="")
    compiler_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llvm_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="quick")
    repetitions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warmup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ml_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ml_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    selected_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    best_variant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    baseline_median_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_median_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ml_prediction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    complexity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    variants: Mapped[list["Variant"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", order_by="Variant.id"
    )


class Variant(Base):
    __tablename__ = "variants"
    __table_args__ = (Index("ix_variants_exp_strategy", "experiment_id", "strategy_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        String(48), ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(24))  # baseline|level|flags|ir_pipeline|source
    is_baseline: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pipeline: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_passes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    techniques: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ir_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    compile_status: Mapped[str] = mapped_column(String(20), default="pending")
    correctness_status: Mapped[str] = mapped_column(String(20), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    binary_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    median_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    stdev_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    iqr_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    samples_ms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    benchmark_count: Mapped[int] = mapped_column(Integer, default=0)
    speedup: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_reduction_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    compile_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    opt_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_rss_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ml_selected: Mapped[bool] = mapped_column(default=False)
    ml_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_winner: Mapped[bool] = mapped_column(default=False)
    below_threshold: Mapped[bool] = mapped_column(default=False)
    added_via_whatif: Mapped[bool] = mapped_column(default=False)
    remarks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)

    experiment: Mapped[Experiment] = relationship(back_populates="variants")
