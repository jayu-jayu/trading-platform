"""
Multi-Timeframe Confirmation — Phase 3. 15M Trend + 5M Setup, deliberately
scoped down from an earlier 3-timeframe idea (15m/5m/1m) — 1-minute data on
the unofficial Yahoo endpoint this app uses is thin and unreliable, and
adding a third timeframe wasn't worth the extra request cost without
evidence it improves outcomes. Same reasoning applies to this pair too:
this is DIAGNOSTIC-ONLY, not gating, until validated via the backtest
engine with real accumulated data.

Costs real requests (see scanner.py) — only run for symbols that already
pass 4+ of the 6 core 15m rules, not the whole watchlist every scan.
"""
import pandas as pd

from app.services.indicators import chart_result_to_df, add_indicators

MIN_CANDLES_5M = 20


def check_mtf_confirmation(df_15m: pd.DataFrame, df_5m_raw: dict | None) -> dict:
    """
    15M Trend: the symbol's OWN close above its OWN 15m EMA50 — genuinely
    new signal, since no existing rule currently checks a symbol's own
    trend context (Rule 6 checks the SECTOR's EMA20, not the symbol's own).

    5M Setup: on the freshly-fetched 5-minute data, close above 5m VWAP
    AND the latest 5m candle's volume above its own 10-period average —
    a finer-grained "is this the right micro-moment" check, same style as
    the existing VWAP-hold and volume-spike rules, just at 5m resolution.

    `df_15m` must already be indicator-enriched (same df evaluate_symbol
    already has in hand — no extra computation needed for the trend leg).
    """
    if df_15m is None or len(df_15m) < 50 or "ema50" not in df_15m.columns:
        return {
            "confirmed": False, "trend_15m_bullish": None, "setup_5m_confirmed": None,
            "detail": "Not enough 15m history yet to establish the trend leg.",
        }

    last_15m = df_15m.iloc[-1]
    if pd.isna(last_15m["ema50"]):
        return {
            "confirmed": False, "trend_15m_bullish": None, "setup_5m_confirmed": None,
            "detail": "15m EMA50 not yet available.",
        }
    trend_15m_bullish = bool(last_15m["close"] > last_15m["ema50"])

    df_5m = chart_result_to_df(df_5m_raw.get("raw") if df_5m_raw else None)
    if df_5m is None or len(df_5m) < MIN_CANDLES_5M:
        return {
            "confirmed": False, "trend_15m_bullish": trend_15m_bullish, "setup_5m_confirmed": None,
            "detail": f"15m trend is {'bullish' if trend_15m_bullish else 'bearish'}, "
                      f"but not enough 5m data yet to confirm entry timing.",
        }

    df_5m = add_indicators(df_5m)
    last_5m = df_5m.iloc[-1]

    vwap_ok = (not pd.isna(last_5m["vwap"])) and bool(last_5m["close"] > last_5m["vwap"])
    volume_ok = (not pd.isna(last_5m["avg_vol_10"])) and last_5m["avg_vol_10"] > 0 and \
                bool(last_5m["volume"] > last_5m["avg_vol_10"])
    setup_5m_confirmed = bool(vwap_ok and volume_ok)

    confirmed = bool(trend_15m_bullish and setup_5m_confirmed)

    detail = (
        f"15m trend {'bullish' if trend_15m_bullish else 'bearish'} (close vs EMA50); "
        f"5m setup {'confirmed' if setup_5m_confirmed else 'not confirmed'} "
        f"(above 5m VWAP: {vwap_ok}, above 5m avg volume: {volume_ok})."
    )

    return {
        "confirmed": confirmed, "trend_15m_bullish": trend_15m_bullish,
        "setup_5m_confirmed": setup_5m_confirmed, "detail": detail,
    }
