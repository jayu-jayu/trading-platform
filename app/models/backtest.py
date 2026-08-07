"""
Backtest results, persisted so runs are comparable over time (needed for
later phases: walk-forward validation, before/after comparisons when
tuning rules). A BacktestRun is one simulation over a symbol set + date
range; each BacktestTrade is one simulated entry/exit within that run.
"""
from sqlalchemy import String, Float, DateTime, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.db.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=True)
    symbols: Mapped[list] = mapped_column(JSON, nullable=False)
    interval: Mapped[str] = mapped_column(String(10), default="15m")
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    institutional_trades: Mapped[int] = mapped_column(Integer, default=0)
    developing_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate_pct: Mapped[float] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=True)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING | COMPLETE | FAILED
    error_detail: Mapped[str] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(10), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # INSTITUTIONAL | DEVELOPING
    rules_passed: Mapped[list] = mapped_column(JSON, default=list)

    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)

    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(30), nullable=True)  # TARGET_HIT | SL_HIT | EOD_EXIT
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
