"""
Replay Shadow Ledger — the "gold dataset" from the FINAL ARCHITECTURAL
BLUEPRINT (item #2). An INDEPENDENT, invisible record of every qualifying
signal's simulated outcome, tracking BOTH institutional and developing
tiers, entirely separate from the user's visible paper-trading portfolio
(app/models/position.py) so it never spends real virtual capital or
interferes with anything the user sees on the dashboard.

This model is new in this rebuild. The mechanism that POPULATES it (a
background process that watches live signals and auto-records outcomes)
is NOT yet built — that's later Phase work, scoped and confirmed with the
user before implementation, per the "one phase at a time" rule. This file
only adds the schema so the shape is settled and stable before any writer
depends on it.
"""
from sqlalchemy import String, Float, DateTime, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.db.base import Base


class ShadowLedgerEntry(Base):
    """
    One row per qualifying signal (institutional OR developing), recording
    its full context and eventual simulated outcome — independent of
    whether the user ever opened a real paper position on it. This is what
    accumulates the long-term, unbiased dataset for future rule-weight
    tuning (Phase 4), since it captures EVERY signal's fate, not just the
    ones a person happened to click on.
    """
    __tablename__ = "shadow_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Links back to the originating signal_history row when one exists
    # (institutional signals always have one; developing-tier entries may
    # be logged here even if the user never opened a position, in which
    # case signal_id stays null until/unless that changes in a later phase).
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signal_history.id"), nullable=True)

    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(10), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # INSTITUTIONAL | DEVELOPING

    confidence_score: Mapped[int] = mapped_column(Integer, nullable=True)
    rules_passed: Mapped[list] = mapped_column(JSON, default=list)
    market_regime: Mapped[str] = mapped_column(String(20), nullable=True)

    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target_1: Mapped[float] = mapped_column(Float, nullable=False)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)  # reserved for Phase 5 smart-exit work

    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Per-rule score breakdown (Trend/Volume/Momentum/VWAP/Market) — schema
    # ready for the Confidence Score Engine refinement (Phase 2), populated
    # as null until that scoring model exists.
    trend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # False Signal Analyzer field (Phase blueprint item #6) — populated
    # once that module exists; schema is ready for it now.
    failure_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Future-ready per the blueprint ("Screenshot (future-ready)") — stores
    # a reference/path, not binary image data, keeping this table lightweight.
    screenshot_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)  # OPEN | CLOSED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
