"""
Roadmap simulation test suite.

============================================================================
READ THIS BEFORE TRUSTING ANY OUTPUT FROM THIS FILE
============================================================================
This file has TWO categories of tests, and they are NOT the same kind of
thing:

  REAL      — exercises actual, shipped, production code paths
              (app/services/signal_engine.py, app/services/price_cache.py).
              A pass here means real functionality works.

  CONCEPTUAL — small illustrative functions defined INSIDE THIS TEST FILE
              ONLY (prefixed `_conceptual_`), demonstrating the intended
              interface/data shape for Phase 2-4 features that have NOT
              been built into the actual application yet. A pass here
              means the demo function is internally consistent — it says
              NOTHING about whether a real implementation exists, works,
              or has been validated against real market data. Do not
              mistake a green checkmark here for a shipped feature.

Phase 1 tests are REAL. Phase 2, 3, and 4 tests are CONCEPTUAL, clearly
marked as such in each test's docstring and print output.
============================================================================
"""
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import numpy as np
import pytest
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

IST = pytz.timezone("Asia/Kolkata")


def _session_timestamps(num_days: int, start_date: datetime) -> list[datetime]:
    """Real trading-session-only timestamps (09:15-15:15 IST), used across
    multiple tests to build realistic synthetic candle data."""
    ts = []
    for d in range(num_days):
        day = start_date + timedelta(days=d)
        t = IST.localize(datetime(day.year, day.month, day.day, 9, 15))
        end = IST.localize(datetime(day.year, day.month, day.day, 15, 15))
        while t <= end:
            ts.append(t)
            t += timedelta(minutes=15)
    return ts


def _build_raw(ts_list, close, volume) -> dict:
    return {
        "raw": {
            "timestamp": [int(t.timestamp()) for t in ts_list],
            "indicators": {"quote": [{
                "open": (close - 0.1).tolist(), "high": (close + 0.3).tolist(),
                "low": (close - 0.3).tolist(), "close": close.tolist(), "volume": volume.tolist(),
            }]},
        }
    }


# ============================================================================
# PHASE 1 — REAL. Exercises actual app/services/signal_engine.py and
# app/services/price_cache.py.
# ============================================================================

@pytest.mark.asyncio
async def test_phase1_evaluate_symbol_as_of_is_deterministic():
    """
    REAL TEST. Confirms evaluate_symbol() produces IDENTICAL rule results
    regardless of the `as_of` timestamp passed in — proving the unified
    signal engine has no hidden datetime.now() dependency in its rule
    logic, which is the entire premise the backtest/replay engines rely on
    for trustworthy results (see signal_engine.py's evaluate_symbol docstring).
    """
    from app.services.signal_engine import evaluate_symbol

    ts_list = _session_timestamps(3, datetime(2026, 8, 3))
    n = len(ts_list)
    close = np.concatenate([
        np.linspace(100, 90, n // 3), np.linspace(90, 93, n // 3),
        np.linspace(93, 107, n - 2 * (n // 3)),
    ])
    volume = np.random.randint(9000, 11000, n).astype(float)
    volume[-5:] = 40000
    raw = _build_raw(ts_list, close, volume)

    # No as_of (defaults to real current time — live-scanner call pattern)
    diag_live = await evaluate_symbol("NIFTYBEES.NS", "ETF", raw, "BULLISH", None)

    # Explicit as_of during market hours — backtest/replay call pattern
    forced_time = IST.localize(datetime(2026, 8, 5, 11, 0))
    diag_backtest = await evaluate_symbol("NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time)

    live_rules = [(r.rule_id, r.passed) for r in diag_live.rule_results]
    backtest_rules = [(r.rule_id, r.passed) for r in diag_backtest.rule_results]

    assert live_rules == backtest_rules, (
        "Rule evaluation must be identical regardless of as_of — if this "
        "fails, the backtest/replay engines are no longer trustworthy."
    )
    print(f"\n[PHASE 1 - REAL] Rule results identical with/without as_of: {live_rules}")


@pytest.mark.asyncio
async def test_phase1_price_cache_populate_and_read():
    """REAL TEST. Exercises the actual price cache populate/upsert/read cycle."""
    from app.services.price_cache import populate_cache, get_cached_candles

    async def fake_fetch_all(symbols, interval="15m", rng="5d"):
        ts_list = _session_timestamps(2, datetime(2026, 8, 3))
        n = len(ts_list)
        results = []
        for sym in symbols:
            close = 100 + np.linspace(0, 2, n) + np.random.normal(0, 0.1, n)
            volume = np.random.randint(9000, 11000, n).astype(float)
            results.append({"symbol": sym, "error": None, "raw": _build_raw(ts_list, close, volume)["raw"]})
        return results

    with patch("app.services.price_cache.fetch_all", fake_fetch_all):
        summary = await populate_cache(["RELIANCE.NS"], interval="15m", rng="5d")
        assert summary["errors"] == []
        assert summary["candles_stored"] > 0

        # Re-populate to confirm upsert doesn't duplicate rows
        await populate_cache(["RELIANCE.NS"], interval="15m", rng="5d")

    candles = await get_cached_candles("RELIANCE.NS", "15m")
    assert len(candles) == summary["candles_stored"], "Re-populating must upsert, not duplicate rows"
    print(f"\n[PHASE 1 - REAL] Cached {len(candles)} candles, confirmed idempotent upsert.")


# ============================================================================
# PHASE 2 — CONCEPTUAL SIMULATION ONLY.
# Market Regime Detection (Trending/Sideways) and Pivot Level Filters do
# NOT exist in app/services/ yet. These are standalone illustrative
# functions demonstrating the intended interface and standard textbook
# formulas (classic floor-trader pivot points), not a validated feature.
# ============================================================================

def _conceptual_classify_regime(close: pd.Series, atr: pd.Series) -> str:
    """CONCEPTUAL ONLY — not wired into the live engine. Illustrates the
    kind of simple slope+volatility heuristic a real Phase 2 implementation
    might start from: EMA slope for direction, ATR-relative-to-price for
    whether that direction is convincing or just noise."""
    ema_now, ema_prev = close.ewm(span=20).mean().iloc[-1], close.ewm(span=20).mean().iloc[-10]
    slope_pct = (ema_now - ema_prev) / ema_prev * 100
    volatility_pct = (atr.iloc[-1] / close.iloc[-1]) * 100

    if volatility_pct > 1.5:
        return "HIGH_VOLATILITY"
    if slope_pct > 0.5:
        return "TRENDING_UP"
    if slope_pct < -0.5:
        return "TRENDING_DOWN"
    return "SIDEWAYS"


def _conceptual_pivot_levels(prev_high: float, prev_low: float, prev_close: float) -> dict:
    """CONCEPTUAL ONLY — not wired into the live engine. Standard classic
    floor-trader pivot formula (textbook technical analysis, not a claim
    about efficacy): P = (H+L+C)/3, R1/S1/R2/S2 derived from P."""
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    return {"pivot": round(pivot, 2), "r1": round(r1, 2), "r2": round(r2, 2), "s1": round(s1, 2), "s2": round(s2, 2)}


def test_phase2_conceptual_regime_and_pivots():
    """CONCEPTUAL SIMULATION — see module docstring. Validates the DEMO
    functions above are internally consistent, not that Phase 2 is built."""
    n = 60
    trending_close = pd.Series(np.linspace(100, 115, n))
    trending_atr = pd.Series(np.full(n, 0.8))
    regime = _conceptual_classify_regime(trending_close, trending_atr)
    assert regime == "TRENDING_UP"

    flat_close = pd.Series(100 + np.random.normal(0, 0.05, n))
    flat_atr = pd.Series(np.full(n, 0.3))
    regime_flat = _conceptual_classify_regime(flat_close, flat_atr)
    assert regime_flat == "SIDEWAYS"

    pivots = _conceptual_pivot_levels(prev_high=105, prev_low=100, prev_close=103)
    assert pivots["s1"] < pivots["pivot"] < pivots["r1"] < pivots["r2"]
    assert pivots["s2"] < pivots["s1"]

    print(f"\n[PHASE 2 - CONCEPTUAL, NOT SHIPPED] Trending regime demo: {regime}")
    print(f"[PHASE 2 - CONCEPTUAL, NOT SHIPPED] Sideways regime demo: {regime_flat}")
    print(f"[PHASE 2 - CONCEPTUAL, NOT SHIPPED] Pivot levels demo: {pivots}")


# ============================================================================
# PHASE 3 — CONCEPTUAL SIMULATION ONLY.
# Multi-timeframe confirmation and the weighted confidence matrix do NOT
# exist in the live engine yet (the current strength_score in
# signal_engine.py uses different, simpler heuristics — see that file).
# ============================================================================

def _conceptual_mtf_confirmation(trend_15m_bullish: bool, setup_5m_confirmed: bool) -> bool:
    """CONCEPTUAL ONLY. Illustrates the intended AND-gate interface for
    stacking a higher-timeframe trend filter with a lower-timeframe entry
    trigger — not a claim this is calibrated or backtested."""
    return trend_15m_bullish and setup_5m_confirmed


def _conceptual_confidence_matrix(trend: float, volume: float, momentum: float,
                                   vwap: float, market: float) -> dict:
    """CONCEPTUAL ONLY. Implements the exact weight breakdown from the
    FINAL ARCHITECTURAL BLUEPRINT (Trend/30, Volume/20, Momentum/20,
    VWAP/15, Market/15 = 100) as a standalone demo — not wired into
    signal_engine.py's actual strength_score calculation."""
    weights = {"trend": 30, "volume": 20, "momentum": 20, "vwap": 15, "market": 15}
    scores = {"trend": trend, "volume": volume, "momentum": momentum, "vwap": vwap, "market": market}
    for key, weight in weights.items():
        assert 0 <= scores[key] <= weight, f"{key} score {scores[key]} exceeds its {weight}-point cap"
    total = sum(scores.values())
    return {"confidence_pct": round(total, 1), "breakdown": scores, "max_possible": sum(weights.values())}


def test_phase3_conceptual_mtf_and_confidence_matrix():
    """CONCEPTUAL SIMULATION — see module docstring."""
    assert _conceptual_mtf_confirmation(True, True) is True
    assert _conceptual_mtf_confirmation(True, False) is False
    assert _conceptual_mtf_confirmation(False, True) is False

    result = _conceptual_confidence_matrix(trend=28, volume=18, momentum=19, vwap=15, market=9)
    assert result["confidence_pct"] == 89
    assert result["max_possible"] == 100

    print(f"\n[PHASE 3 - CONCEPTUAL, NOT SHIPPED] MTF confirmation demo: 15m+5m aligned -> True")
    print(f"[PHASE 3 - CONCEPTUAL, NOT SHIPPED] Confidence matrix demo: {result}")


# ============================================================================
# PHASE 4 — HYBRID. The shadow_ledger TABLE is real (see
# app/models/shadow_ledger.py + migration 0004) — this test performs a
# genuine database write/read against it. The AUTOMATIC POPULATION
# mechanism (a background writer watching every live signal) does NOT
# exist yet — this test writes one row manually to prove the schema
# works, not that live auto-logging is implemented. The False Signal
# Analyzer categorization is CONCEPTUAL ONLY, same caveat as Phases 2-3.
# ============================================================================

_FAILURE_REASONS = [
    "WEAK_TREND", "LOW_VOLUME", "VWAP_FAILURE", "RSI_WEAKNESS",
    "SIDEWAYS_MARKET", "GAP_AGAINST_POSITION", "VOLATILITY_EXPANSION", "OTHER_RULE_FAILURE",
]


def _conceptual_classify_failure_reason(rules_passed: list[str], pnl_pct: float) -> str:
    """CONCEPTUAL ONLY — not wired into any real losing-trade pipeline yet.
    Illustrates the intended interface: given which rules passed and the
    outcome, pick a failure category from the blueprint's list. Real
    Phase 4 work would derive this from genuine loss analysis, not this
    placeholder mapping."""
    if pnl_pct >= 0:
        return "NOT_A_LOSS"
    if "volume_spike" not in rules_passed:
        return "LOW_VOLUME"
    if "vwap_cross_and_hold" not in rules_passed:
        return "VWAP_FAILURE"
    if "rsi_momentum_reversal" not in rules_passed:
        return "RSI_WEAKNESS"
    return "OTHER_RULE_FAILURE"


@pytest.mark.asyncio
async def test_phase4_shadow_ledger_schema_and_conceptual_failure_analysis(db_session):
    """
    HYBRID TEST. The database write below is REAL — it proves the
    shadow_ledger schema (migration 0004) actually works. The failure-
    reason classification is CONCEPTUAL — see function docstring above.
    """
    from app.models.shadow_ledger import ShadowLedgerEntry

    entry = ShadowLedgerEntry(
        symbol="RELIANCE.NS", asset_type="STOCK", tier="DEVELOPING",
        confidence_score=62, rules_passed=["nifty_trend_gatekeeper", "atr_breakout", "volume_spike"],
        market_regime="BULLISH",
        entry_time=datetime.now(), entry_price=1500.0, stop_loss=1480.0, target_1=1530.0,
        exit_time=datetime.now() + timedelta(minutes=45), exit_price=1475.0,
        exit_reason="SL_HIT", pnl=-25.0, pnl_pct=-1.67, holding_time_minutes=45,
        status="CLOSED",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)

    assert entry.id is not None
    print(f"\n[PHASE 4 - REAL] shadow_ledger row written and read back, id={entry.id}")

    reason = _conceptual_classify_failure_reason(entry.rules_passed, entry.pnl_pct)
    assert reason in _FAILURE_REASONS
    print(f"[PHASE 4 - CONCEPTUAL, NOT SHIPPED] Failure reason demo for this loss: {reason}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
