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
from app.services.data_fetcher import fetch_full_scan_data, fetch_5m_batch
from app.services.signal_engine import (
    evaluate_symbol, get_market_regime, check_time_window, is_market_open, DEVELOPING_THRESHOLD,
)
from app.services.market_analysis import classify_market_regime
from app.services.mtf_engine import check_mtf_confirmation
from app.services.indicators import chart_result_to_df, add_indicators
from app.services.sector_map import get_sector_proxy
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

    # Phase 2: richer regime classification (TRENDING_UP/DOWN, SIDEWAYS,
    # HIGH_VOLATILITY), computed once from the SAME Nifty data already
    # fetched for the existing binary gatekeeper above. This is diagnostic
    # enrichment only — market_regime (BULLISH/BEARISH) above still
    # governs the actual gate, completely unchanged.
    nifty_df = chart_result_to_df(batch["nifty"].get("raw") if batch["nifty"] else None)
    market_regime_detail = None
    if nifty_df is not None and len(nifty_df) >= 30:
        market_regime_detail = classify_market_regime(add_indicators(nifty_df))

    # Every symbol is evaluated regardless of market regime — this is what
    # gives you visibility into "these 3 would qualify if only the market
    # gate were open" instead of an opaque empty scan.
    eval_tasks = []
    for sym in stocks:
        eval_tasks.append(evaluate_symbol(
            symbol=sym, asset_type="STOCK", df_15m_raw=batch["15m"].get(sym),
            market_regime=market_regime, sector_15m_raw=_lookup_sector_raw(sym, batch["15m"]),
            market_regime_detail=market_regime_detail, nifty_15m_raw=batch["nifty"],
        ))
    for sym in etfs:
        eval_tasks.append(evaluate_symbol(
            symbol=sym, asset_type="ETF", df_15m_raw=batch["15m"].get(sym),
            market_regime=market_regime, sector_15m_raw=_lookup_sector_raw(sym, batch["15m"]),
            market_regime_detail=market_regime_detail, nifty_15m_raw=batch["nifty"],
        ))

    diagnostics = await asyncio.gather(*eval_tasks)

    # Phase 3, pass 2: MTF confirmation. Only fetch 5m data for symbols
    # that already pass 4+ of the 6 core 15m rules — see mtf_engine.py and
    # data_fetcher.fetch_5m_batch for why this is deliberately targeted
    # rather than run against the whole watchlist every scan.
    eligible_symbols = [d.symbol for d in diagnostics if d.rules_passed_count >= DEVELOPING_THRESHOLD]
    if eligible_symbols:
        batch_5m = await fetch_5m_batch(eligible_symbols)
        for diag in diagnostics:
            if diag.symbol not in batch_5m:
                continue
            raw_15m = batch["15m"].get(diag.symbol)
            df_15m = chart_result_to_df(raw_15m.get("raw") if raw_15m else None)
            if df_15m is None or len(df_15m) < 50:
                continue
            df_15m = add_indicators(df_15m)
            mtf_result = check_mtf_confirmation(df_15m, batch_5m.get(diag.symbol))
            diag.mtf_confirmation = mtf_result

            # Mirror onto the signal payload too, if this symbol qualified —
            # that's what actually gets persisted to signal_history below.
            for payload in (diag.qualified_signal, diag.developing_signal):
                if payload is not None:
                    payload["mtf_confirmed"] = mtf_result.get("confirmed")
                    payload["sector_relative_strength_pct"] = (
                        (diag.sector_relative_strength or {}).get("relative_strength_pct")
                    )

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
        "market_regime_detail": market_regime_detail,
        "diagnostics": [d.to_dict() for d in diagnostics],
    }
    return scan_result


def _lookup_sector_raw(symbol: str, results_15m: dict) -> dict | None:
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
                trend_score=sig.get("trend_score"),
                volume_score=sig.get("volume_score"),
                momentum_score=sig.get("momentum_score"),
                vwap_score=sig.get("vwap_score"),
                market_score=sig.get("market_score"),
                market_regime_detail=sig.get("market_regime_detail"),
                mtf_confirmed=sig.get("mtf_confirmed"),
                sector_relative_strength_pct=sig.get("sector_relative_strength_pct"),
            )
            session.add(record)
            records.append(record)

        await session.commit()
        for record in records:
            await session.refresh(record)

        return [{**sig, "id": r.id, "outcome": r.outcome, "generated_at": r.generated_at}
                for sig, r in zip(signals, records)]
