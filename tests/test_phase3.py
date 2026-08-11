"""
Phase 3 test suite — Multi-Timeframe Confirmation, Sector Strength /
Relative Strength vs Nifty. Tests the REAL implementation in
app/services/mtf_engine.py, app/services/sector_strength.py, and their
integration into signal_engine.py and scanner.py's two-pass flow.
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
# sector_strength.py
# ============================================================================

def test_relative_strength_detects_outperformance():
    from app.services.sector_strength import compute_relative_strength
    sym_df = pd.DataFrame({"close": np.linspace(100, 105, 25)})
    bench_df = pd.DataFrame({"close": np.linspace(100, 101, 25)})
    result = compute_relative_strength(sym_df, bench_df, lookback=20, label="test")
    assert result["outperforming"] is True
    assert result["relative_strength_pct"] > 0
    assert type(result["outperforming"]) is bool  # not numpy.bool_ — matters for JSON serialization


def test_relative_strength_detects_underperformance():
    from app.services.sector_strength import compute_relative_strength
    sym_df = pd.DataFrame({"close": np.full(25, 100.0)})
    bench_df = pd.DataFrame({"close": np.linspace(100, 103, 25)})
    result = compute_relative_strength(sym_df, bench_df, lookback=20, label="test")
    assert result["outperforming"] is False
    assert result["relative_strength_pct"] < 0


def test_relative_strength_none_with_insufficient_data():
    from app.services.sector_strength import compute_relative_strength
    result = compute_relative_strength(pd.DataFrame({"close": [100, 101]}),
                                        pd.DataFrame({"close": [100, 101]}), lookback=20, label="test")
    assert result["relative_strength_pct"] is None
    assert result["outperforming"] is None


# ============================================================================
# mtf_engine.py
# ============================================================================

def _make_15m_df(n, close_pattern):
    from app.services.indicators import add_indicators
    ts = pd.date_range("2026-08-04 09:15", periods=n, freq="15min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        "timestamp": ts, "open": close_pattern - 0.1, "high": close_pattern + 0.3,
        "low": close_pattern - 0.3, "close": close_pattern, "volume": np.random.randint(9000, 11000, n).astype(float),
    })
    return add_indicators(df)


def test_mtf_confirms_when_both_legs_align():
    from app.services.mtf_engine import check_mtf_confirmation
    n15 = 60
    df15 = _make_15m_df(n15, np.linspace(90, 110, n15))  # clear uptrend, close > ema50

    n5 = 30
    close5 = np.full(n5, 110.0) + np.linspace(0, 1, n5)
    vol5 = np.random.randint(9000, 11000, n5).astype(float)
    vol5[-1] = 30000
    ts5 = pd.date_range("2026-08-04 14:00", periods=n5, freq="5min", tz="Asia/Kolkata")
    raw5 = _build_raw(ts5, close5, vol5)

    result = check_mtf_confirmation(df15, raw5)
    assert result["confirmed"] is True
    assert result["trend_15m_bullish"] is True
    assert result["setup_5m_confirmed"] is True


def test_mtf_rejects_when_15m_trend_bearish():
    """A confirmed 5m setup must NOT override a bearish 15m trend."""
    from app.services.mtf_engine import check_mtf_confirmation
    n15 = 60
    df15 = _make_15m_df(n15, np.linspace(110, 90, n15))  # downtrend

    n5 = 30
    close5 = np.full(n5, 90.0) + np.linspace(0, 1, n5)
    vol5 = np.random.randint(9000, 11000, n5).astype(float)
    vol5[-1] = 30000
    ts5 = pd.date_range("2026-08-04 14:00", periods=n5, freq="5min", tz="Asia/Kolkata")
    raw5 = _build_raw(ts5, close5, vol5)

    result = check_mtf_confirmation(df15, raw5)
    assert result["confirmed"] is False
    assert result["trend_15m_bullish"] is False


def test_mtf_handles_missing_5m_data_gracefully():
    from app.services.mtf_engine import check_mtf_confirmation
    n15 = 60
    df15 = _make_15m_df(n15, np.linspace(90, 110, n15))
    result = check_mtf_confirmation(df15, None)
    assert result["confirmed"] is False
    assert result["trend_15m_bullish"] is True  # 15m leg still evaluated
    assert result["setup_5m_confirmed"] is None


def test_mtf_insufficient_15m_history():
    from app.services.mtf_engine import check_mtf_confirmation
    df15 = _make_15m_df(60, np.linspace(90, 110, 60)).iloc[:10]
    result = check_mtf_confirmation(df15, None)
    assert result["confirmed"] is False
    assert result["trend_15m_bullish"] is None


# ============================================================================
# Integration: signal_engine.py regression
# ============================================================================

@pytest.mark.asyncio
async def test_phase3_relative_strength_does_not_change_gating():
    from app.services.signal_engine import evaluate_symbol

    n = 45
    ts = pd.date_range("2026-08-04 10:00", periods=n, freq="15min", tz="Asia/Kolkata")
    close = np.concatenate([np.linspace(100, 90, 20), np.linspace(90, 93, 18), np.array([94, 96, 99, 100, 102, 104, 107])])
    volume = np.random.randint(9000, 11000, n).astype(float)
    volume[-1] = 40000
    raw = _build_raw(ts, close, volume)
    nifty_raw = _build_raw(ts, 100 + np.linspace(0, 1, n), np.random.randint(9000, 11000, n).astype(float))

    forced_time = ts[-1]
    diag_without = await evaluate_symbol("NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time)
    diag_with = await evaluate_symbol(
        "NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time,
        market_regime_detail={"regime": "TRENDING_UP"}, nifty_15m_raw=nifty_raw,
    )

    assert diag_without.tier == diag_with.tier
    assert diag_without.rules_passed_count == diag_with.rules_passed_count
    assert [(r.rule_id, r.passed) for r in diag_without.rule_results] == \
           [(r.rule_id, r.passed) for r in diag_with.rule_results]
    assert diag_with.relative_strength is not None


@pytest.mark.asyncio
async def test_phase3_persistence_of_mtf_and_sector_rs():
    """Direct test of the persistence path scanner.py uses — same shape
    verified manually during development, formalized here as a regression."""
    from app.services.scanner import _persist_signals
    from app.db.session import AsyncSessionLocal
    from app.models.signal import SignalHistory

    fake_signal = {
        "symbol": "RELIANCE.NS", "asset_type": "STOCK", "signal_type": "BUY",
        "entry_price": 1500.0, "stop_loss": 1480.0, "target": 1530.0, "atr_value": 12.5,
        "rsi_value": 65.0, "vwap_value": 1495.0, "volume_ratio": 2.5,
        "rules_passed": ["nifty_trend_gatekeeper"], "sector_proxy": "NIFTYBEES.NS",
        "market_regime": "BULLISH", "strength_score": 92, "tier": "INSTITUTIONAL", "rules_passed_count": 6,
        "trend_score": 28.0, "volume_score": 18.0, "momentum_score": 19.0, "vwap_score": 14.0, "market_score": 13.0,
        "market_regime_detail": "TRENDING_UP", "mtf_confirmed": True, "sector_relative_strength_pct": 1.85,
    }
    enriched = await _persist_signals([fake_signal])
    async with AsyncSessionLocal() as session:
        record = await session.get(SignalHistory, enriched[0]["id"])
        assert record.mtf_confirmed is True
        assert record.sector_relative_strength_pct == 1.85


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
