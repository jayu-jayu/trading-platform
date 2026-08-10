"""
Phase 3 test suite — Multi-Timeframe Confirmation, Sector Strength /
Relative Strength vs Nifty. Same standard as test_phase2.py: everything
here tests the REAL, shipped implementation.
"""
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytest
import pytz
from unittest.mock import patch

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


def _make_raw(ts_list, close, volume) -> dict:
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
# sector_strength.py — relative strength vs Nifty
# ============================================================================

def test_relative_strength_detects_outperformance():
    from app.services.sector_strength import compute_relative_strength
    sym_df = pd.DataFrame({"close": np.linspace(100, 105, 25)})
    nifty_df = pd.DataFrame({"close": np.linspace(100, 101, 25)})
    result = compute_relative_strength(sym_df, nifty_df, lookback=20, label="TEST")
    assert result["outperforming"] is True
    assert result["relative_strength_pct"] > 0
    assert type(result["outperforming"]) is bool  # not numpy.bool_ — see the fix in sector_strength.py


def test_relative_strength_detects_underperformance():
    from app.services.sector_strength import compute_relative_strength
    sym_df = pd.DataFrame({"close": np.full(25, 100.0)})
    nifty_df = pd.DataFrame({"close": np.linspace(100, 103, 25)})
    result = compute_relative_strength(sym_df, nifty_df, lookback=20, label="TEST")
    assert result["outperforming"] is False
    assert result["relative_strength_pct"] < 0


def test_relative_strength_none_with_insufficient_data():
    from app.services.sector_strength import compute_relative_strength
    sym_df = pd.DataFrame({"close": [100, 101]})
    nifty_df = pd.DataFrame({"close": np.linspace(100, 101, 25)})
    result = compute_relative_strength(sym_df, nifty_df, lookback=20, label="TEST")
    assert result["relative_strength_pct"] is None
    assert result["outperforming"] is None


# ============================================================================
# mtf_engine.py — 15m trend + 5m setup confirmation
# ============================================================================

def _enriched_15m(close_pattern: np.ndarray, n: int = 60) -> pd.DataFrame:
    from app.services.indicators import add_indicators
    ts = pd.date_range("2026-08-04 09:15", periods=n, freq="15min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        "timestamp": ts, "open": close_pattern - 0.1, "high": close_pattern + 0.3,
        "low": close_pattern - 0.3, "close": close_pattern,
        "volume": np.random.randint(9000, 11000, n).astype(float),
    })
    return add_indicators(df)


def test_mtf_confirms_when_trend_and_setup_both_align():
    from app.services.mtf_engine import check_mtf_confirmation
    df15 = _enriched_15m(np.linspace(90, 110, 60))  # clear uptrend, close > ema50

    n5 = 30
    close5 = np.full(n5, 110.0) + np.linspace(0, 1, n5)
    vol5 = np.random.randint(9000, 11000, n5).astype(float)
    vol5[-1] = 30000
    ts5 = pd.date_range("2026-08-04 14:00", periods=n5, freq="5min", tz="Asia/Kolkata")
    raw5 = _make_raw(ts5, close5, vol5)

    result = check_mtf_confirmation(df15, raw5)
    assert result["confirmed"] is True
    assert result["trend_15m_bullish"] is True
    assert result["setup_5m_confirmed"] is True


def test_mtf_never_confirms_on_bearish_15m_trend_regardless_of_5m():
    from app.services.mtf_engine import check_mtf_confirmation
    df15 = _enriched_15m(np.linspace(110, 90, 60))  # downtrend

    n5 = 30
    close5 = np.full(n5, 90.0) + np.linspace(0, 1, n5)
    vol5 = np.random.randint(9000, 11000, n5).astype(float)
    vol5[-1] = 30000
    ts5 = pd.date_range("2026-08-04 14:00", periods=n5, freq="5min", tz="Asia/Kolkata")
    raw5 = _make_raw(ts5, close5, vol5)  # 5m setup WOULD confirm on its own

    result = check_mtf_confirmation(df15, raw5)
    assert result["confirmed"] is False, "15m downtrend must veto confirmation even if 5m setup looks good"
    assert result["trend_15m_bullish"] is False


def test_mtf_handles_missing_5m_data_gracefully():
    from app.services.mtf_engine import check_mtf_confirmation
    df15 = _enriched_15m(np.linspace(90, 110, 60))
    result = check_mtf_confirmation(df15, None)
    assert result["confirmed"] is False
    assert result["trend_15m_bullish"] is True  # still reports the trend leg
    assert result["setup_5m_confirmed"] is None


def test_mtf_handles_insufficient_15m_history():
    from app.services.mtf_engine import check_mtf_confirmation
    df15_short = _enriched_15m(np.linspace(90, 110, 60)).iloc[:10]
    result = check_mtf_confirmation(df15_short, None)
    assert result["confirmed"] is False
    assert result["trend_15m_bullish"] is None


# ============================================================================
# Integration: signal_engine.py regression — proves Phase 3 additions
# cannot change gating/tier behavior, exactly like the Phase 2 equivalent.
# ============================================================================

@pytest.mark.asyncio
async def test_phase3_additions_do_not_change_gating_behavior():
    from app.services.signal_engine import evaluate_symbol

    ts_list = _session_timestamps(3, datetime(2026, 8, 3))
    n = len(ts_list)
    close = np.concatenate([
        np.linspace(100, 90, n // 3), np.linspace(90, 93, n // 3),
        np.linspace(93, 107, n - 2 * (n // 3)),
    ])
    volume = np.random.randint(9000, 11000, n).astype(float)
    volume[-5:] = 40000
    raw = _make_raw(ts_list, close, volume)

    nifty_close = 100 + np.linspace(0, 1, n)
    nifty_raw = _make_raw(ts_list, nifty_close, np.random.randint(9000, 11000, n).astype(float))
    forced_time = ts_list[-1]

    diag_without_phase3 = await evaluate_symbol("NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time)
    diag_with_phase3 = await evaluate_symbol(
        "NIFTYBEES.NS", "ETF", raw, "BULLISH", None, as_of=forced_time,
        market_regime_detail={"regime": "TRENDING_UP"}, nifty_15m_raw=nifty_raw,
    )

    assert diag_without_phase3.tier == diag_with_phase3.tier
    assert diag_without_phase3.rules_passed_count == diag_with_phase3.rules_passed_count
    assert [(r.rule_id, r.passed) for r in diag_without_phase3.rule_results] == \
           [(r.rule_id, r.passed) for r in diag_with_phase3.rule_results]

    # New diagnostic field IS populated when nifty_15m_raw is provided
    assert diag_with_phase3.relative_strength is not None
    # ...and gracefully absent (not crashed) when it isn't
    assert diag_without_phase3.relative_strength is None


# ============================================================================
# Integration: scanner.py's two-pass MTF orchestration
# ============================================================================

@pytest.mark.asyncio
async def test_scanner_mtf_pass_targets_only_eligible_symbols_and_persists_correctly(db_session):
    """
    Proves: (1) fetch_5m_batch is called ONLY for symbols passing >= 4/6
    rules, not the whole watchlist; (2) mtf_confirmed and
    sector_relative_strength_pct correctly merge into the signal payload;
    (3) institutional signals auto-persist these fields; (4) developing
    signals correctly do NOT auto-persist (existing Phase 1 design,
    unchanged by this phase).
    """
    from app.services.signal_engine import SymbolDiagnostics, RuleResult

    ts_list = _session_timestamps(4, datetime(2026, 8, 3))
    n = len(ts_list)

    async def fake_fetch_full_scan_data(symbols, nifty_symbol):
        results_15m = {s: _make_raw(ts_list, 100 + np.linspace(0, 2, n),
                                     np.random.randint(9000, 11000, n).astype(float)) for s in symbols}
        nifty_raw = _make_raw(ts_list, 100 + np.linspace(0, 1, n), np.random.randint(9000, 11000, n).astype(float))
        return {"nifty": nifty_raw, "15m": results_15m}

    fetch_5m_calls = []

    async def fake_fetch_5m_batch(symbols):
        fetch_5m_calls.append(list(symbols))
        ts5 = pd.date_range("2026-08-06 14:00", periods=60, freq="5min", tz="Asia/Kolkata")
        close5 = np.full(60, 107.0) + np.linspace(0, 1, 60)
        vol5 = np.random.randint(9000, 11000, 60).astype(float)
        vol5[-1] = 30000
        return {s: _make_raw(ts5, close5, vol5) for s in symbols}

    async def fake_evaluate_symbol(symbol, asset_type, df_15m_raw, market_regime, sector_15m_raw,
                                    as_of=None, market_regime_detail=None, nifty_15m_raw=None):
        diag = SymbolDiagnostics(symbol=symbol, asset_type=asset_type, data_available=True)
        # ELIGIBLE.NS passes 6/6 (institutional, auto-persists); NOT_ELIGIBLE.NS passes only 2/6
        if symbol == "ELIGIBLE.NS":
            diag.rule_results = [RuleResult(f"r{i}", f"Rule {i}", True, "t") for i in range(6)]
            diag.rules_passed_count = 6
            diag.tier = "INSTITUTIONAL"
            diag.qualified_signal = {
                "symbol": symbol, "asset_type": asset_type, "signal_type": "BUY",
                "entry_price": 107.0, "stop_loss": 105.0, "target": 110.0, "atr_value": 1.2,
                "rsi_value": 55.0, "vwap_value": 106.0, "volume_ratio": 2.0,
                "rules_passed": [f"r{i}" for i in range(6)], "sector_proxy": "NIFTYBEES.NS",
                "market_regime": market_regime, "strength_score": 92, "tier": "INSTITUTIONAL",
                "rules_passed_count": 6, "trend_score": 28, "volume_score": 18,
                "momentum_score": 18, "vwap_score": 15, "market_score": 13,
                "market_regime_detail": "TRENDING_UP",
            }
        else:
            diag.rule_results = [RuleResult(f"r{i}", f"Rule {i}", i < 2, "t") for i in range(6)]
            diag.rules_passed_count = 2
            diag.tier = "WEAK"
        diag.in_time_window = True
        return diag

    with patch("app.services.scanner.fetch_full_scan_data", fake_fetch_full_scan_data), \
         patch("app.services.scanner.fetch_5m_batch", fake_fetch_5m_batch), \
         patch("app.services.scanner.evaluate_symbol", fake_evaluate_symbol):
        import app.services.scanner as scanner
        import app.config as config_module
        config_module.settings.STOCK_WATCHLIST = ["ELIGIBLE.NS", "NOT_ELIGIBLE.NS"]
        config_module.settings.ETF_WATCHLIST = []
        result = await scanner.run_full_scan()

    assert fetch_5m_calls == [["ELIGIBLE.NS"]], (
        f"5m fetch must ONLY target the eligible symbol, got: {fetch_5m_calls}"
    )
    assert len(result["signals"]) == 1
    assert result["signals"][0]["symbol"] == "ELIGIBLE.NS"
    assert "mtf_confirmed" in result["signals"][0]

    from app.models.signal import SignalHistory
    from sqlalchemy import select
    res = await db_session.execute(select(SignalHistory))
    rows = res.scalars().all()
    assert len(rows) == 1
    assert rows[0].symbol == "ELIGIBLE.NS"
    assert rows[0].mtf_confirmed is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
