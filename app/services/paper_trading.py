"""
Paper trading against the single shared portfolio (no login, no per-user
scoping — see models/portfolio.py). get_or_create_portfolio ensures the
one row always exists.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models.position import Position
from app.models.portfolio import Portfolio
from app.models.signal import SignalHistory
from app.config import settings

PORTFOLIO_ID = 1  # single-tenant app — always this row


async def get_or_create_portfolio(db: AsyncSession) -> Portfolio:
    result = await db.execute(select(Portfolio).where(Portfolio.id == PORTFOLIO_ID))
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        portfolio = Portfolio(
            id=PORTFOLIO_ID,
            virtual_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
            available_capital=settings.DEFAULT_VIRTUAL_CAPITAL,
        )
        db.add(portfolio)
        await db.commit()
        await db.refresh(portfolio)
    return portfolio


def calculate_quantity(available_capital: float, entry_price: float) -> int:
    if entry_price <= 0:
        return 0
    return int(available_capital // entry_price)


async def open_position(db: AsyncSession, signal: SignalHistory) -> Position | None:
    portfolio = await get_or_create_portfolio(db)

    qty = calculate_quantity(portfolio.available_capital, signal.entry_price)
    if qty <= 0:
        return None

    cost = qty * signal.entry_price
    portfolio.available_capital -= cost

    position = Position(
        signal_id=signal.id,
        symbol=signal.symbol,
        entry_price=signal.entry_price,
        quantity=qty,
        stop_loss=signal.stop_loss,
        target=signal.target,
        status="OPEN",
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)
    return position


async def close_position(db: AsyncSession, position: Position, exit_price: float, outcome: str) -> Position:
    pnl = round((exit_price - position.entry_price) * position.quantity, 2)
    position.exit_price = exit_price
    position.realized_pnl = pnl
    position.status = outcome
    position.closed_at = datetime.utcnow()

    portfolio = await get_or_create_portfolio(db)
    portfolio.available_capital += (position.quantity * exit_price)
    portfolio.total_realized_pnl += pnl
    portfolio.total_trades += 1
    if pnl > 0:
        portfolio.winning_trades += 1

    await db.commit()
    await db.refresh(position)
    return position


async def check_open_positions_against_price(db: AsyncSession, symbol: str, current_price: float) -> list[Position]:
    """Called during each scan cycle — auto-closes open positions that hit
    their target or stop-loss at the freshly-fetched price."""
    result = await db.execute(select(Position).where(Position.symbol == symbol, Position.status == "OPEN"))
    positions = result.scalars().all()
    closed = []
    for pos in positions:
        if current_price >= pos.target:
            closed.append(await close_position(db, pos, current_price, "TARGET_HIT"))
        elif current_price <= pos.stop_loss:
            closed.append(await close_position(db, pos, current_price, "SL_HIT"))
    return closed
