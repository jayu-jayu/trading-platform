from sqlalchemy import Float, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.db.base import Base


class Portfolio(Base):
    """
    Single global paper-trading portfolio — there is no login, so the whole
    app shares one virtual account. Always exactly one row (id=1),
    created on first startup if missing. See services/paper_trading.py.
    """
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(primary_key=True)
    virtual_capital: Mapped[float] = mapped_column(Float, default=500_000.0)
    available_capital: Mapped[float] = mapped_column(Float, default=500_000.0)
    total_realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
