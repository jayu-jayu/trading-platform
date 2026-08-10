"""
Sector Strength & Relative Strength vs Nifty — Phase 3.

DIAGNOSTIC-ONLY, same status as Phase 2's market regime/pivot additions —
does not gate qualification or tier. Costs NO extra data fetches: Nifty
and sector-proxy ETF data are already fetched every scan (for the
existing gatekeeper and Rule 6 respectively), this just derives a second,
continuous metric from the same data instead of only a binary EMA check.

CALIBRATION NOTE: same honesty caveat as market_analysis.py — the lookback
window (20 candles) is a reasonable starting point, not backtested.
"""
import pandas as pd


def _pct_return(df: pd.DataFrame, lookback: int) -> float | None:
    """Simple close-to-close return over the last `lookback` candles."""
    if df is None or len(df) < lookback + 1:
        return None
    start_price = df["close"].iloc[-(lookback + 1)]
    end_price = df["close"].iloc[-1]
    if start_price == 0 or pd.isna(start_price) or pd.isna(end_price):
        return None
    return round(float((end_price - start_price) / start_price * 100), 3)


def compute_relative_strength(symbol_df: pd.DataFrame, benchmark_df: pd.DataFrame,
                               lookback: int = 20, label: str = "symbol") -> dict:
    """
    Compares `symbol_df`'s return over the lookback window against
    `benchmark_df`'s (normally Nifty). Positive relative_strength_pct means
    outperformance — the symbol moved more (or fell less) than the
    benchmark over the same window.

    Works identically whether `symbol_df` is the stock itself or its
    sector-proxy ETF — `label` just controls the detail message wording,
    letting one function serve both "stock vs Nifty" and "sector vs Nifty".
    """
    symbol_return = _pct_return(symbol_df, lookback)
    benchmark_return = _pct_return(benchmark_df, lookback)

    if symbol_return is None or benchmark_return is None:
        return {
            "relative_strength_pct": None, "symbol_return_pct": symbol_return,
            "benchmark_return_pct": benchmark_return, "outperforming": None,
            "detail": f"Not enough history yet to compute {label} relative strength ({lookback}-candle lookback).",
        }

    relative_strength = round(float(symbol_return - benchmark_return), 3)
    outperforming = bool(relative_strength > 0)

    verb = "outperformed" if outperforming else "underperformed"
    detail = (f"{label.capitalize()} {verb} Nifty by {abs(relative_strength):.2f}pp over the last "
              f"{lookback} candles ({symbol_return:+.2f}% vs {benchmark_return:+.2f}%).")

    return {
        "relative_strength_pct": relative_strength, "symbol_return_pct": symbol_return,
        "benchmark_return_pct": benchmark_return, "outperforming": outperforming, "detail": detail,
    }
