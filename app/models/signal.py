from sqlalchemy import String, Float, DateTime, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.db.base import Base


class SignalHistory(Base):
    """Immutable audit record of every qualifying signal, stock or ETF."""
    __tablename__ = "signal_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(10), default="STOCK")  # STOCK | ETF
    signal_type: Mapped[str] = mapped_column(String(10), default="BUY")

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    atr_value: Mapped[float] = mapped_column(Float, nullable=False)

    rsi_value: Mapped[float] = mapped_column(Float, nullable=True)
    vwap_value: Mapped[float] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float] = mapped_column(Float, nullable=True)

    rules_passed: Mapped[list] = mapped_column(JSON, default=list)
    sector_proxy: Mapped[str] = mapped_column(String(20), nullable=True)  # ETF used for Rule 6
    market_regime: Mapped[str] = mapped_column(String(20), nullable=False)
    strength_score: Mapped[int] = mapped_column(Integer, nullable=True)

    outcome: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
