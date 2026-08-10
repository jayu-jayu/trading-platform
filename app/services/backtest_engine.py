"""
Walk-forward backtest engine — reuses evaluate_symbol() from signal_engine.py
directly via the as_of parameter, so backtested behavior is guaranteed
identical to live scanning behavior (per the "one unified signal engine"
architecture decision). This module contains NO trading logic of its own —
only simulation mechanics: slicing historical candles, calling the engine
at each step, and tracking simulated entries/exits.

Reads exclusively from price_cache (never hits Yahoo directly) — populate
the cache first via services/price_cache.populate_cache().

LOOKAHEAD BIAS: the single most important correctness property of a
backtest. At simulated step i, evaluate_symbol() is only ever shown
candles[0:i+1] — never a candle whose timestamp is later than the moment
being simulated. This is enforced structurally (each step builds a fresh,
truncated slice) rather than relying on a flag, so it can't be silently
broken by a future edit that forgets to set something.
"""
from datetime import datetime, timedelta
import pandas as pd
import pytz

from app.config import settings
from app.services.price_cache import get_cached_candles
from app.services.signal_engine import evaluate_symbol, get_market_regime
from app.services.market_analysis import classify_market_regime
from app.services.indicators import chart_result_to_df, add_indicators
from app.services.sector_map import get_sector_proxy
from app.models.backtest import BacktestRun, BacktestTrade
from app.db.session import AsyncSessionLocal

IST = pytz.timezone("Asia/Kolkata")

MIN_LOOKBACK_CANDLES = 30  # matches evaluate_symbol's own >=25 requirement, with a small buffer


def _candles_to_raw(candles: list) -> dict:
    """
    Converts a list of PriceCache rows into the same raw-JSON shape
    chart_result_to_df() expects from a live Yahoo fetch. This is the
    bridge that lets evaluate_symbol() run completely unmodified in its
    data-parsing path — the backtest engine never touches that logic,
    it only feeds it historical data shaped exactly like live data.
    """
    if not candles:
        return {"raw": None}
    return {
        "raw": {
            "timestamp": [int(c.candle_timestamp.timestamp()) for c in candles],
            "indicators": {
                "quote": [{
                    "open": [c.open for c in candles],
                    "high": [c.high for c in candles],
                    "low": [c.low for c in candles],
                    "close": [c.close for c in candles],
                    "volume": [c.volume for c in candles],
                }]
            },
        }
    }


def _localize(candles: list) -> list:
    """PriceCache stores naive UTC-equivalent timestamps (from Yahoo's epoch
    seconds via chart_result_to_df, which localizes to Asia/Kolkata then the
    ORM strips tzinfo on write) — re-attach IST tzinfo so as_of comparisons
    against signal_engine's IST-aware time-window logic are correct."""
    out = []
    for c in candles:
        ts = c.candle_timestamp
        if ts.tzinfo is None:
            ts = IST.localize(ts)
        c.candle_timestamp = ts
        out.append(c)
    return out


async def _simulate_exit(symbol: str, interval: str, entry_time: datetime,
                          entry_price: float, stop_loss: float, target: float) -> dict:
    """Walks forward from entry_time through same-day cached candles,
    checking each candle's high/low against target/stop_loss. Bounded to
    the entry day, matching this platform's intraday-only design — no
    overnight holds are simulated."""
    day_end = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)
    future_candles = await get_cached_candles(symbol, interval, start=entry_time + timedelta(minutes=1), end=day_end)
    future_candles = _localize(future_candles)

    for c in future_candles:
        if c.high >= target:
            return {"exit_time": c.candle_timestamp, "exit_price": target, "exit_reason": "TARGET_HIT"}
        if c.low <= stop_loss:
            return {"exit_time": c.candle_timestamp, "exit_price": stop_loss, "exit_reason": "SL_HIT"}

    if future_candles:
        last = future_candles[-1]
        return {"exit_time": last.candle_timestamp, "exit_price": last.close, "exit_reason": "EOD_EXIT"}

    # No further candles at all (e.g. entry was the last cached candle) —
    # can't determine an exit; caller discards this as an incomplete trade.
    return {"exit_time": None, "exit_price": None, "exit_reason": "NO_EXIT_DATA"}


async def run_backtest(symbols: list[str], start_date: datetime, end_date: datetime,
                        interval: str = "15m", label: str | None = None) -> int:
    """
    Runs a walk-forward simulation over `symbols` between start_date and
    end_date (both should exist in price_cache already — this function
    does not fetch from Yahoo). Persists a BacktestRun + one BacktestTrade
    per simulated entry, returns the new run's id.
    """
    async with AsyncSessionLocal() as session:
        run = BacktestRun(
            label=label, symbols=symbols, interval=interval,
            start_date=start_date, end_date=end_date, status="RUNNING",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    try:
        trades: list[dict] = []

        # Pre-load Nifty candles once — every symbol's market-regime check
        # depends on the same index data.
        nifty_candles = _localize(await get_cached_candles(settings.NIFTY_INDEX_SYMBOL, interval, start_date, end_date))

        # Pre-load every sector proxy ETF's candles once too (small, fixed set).
        sector_candle_cache: dict[str, list] = {}
        for etf in settings.ETF_WATCHLIST:
            sector_candle_cache[etf] = _localize(await get_cached_candles(etf, interval, start_date, end_date))

        for symbol in symbols:
            asset_type = "ETF" if symbol in settings.ETF_WATCHLIST else "STOCK"
            candles = _localize(await get_cached_candles(symbol, interval, start_date, end_date))
            if len(candles) < MIN_LOOKBACK_CANDLES:
                continue  # not enough history cached for this symbol — skip, don't fabricate data

            sector_proxy_symbol = get_sector_proxy(symbol)
            sector_candles = sector_candle_cache.get(sector_proxy_symbol, [])

            blocked_until: datetime | None = None  # don't re-signal while a simulated trade is still open

            for i in range(MIN_LOOKBACK_CANDLES, len(candles)):
                as_of = candles[i].candle_timestamp

                if blocked_until and as_of <= blocked_until:
                    continue

                window = candles[: i + 1]  # STRICT truncation — nothing beyond `as_of` is ever visible

                # Align Nifty/sector windows to the same as_of boundary
                nifty_window = [c for c in nifty_candles if c.candle_timestamp <= as_of]
                sector_window = [c for c in sector_candles if c.candle_timestamp <= as_of]

                if len(nifty_window) < 25:
                    continue

                market_regime = get_market_regime({"raw": _candles_to_raw(nifty_window)["raw"]})

                # Phase 2: same richer regime classification scanner.py computes
                # for live scans, from the same truncated Nifty window — keeps
                # backtested confidence scores consistent with live ones instead
                # of silently falling back to a neutral default.
                nifty_window_df = chart_result_to_df(_candles_to_raw(nifty_window)["raw"])
                market_regime_detail = None
                if nifty_window_df is not None and len(nifty_window_df) >= 30:
                    market_regime_detail = classify_market_regime(add_indicators(nifty_window_df))

                df_raw = _candles_to_raw(window)
                sector_raw = _candles_to_raw(sector_window) if sector_window else None

                diag = await evaluate_symbol(
                    symbol=symbol, asset_type=asset_type, df_15m_raw=df_raw,
                    market_regime=market_regime, sector_15m_raw=sector_raw, as_of=as_of,
                    market_regime_detail=market_regime_detail,
                )

                signal = diag.qualified_signal or diag.developing_signal
                if not signal:
                    continue

                exit_info = await _simulate_exit(
                    symbol, interval, as_of, signal["entry_price"], signal["stop_loss"], signal["target"],
                )
                if exit_info["exit_price"] is None:
                    continue  # incomplete trade (ran out of cached data) — don't count it

                pnl = round(exit_info["exit_price"] - signal["entry_price"], 4)
                pnl_pct = round((pnl / signal["entry_price"]) * 100, 4)

                trades.append({
                    "symbol": symbol, "asset_type": asset_type, "tier": signal["tier"],
                    "rules_passed": signal["rules_passed"],
                    "entry_time": as_of, "entry_price": signal["entry_price"],
                    "stop_loss": signal["stop_loss"], "target": signal["target"],
                    "exit_time": exit_info["exit_time"], "exit_price": exit_info["exit_price"],
                    "exit_reason": exit_info["exit_reason"], "pnl": pnl, "pnl_pct": pnl_pct,
                })
                blocked_until = exit_info["exit_time"]  # next eligible signal must be strictly after this

        summary = _summarize(trades)

        async with AsyncSessionLocal() as session:
            for t in trades:
                session.add(BacktestTrade(run_id=run_id, **t))

            run = await session.get(BacktestRun, run_id)
            run.total_trades = summary["total_trades"]
            run.institutional_trades = summary["institutional_trades"]
            run.developing_trades = summary["developing_trades"]
            run.winning_trades = summary["winning_trades"]
            run.win_rate_pct = summary["win_rate_pct"]
            run.profit_factor = summary["profit_factor"]
            run.max_drawdown_pct = summary["max_drawdown_pct"]
            run.total_pnl = summary["total_pnl"]
            run.status = "COMPLETE"
            run.completed_at = datetime.utcnow()
            await session.commit()

        return run_id

    except Exception as exc:
        async with AsyncSessionLocal() as session:
            run = await session.get(BacktestRun, run_id)
            run.status = "FAILED"
            run.error_detail = str(exc)[:1000]
            run.completed_at = datetime.utcnow()
            await session.commit()
        raise


def _summarize(trades: list[dict]) -> dict:
    """
    Simplified equity-curve stats — NOT capital/position-size based (the
    backtest engine doesn't simulate quantity or account balance, only
    per-unit price movement). Profit factor and drawdown here describe the
    strategy's raw price behavior, not a portfolio outcome. Treat this as
    a foundation for comparing rule changes, not a finished P&L report.
    """
    total = len(trades)
    if total == 0:
        return {
            "total_trades": 0, "institutional_trades": 0, "developing_trades": 0,
            "winning_trades": 0, "win_rate_pct": None, "profit_factor": None,
            "max_drawdown_pct": None, "total_pnl": None,
        }

    institutional = sum(1 for t in trades if t["tier"] == "INSTITUTIONAL")
    developing = sum(1 for t in trades if t["tier"] == "DEVELOPING")
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

    # Max drawdown on the cumulative pnl curve, in absolute price-point terms
    # expressed as a percentage of the peak (guards against div-by-zero when
    # the curve never goes positive).
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["entry_time"]):
        cumulative += t["pnl"]
        peak = max(peak, cumulative)
        if peak > 0:
            max_dd = max(max_dd, (peak - cumulative) / peak * 100)

    return {
        "total_trades": total,
        "institutional_trades": institutional,
        "developing_trades": developing,
        "winning_trades": len(winners),
        "win_rate_pct": round(len(winners) / total * 100, 2),
        "profit_factor": profit_factor,
        "max_drawdown_pct": round(max_dd, 2),
        "total_pnl": round(sum(t["pnl"] for t in trades), 4),
    }
