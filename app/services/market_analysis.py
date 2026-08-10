"""
Market Regime Detection + Pivot Level calculation — Phase 2.

Both are DIAGNOSTIC-ONLY in this phase, per the blueprint: they inform the
confidence score and are shown in diagnostics, but do NOT gate whether a
signal qualifies. The existing binary Nifty gatekeeper (BULLISH/BEARISH in
signal_engine.py) is completely unchanged by this module — this adds a
richer classification ALONGSIDE it, not instead of it.

CALIBRATION NOTE: the thresholds below (slope %, volatility %) are initial,
reasonable starting values, not backtested-and-proven constants. Treat them
the same way the rest of this codebase treats its rule thresholds — as
something to validate and tune once real signal history accumulates, not
as settled fact. This mirrors the honesty note already in config.py about
the watchlist.
"""
import pandas as pd
import pytz
from datetime import datetime

IST = pytz.timezone("Asia/Kolkata")

TREND_SLOPE_THRESHOLD_PCT = 0.5     # EMA20 slope over 10 candles, as % of price
HIGH_VOLATILITY_ATR_PCT = 1.5       # ATR as % of price

REGIME_TRENDING_UP = "TRENDING_UP"
REGIME_TRENDING_DOWN = "TRENDING_DOWN"
REGIME_SIDEWAYS = "SIDEWAYS"
REGIME_HIGH_VOLATILITY = "HIGH_VOLATILITY"
REGIME_UNKNOWN = "UNKNOWN"


def classify_market_regime(df: pd.DataFrame) -> dict:
    """
    Classifies the current market condition from an already-indicator-enriched
    DataFrame (expects ema20 and atr14 columns, same shape signal_engine.py's
    add_indicators() produces). Volatility check takes priority over trend
    direction — a fast-trending-but-choppy market is flagged HIGH_VOLATILITY
    first, since that's the more actionable risk signal for a long-only
    intraday system.

    Returns a dict (not just a string) so the reasoning is inspectable —
    consistent with how every other rule in this codebase reports a detail
    string alongside its verdict, not just a pass/fail.
    """
    if len(df) < 30 or "ema20" not in df.columns or "atr14" not in df.columns:
        return {"regime": REGIME_UNKNOWN, "detail": "Not enough history to classify regime yet.",
                "trend_slope_pct": None, "volatility_pct": None}

    last = df.iloc[-1]
    ema_now = df["ema20"].iloc[-1]
    ema_prev = df["ema20"].iloc[-11] if len(df) >= 11 else df["ema20"].iloc[0]

    if pd.isna(ema_now) or pd.isna(ema_prev) or pd.isna(last["atr14"]) or ema_prev == 0:
        return {"regime": REGIME_UNKNOWN, "detail": "Indicators not yet available for regime classification.",
                "trend_slope_pct": None, "volatility_pct": None}

    slope_pct = round((ema_now - ema_prev) / ema_prev * 100, 3)
    volatility_pct = round((last["atr14"] / last["close"]) * 100, 3) if last["close"] else None

    if volatility_pct is not None and volatility_pct > HIGH_VOLATILITY_ATR_PCT:
        regime = REGIME_HIGH_VOLATILITY
        detail = f"ATR is {volatility_pct}% of price (above the {HIGH_VOLATILITY_ATR_PCT}% high-volatility threshold) — conditions are choppy regardless of direction."
    elif slope_pct > TREND_SLOPE_THRESHOLD_PCT:
        regime = REGIME_TRENDING_UP
        detail = f"EMA20 rose {slope_pct}% over the last 10 candles — a clear uptrend."
    elif slope_pct < -TREND_SLOPE_THRESHOLD_PCT:
        regime = REGIME_TRENDING_DOWN
        detail = f"EMA20 fell {slope_pct}% over the last 10 candles — a clear downtrend."
    else:
        regime = REGIME_SIDEWAYS
        detail = f"EMA20 moved only {slope_pct}% over the last 10 candles — no clear direction, likely range-bound."

    return {"regime": regime, "detail": detail, "trend_slope_pct": slope_pct, "volatility_pct": volatility_pct}


def compute_pivot_levels(df: pd.DataFrame, as_of: datetime | None = None) -> dict | None:
    """
    Classic floor-trader pivot points (P, R1, R2, S1, S2) from the most
    recently COMPLETED trading session's High/Low/Close — derived from
    already-fetched 15m candle data by grouping on session_date, no
    separate daily-interval fetch required.

    `as_of`: same convention as evaluate_symbol's as_of — the "previous
    session" is relative to this timestamp (or the DataFrame's last
    timestamp if not given), so this works identically for live scanning
    and backtesting.

    Returns None if there isn't yet a fully completed prior session in the
    data (e.g. very first day the app has ever seen a symbol).
    """
    if df is None or len(df) == 0 or "session_date" not in df.columns:
        return None

    reference_date = (as_of or df["timestamp"].iloc[-1]).date()
    prior_sessions = sorted(d for d in df["session_date"].unique() if d < reference_date)
    if not prior_sessions:
        return None

    prev_session = prior_sessions[-1]
    session_df = df[df["session_date"] == prev_session]
    if session_df.empty:
        return None

    prev_high = float(session_df["high"].max())
    prev_low = float(session_df["low"].min())
    prev_close = float(session_df["close"].iloc[-1])

    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)

    return {
        "session_date": str(prev_session),
        "pivot": round(pivot, 2), "r1": round(r1, 2), "r2": round(r2, 2),
        "s1": round(s1, 2), "s2": round(s2, 2),
    }


def describe_price_vs_pivots(current_price: float, pivots: dict | None) -> str:
    """Human-readable position of price relative to the pivot ladder —
    the diagnostic detail string shown in the UI/API, same style as every
    other rule's detail message in signal_engine.py."""
    if pivots is None:
        return "No completed prior session available yet to compute pivot levels."

    levels = [("S2", pivots["s2"]), ("S1", pivots["s1"]), ("Pivot", pivots["pivot"]),
              ("R1", pivots["r1"]), ("R2", pivots["r2"])]

    if current_price > pivots["r2"]:
        return f"Price {current_price:.2f} is above R2 ({pivots['r2']:.2f}) — extended above the pivot ladder."
    if current_price < pivots["s2"]:
        return f"Price {current_price:.2f} is below S2 ({pivots['s2']:.2f}) — extended below the pivot ladder."

    for i in range(len(levels) - 1):
        lower_label, lower_val = levels[i]
        upper_label, upper_val = levels[i + 1]
        if lower_val <= current_price <= upper_val:
            return f"Price {current_price:.2f} is between {lower_label} ({lower_val:.2f}) and {upper_label} ({upper_val:.2f})."

    return f"Price {current_price:.2f} relative to pivot {pivots['pivot']:.2f} — position unclear."
