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

    # INSTITUTIONAL (6/6, auto-generated) or DEVELOPING (4-5/6, only created
    # when someone explicitly opens a paper position on a developing-tier
    # card). Nullable with a default so this stays backward-compatible with
    # any table created before this column existed — see README for the
    # one-line migration needed on an already-deployed database.
    tier: Mapped[str] = mapped_column(String(20), default="INSTITUTIONAL", nullable=True)

    # Phase 2 additions — all nullable, no default required, so existing
    # rows and any pre-Phase-2 code path remain completely unaffected.
    trend_score: Mapped[float] = mapped_column(Float, nullable=True)
    volume_score: Mapped[float] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float] = mapped_column(Float, nullable=True)
    vwap_score: Mapped[float] = mapped_column(Float, nullable=True)
    market_score: Mapped[float] = mapped_column(Float, nullable=True)
    market_regime_detail: Mapped[str] = mapped_column(String(20), nullable=True)  # TRENDING_UP/DOWN, SIDEWAYS, HIGH_VOLATILITY

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
