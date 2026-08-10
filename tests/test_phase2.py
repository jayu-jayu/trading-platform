"""
Phase 2 test suite — Market Regime Detection, Pivot Levels, Confidence
Score Engine. Unlike tests/test_roadmap_simulation.py's Phase 2 section
(which was explicitly conceptual scaffolding), everything here tests the
REAL, shipped implementation in app/services/market_analysis.py,
app/services/confidence_engine.py, and their integration into
app/services/signal_engine.py.
"""
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytest
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

IST = pytz.timezone("Asia/Kolkata")


def _session_timestamps(num_days: int, start_date: datetime) -> list[datetime]:
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
# market_analysis.py — regime classification
# ============================================================================

def test_regime_classifies_trending_up():
    from app.services.market_analysis import classify_market_regime, REGIME_TRENDING_UP
    n = 40
    df = pd.DataFrame({"close": np.linspace(100, 115, n)})
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["atr14"] = 0.8
    result = classify_market_regime(df)
    assert result["regime"] == REGIME_TRENDING_UP
    assert result["trend_slope_pct"] > 0


def test_regime_classifies_sideways():
    from app.services.market_analysis import classify_market_regime, REGIME_SIDEWAYS
    n = 40
    np.random.seed(1)
    df = pd.DataFrame({"close": 100 + np.random.normal(0, 0.05, n)})
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["atr14"] = 0.3
    result = classify_market_regime(df)
    assert result["regime"] == REGIME_SIDEWAYS


def test_regime_classifies_high_volatility_over_trend():
    """High volatility must take priority over trend direction — a fast
    but choppy market should not be reported as a clean trend."""
    from app.services.market_analysis import classify_market_regime, REGIME_HIGH_VOLATILITY
    n = 40
    df = pd.DataFrame({"close": np.linspace(100, 115, n)})  # strong uptrend...
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["atr14"] = 5.0  # ...but very high ATR relative to price
    result = classify_market_regime(df)
    assert result["regime"] == REGIME_HIGH_VOLATILITY


def test_regime_returns_unknown_with_insufficient_data():
    from app.services.market_analysis import classify_market_regime, REGIME_UNKNOWN
    df = pd.DataFrame({"close": [100, 101, 102]})  # far too short
    result = classify_market_regime(df)
    assert result["regime"] == REGIME_UNKNOWN


# ============================================================================
# market_analysis.py — pivot levels
# ============================================================================

def test_pivot_levels_internally_consistent():
    from app.services.market_analysis import compute_pivot_levels

    ts_list = _session_timestamps(2, datetime(2026, 8, 3))
    n = len(ts_list)
    day1_count = n // 2
    high = np.concatenate([np.full(day1_count, 105.0), np.full(n - day1_count, 104.5)])
    low = np.concatenate([np.full(day1_count, 100.0), np.full(n - day1_count, 103.5)])
    close = np.concatenate([np.full(day1_count, 103.0), np.full(n - day1_count, 104.0)])

    df = pd.DataFrame({
        "timestamp": ts_list, "session_date": [t.date() for t in ts_list],
        "high": high, "low": low, "close": close,
    })

    pivots = compute_pivot_levels(df, as_of=ts_list[-1])
    assert pivots is not None
    assert pivots["s2"] < pivots["s1"] < pivots["pivot"] < pivots["r1"] < pivots["r2"]
    # Classic formula check against the UNROUNDED math (prev_high=105, prev_low=100,
    # prev_close=103) — comparing against the already-rounded pivot value would
    # introduce its own rounding-order mismatch, which is not what this checks.
    true_pivot = (105.0 + 100.0 + 103.0) / 3
    assert pivots["r1"] == round(2 * true_pivot - 100.0, 2)
    assert pivots["s1"] == round(2 * true_pivot - 105.0, 2)


def test_pivot_levels_none_with_no_prior_session():
    from app.services.market_analysis import compute_pivot_levels
    ts_list = _session_timestamps(1, datetime(2026, 8, 3))  # only ONE day — no prior session exists
    df = pd.DataFrame({
        "timestamp": ts_list, "session_date": [t.date() for t in ts_list],
        "high": [105.0] * len(ts_list), "low": [100.0] * len(ts_list), "close": [103.0] * len(ts_list),
    })
    assert compute_pivot_levels(df, as_of=ts_list[-1]) is None


def test_pivot_description_matches_position():
    from app.services.market_analysis import describe_price_vs_pivots
    pivots = {"s2": 95, "s1": 98, "pivot": 100, "r1": 102, "r2": 105}
    assert "R2" in describe_price_vs_pivots(110, pivots) or "above" in describe_price_vs_pivots(110, pivots).lower()
    assert "S2" in describe_price_vs_pivots(90, pivots) or "below" in describe_price_vs_pivots(90, pivots).lower()
    mid_desc = describe_price_vs_pivots(101, pivots)
    assert "Pivot" in mid_desc and "R1" in mid_desc


# ============================================================================
# confidence_engine.py — weighted 0-100 matrix
# ============================================================================

def test_confidence_weights_sum_to_100():
    from app.services.confidence_engine import WEIGHTS
    assert sum(WEIGHTS.values()) == 100


def test_confidence_strong_setup_scores_higher_than_weak():
    from app.services.confidence_engine import compute_confidence
    strong = compute_confidence(
        breakout_margin_atr=1.5, volume_ratio=3.0, rsi_value=65,
        vwap_passed=True, close=105, vwap_value=103,
        market_regime_detail={"regime": "TRENDING_UP"},
    )
    weak = compute_confidence(
        breakout_margin_atr=0.1, volume_ratio=1.5, rsi_value=50,
        vwap_passed=False, close=100, vwap_value=None,
        market_regime_detail={"regime": "HIGH_VOLATILITY"},
    )
    assert strong["confidence_pct"] > weak["confidence_pct"]
    assert 0 <= strong["confidence_pct"] <= 100
    assert 0 <= weak["confidence_pct"] <= 100


def test_confidence_breakdown_never_exceeds_its_own_weight_cap():
    from app.services.confidence_engine import compute_confidence, WEIGHTS
    # Deliberately extreme inputs to try to force an overflow
    result = compute_confidence(
        breakout_margin_atr=100, volume_ratio=1000, rsi_value=100,
        vwap_passed=True, close=1000, vwap_value=1,
        market_regime_detail={"regime": "TRENDING_UP"},
    )
    for key, score in result["breakdown"].items():
        assert score <= WEIGHTS[key], f"{key} score {score} exceeded its cap of {WEIGHTS[key]}"
    assert result["confidence_pct"] <= 100


def test_confidence_handles_missing_market_regime_gracefully():
    """Backward-compat check: passing None (old caller behavior, before
    Phase 2 existed) must not crash — should fall back to a neutral score."""
    from app.services.confidence_engine import compute_confidence
    result = compute_confidence(
        breakout_margin_atr=0.5, volume_ratio=2.0, rsi_value=55,
        vwap_passed=True, close=100, vwap_value=99,
        market_regime_detail=None,
    )
    assert result["confidence_pct"] is not None
    assert 0 <= result["confidence_pct"] <= 100


# ============================================================================
# Integration: signal_engine.py regression — the most important test in
# this file. Proves Phase 2 additions cannot change gating/tier behavior.
# ============================================================================

@pytest.mark.asyncio
async def test_phase2_additions_do_not_change_gating_behavior():
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

    forced_time = ts_list[-1]  # deterministic — inside the signal window by construction

    diag_without_phase2 = await evaluate_symbol("NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time)
    diag_with_phase2 = await evaluate_symbol(
        "NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time,
        market_regime_detail={"regime": "TRENDING_UP", "detail": "test", "trend_slope_pct": 1.0, "volatility_pct": 0.5},
    )

    assert diag_without_phase2.tier == diag_with_phase2.tier
    assert diag_without_phase2.rules_passed_count == diag_with_phase2.rules_passed_count
    assert [(r.rule_id, r.passed) for r in diag_without_phase2.rule_results] == \
           [(r.rule_id, r.passed) for r in diag_with_phase2.rule_results]

    # New diagnostic fields ARE populated
    assert diag_with_phase2.confidence_breakdown is not None
    assert diag_with_phase2.pivot_description != ""
    assert diag_with_phase2.market_regime_detail is not None


@pytest.mark.asyncio
async def test_phase2_confidence_breakdown_present_in_qualifying_signal_payload():
    """When a signal qualifies (institutional or developing), its payload
    must carry the new breakdown fields, since that's what scanner.py
    persists to signal_history."""
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

    diag = await evaluate_symbol(
        "NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=ts_list[-1],
        market_regime_detail={"regime": "TRENDING_UP"},
    )
    signal = diag.qualified_signal or diag.developing_signal
    assert signal is not None, "Test fixture must produce at least a developing-tier signal"
    for key in ("trend_score", "volume_score", "momentum_score", "vwap_score", "market_score"):
        assert key in signal, f"{key} missing from signal payload"
    # strength_score must still be present with its original name/range —
    # backward compatibility with the dashboard and DB column.
    assert 0 <= signal["strength_score"] <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
