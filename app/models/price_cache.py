"""
Historical OHLCV cache — populated once per symbol/interval range by
services/price_cache.py, then read repeatedly by the backtest engine
instead of re-hitting Yahoo Finance on every backtest run.

This also protects your live scanner's rate-limit headroom: at 140
symbols, a backtest that iterated live fetches for every historical day
would compete with the actual live scan for the same unofficial endpoint.
"""
from sqlalchemy import String, Float, DateTime, Integer, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.db.base import Base


class PriceCache(Base):
    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)  # "15m", "5m", etc.
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # One row per symbol+interval+candle — re-fetching the same range is
        # an upsert, not a duplicate insert.
        UniqueConstraint("symbol", "interval", "candle_timestamp", name="uq_price_cache_symbol_interval_ts"),
        Index("ix_price_cache_symbol_interval_ts", "symbol", "interval", "candle_timestamp"),
    )
