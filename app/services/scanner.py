"""
Scan orchestrator: one concurrent batch fetches Nifty + every stock/ETF in
the watchlist, then the engine evaluates EVERY symbol and keeps a full
diagnostic breakdown — not just the ones that qualify — so the dashboard
can show exactly why each symbol did or didn't produce a signal.
"""
import asyncio
from datetime import datetime
import pytz

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.data_fetcher import fetch_full_scan_data
from app.services.signal_engine import evaluate_symbol, get_market_regime, check_time_window, is_market_open
from app.core.websocket_manager import manager as ws_manager
from app.models.signal import SignalHistory
from app.db.session import AsyncSessionLocal

IST = pytz.timezone("Asia/Kolkata")

_latest_scan_cache: dict = {
    "scan_timestamp": None,
    "market_regime": "UNKNOWN",
    "total_scanned": 0,
    "signals": [],
    "developing_signals": [],
}

_latest_diagnostics_cache: dict = {
    "scan_timestamp": None,
    "market_regime": "UNKNOWN",
    "diagnostics": [],  # list of SymbolDiagnostics.to_dict()
}


def get_cached_scan() -> dict:
    return _latest_scan_cache


def get_cached_diagnostics() -> dict:
    return _latest_diagnostics_cache


def get_market_status() -> dict:
    now = datetime.now(IST)
    return {
        "is_market_open": is_market_open(now),
        "is_signal_window": check_time_window(now),
        "market_regime": _latest_scan_cache["market_regime"],
        "server_time_ist": now,
    }


async def run_full_scan() -> dict:
    stocks = settings.STOCK_WATCHLIST
    etfs = settings.ETF_WATCHLIST
    all_symbols = stocks + etfs

    batch = await fetch_full_scan_data(all_symbols, settings.NIFTY_INDEX_SYMBOL)
    market_regime = get_market_regime(batch["nifty"])

    # Every symbol is evaluated regardless of market regime — this is what
    # gives you visibility into "these 3 would qualify if only the market
    # gate were open" instead of an opaque empty scan.
    eval_tasks = []
    for sym in stocks:
        eval_tasks.append(evaluate_symbol(
            symbol=sym, asset_type="STOCK", df_15m_raw=batch["15m"].get(sym),
            market_regime=market_regime, sector_15m_raw=_lookup_sector_raw(sym, batch["15m"]),
        ))
    for sym in etfs:
        eval_tasks.append(evaluate_symbol(
            symbol=sym, asset_type="ETF", df_15m_raw=batch["15m"].get(sym),
            market_regime=market_regime, sector_15m_raw=_lookup_sector_raw(sym, batch["15m"]),
        ))

    diagnostics = await asyncio.gather(*eval_tasks)

    qualifying_signals = [d.qualified_signal for d in diagnostics if d.qualified_signal]
    developing_signals = [d.developing_signal for d in diagnostics if d.developing_signal]
    # Rank developing candidates by how many rules they passed, then by
    # strength score, so the strongest near-misses surface first in the feed.
    developing_signals.sort(key=lambda s: (s["rules_passed_count"], s["strength_score"]), reverse=True)

    scan_result = {
        "scan_timestamp": datetime.now(IST),
        "market_regime": market_regime,
        "total_scanned": len(all_symbols),
        "signals": qualifying_signals,
        "developing_signals": developing_signals,  # NOT persisted — display-only until acted on
    }

    if qualifying_signals:
        qualifying_signals = await _persist_signals(qualifying_signals)
        scan_result["signals"] = qualifying_signals
        for sig in qualifying_signals:
            await ws_manager.broadcast({"type": "new_signal", "data": sig})

    global _latest_scan_cache, _latest_diagnostics_cache
    _latest_scan_cache = scan_result
    _latest_diagnostics_cache = {
        "scan_timestamp": scan_result["scan_timestamp"],
        "market_regime": market_regime,
        "diagnostics": [d.to_dict() for d in diagnostics],
    }
    return scan_result


def _lookup_sector_raw(symbol: str, results_15m: dict) -> dict | None:
    from app.services.sector_map import get_sector_proxy
    proxy = get_sector_proxy(symbol)
    return results_15m.get(proxy)


async def _persist_signals(signals: list[dict]) -> list[dict]:
    async with AsyncSessionLocal() as session:  # type: AsyncSession
        records = []
        for sig in signals:
            record = SignalHistory(
                symbol=sig["symbol"],
                asset_type=sig["asset_type"],
                signal_type=sig["signal_type"],
                entry_price=sig["entry_price"],
                stop_loss=sig["stop_loss"],
                target=sig["target"],
                atr_value=sig["atr_value"],
                rsi_value=sig["rsi_value"],
                vwap_value=sig["vwap_value"],
                volume_ratio=sig["volume_ratio"],
                rules_passed=sig["rules_passed"],
                sector_proxy=sig["sector_proxy"],
                market_regime=sig["market_regime"],
                strength_score=sig["strength_score"],
                tier=sig.get("tier", "INSTITUTIONAL"),
            )
            session.add(record)
            records.append(record)

        await session.commit()
        for record in records:
            await session.refresh(record)

        return [{**sig, "id": r.id, "outcome": r.outcome, "generated_at": r.generated_at}
                for sig, r in zip(signals, records)]
