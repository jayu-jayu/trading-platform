from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.db.session import get_db
from app.models.position import Position
from app.models.signal import SignalHistory
from app.schemas.portfolio import PortfolioResponse, OpenPositionRequest, OpenCandidateRequest, PositionResponse
from app.services.paper_trading import open_position, close_position, get_or_create_portfolio, open_candidate_position

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/", response_model=PortfolioResponse)
async def get_portfolio(db: AsyncSession = Depends(get_db)):
    portfolio = await get_or_create_portfolio(db)

    open_result = await db.execute(select(Position).where(Position.status == "OPEN"))
    open_positions = open_result.scalars().all()

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    closed_result = await db.execute(
        select(Position).where(Position.status != "OPEN", Position.closed_at >= today_start)
    )
    closed_today = closed_result.scalars().all()

    win_rate = (portfolio.winning_trades / portfolio.total_trades * 100) if portfolio.total_trades else 0.0

    return PortfolioResponse(
        virtual_capital=portfolio.virtual_capital,
        available_capital=portfolio.available_capital,
        total_realized_pnl=portfolio.total_realized_pnl,
        total_trades=portfolio.total_trades,
        winning_trades=portfolio.winning_trades,
        win_rate_pct=round(win_rate, 1),
        open_positions=open_positions,
        closed_positions_today=closed_today,
    )


@router.post("/positions/open", response_model=PositionResponse)
async def open_new_position(payload: OpenPositionRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SignalHistory).where(SignalHistory.id == payload.signal_id))
    signal = result.scalar_one_or_none()
    if signal is None:
        raise HTTPException(404, "Signal not found")

    position = await open_position(db, signal)
    if position is None:
        raise HTTPException(400, "Insufficient available capital for this position")
    return position


@router.post("/positions/open-candidate", response_model=PositionResponse)
async def open_candidate(payload: OpenCandidateRequest, db: AsyncSession = Depends(get_db)):
    """
    Opens a paper position directly from a DEVELOPING-tier card's computed
    values. This is the only path that writes a developing-tier signal to
    signal_history — it's created lazily, at the moment someone acts on it,
    rather than eagerly on every scan like institutional signals are.
    """
    position = await open_candidate_position(db, payload.model_dump())
    if position is None:
        raise HTTPException(400, "Insufficient available capital for this position")
    return position


@router.post("/positions/{position_id}/close", response_model=PositionResponse)
async def close_existing_position(position_id: int, exit_price: float, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(404, "Position not found")
    if position.status != "OPEN":
        raise HTTPException(400, "Position already closed")

    return await close_position(db, position, exit_price, "MANUALLY_CLOSED")
