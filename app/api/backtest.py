"""
Backtest API — entirely new, additive route file. Does not modify or
depend on any existing signal/portfolio/price endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.backtest import BacktestRun, BacktestTrade
from app.schemas.backtest import (
    BacktestRunRequest, BacktestRunResponse, BacktestRunDetail, CachePopulateRequest,
)
from app.services.backtest_engine import run_backtest
from app.services.price_cache import populate_cache

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/cache/populate")
async def populate_price_cache(payload: CachePopulateRequest):
    """
    Populate the historical price cache before running a backtest — this
    hits Yahoo Finance once per symbol and stores the result; the backtest
    engine itself never fetches live data. Run this first for any symbol
    set you want to backtest.
    """
    summary = await populate_cache(payload.symbols, interval=payload.interval, rng=payload.rng)
    return summary


@router.post("/run", response_model=BacktestRunResponse)
async def start_backtest(payload: BacktestRunRequest, db: AsyncSession = Depends(get_db)):
    """
    Runs a walk-forward backtest synchronously and returns the completed
    result. For large symbol sets / long ranges this can take a while —
    each simulated step reuses the exact same rule engine as live scanning
    (see services/backtest_engine.py's as_of usage). Requires the price
    cache to already cover the requested symbols/date range — populate it
    via POST /api/backtest/cache/populate first.
    """
    try:
        run_id = await run_backtest(
            symbols=payload.symbols, start_date=payload.start_date, end_date=payload.end_date,
            interval=payload.interval, label=payload.label,
        )
    except Exception as exc:
        raise HTTPException(500, f"Backtest failed: {exc}")

    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(500, "Backtest run vanished after completion — this should not happen.")
    return run


@router.get("/runs", response_model=list[BacktestRunResponse])
async def list_backtest_runs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit))
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=BacktestRunDetail)
async def get_backtest_run(run_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Backtest run not found")

    trades_result = await db.execute(
        select(BacktestTrade).where(BacktestTrade.run_id == run_id).order_by(BacktestTrade.entry_time)
    )
    trades = trades_result.scalars().all()

    response = BacktestRunDetail.model_validate(run)
    response.trades = trades
    return response
