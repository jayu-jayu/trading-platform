from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime

from app.db.session import get_db
from app.models.signal import SignalHistory
from app.schemas.signal import SignalListResponse, SignalResponse, MarketStatusResponse
from app.services.scanner import get_cached_scan, run_full_scan, get_market_status
from app.core.websocket_manager import manager as ws_manager

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _to_signal_response(sig: dict) -> SignalResponse:
    extra = {k: v for k, v in sig.items() if k not in ("id", "outcome", "generated_at")}
    return SignalResponse(
        id=sig.get("id", 0),
        outcome=sig.get("outcome", "OPEN"),
        generated_at=sig.get("generated_at", datetime.utcnow()),
        **extra,
    )


@router.get("/", response_model=SignalListResponse)
async def get_latest_signals():
    cache = get_cached_scan()
    return SignalListResponse(
        scan_timestamp=cache["scan_timestamp"],
        market_regime=cache["market_regime"],
        total_scanned=cache["total_scanned"],
        signals=[_to_signal_response(s) for s in cache["signals"]],
    )


@router.post("/scan-now", response_model=SignalListResponse)
async def trigger_manual_scan():
    result = await run_full_scan()
    return SignalListResponse(
        scan_timestamp=result["scan_timestamp"],
        market_regime=result["market_regime"],
        total_scanned=result["total_scanned"],
        signals=[_to_signal_response(s) for s in result["signals"]],
    )


@router.get("/history", response_model=list[SignalResponse])
async def get_signal_history(symbol: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)):
    query = select(SignalHistory).order_by(desc(SignalHistory.generated_at)).limit(limit)
    if symbol:
        query = query.where(SignalHistory.symbol == symbol)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/market-status", response_model=MarketStatusResponse)
async def market_status():
    return MarketStatusResponse(**get_market_status())


@router.websocket("/ws")
async def signals_websocket(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
