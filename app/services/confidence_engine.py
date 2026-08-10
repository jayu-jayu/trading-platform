"""
Confidence Score Engine — Phase 2. Weighted 0-100 matrix:
  Trend      /30  — how convincingly price broke out, in ATR terms
  Volume     /20  — how strong the relative volume spike is
  Momentum   /20  — how far RSI has pushed past the reversal threshold
  VWAP       /15  — whether the VWAP hold is fresh/clean or marginal
  Market     /15  — whether the broader market regime supports a long

This is diagnostic enrichment, not a gating rule — it never changes
whether a signal qualifies (that's still purely the 6 pass/fail rules in
signal_engine.py). It replaces the old flat strength_score heuristic with
a transparent, explainable breakdown, while keeping strength_score itself
as the same 0-100 total for backward compatibility with everything that
already reads that field (dashboard cards, sort order, DB column).

CALIBRATION NOTE: same honesty caveat as market_analysis.py — these
sub-score formulas are a reasonable, documented starting point, not
backtested-and-proven weights. Revisit once real outcome data exists.
"""
from app.services.market_analysis import (
    REGIME_TRENDING_UP, REGIME_TRENDING_DOWN, REGIME_SIDEWAYS,
    REGIME_HIGH_VOLATILITY, REGIME_UNKNOWN,
)

WEIGHTS = {"trend": 30, "volume": 20, "momentum": 20, "vwap": 15, "market": 15}

_MARKET_REGIME_POINTS = {
    REGIME_TRENDING_UP: 15,
    REGIME_SIDEWAYS: 7,
    REGIME_HIGH_VOLATILITY: 5,
    REGIME_TRENDING_DOWN: 0,
    REGIME_UNKNOWN: 7,  # neutral default when regime can't be determined yet
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _trend_score(breakout_margin_atr: float) -> float:
    """0-30. margin_atr=0 (barely broke out) -> 0; margin_atr>=1.5 -> full 30."""
    return round(_clamp(breakout_margin_atr / 1.5, 0, 1) * WEIGHTS["trend"], 1)


def _volume_score(volume_ratio: float, threshold: float = 1.5) -> float:
    """0-20. Below threshold scales 0->10 approaching the bar; above it,
    10->20 as the spike gets stronger, capping the 'stronger is better'
    credit at 3x so one freak print doesn't dominate the score."""
    if volume_ratio <= 0:
        return 0.0
    if volume_ratio < threshold:
        return round(_clamp(volume_ratio / threshold, 0, 1) * 10, 1)
    extra = _clamp((volume_ratio - threshold) / (3.0 - threshold), 0, 1)
    return round(10 + extra * 10, 1)


def _momentum_score(rsi_value: float, reversal_threshold: float = 50.0) -> float:
    """0-20. rsi=reversal_threshold -> 10 (just crossed); rsi>=70 -> full 20;
    below the threshold scales down toward 0 as RSI weakens further."""
    if rsi_value is None:
        return 0.0
    if rsi_value >= reversal_threshold:
        extra = _clamp((rsi_value - reversal_threshold) / (70 - reversal_threshold), 0, 1)
        return round(10 + extra * 10, 1)
    below = _clamp((reversal_threshold - rsi_value) / reversal_threshold, 0, 1)
    return round(10 * (1 - below), 1)


def _vwap_score(vwap_passed: bool, close: float, vwap_value: float | None) -> float:
    """0-15. Full credit for a confirmed hold; partial credit scaled by
    how far above VWAP price is (a stronger hold), zero if never crossed."""
    if not vwap_passed or vwap_value is None or vwap_value == 0:
        return 0.0
    distance_pct = _clamp((close - vwap_value) / vwap_value * 100, 0, 2) / 2  # cap credit at 2% above VWAP
    return round((0.6 + 0.4 * distance_pct) * WEIGHTS["vwap"], 1)


def _market_score(regime: str) -> float:
    """0-15, straight lookup — see _MARKET_REGIME_POINTS above."""
    return float(_MARKET_REGIME_POINTS.get(regime, _MARKET_REGIME_POINTS[REGIME_UNKNOWN]))


def compute_confidence(*, breakout_margin_atr: float, volume_ratio: float, rsi_value: float | None,
                        vwap_passed: bool, close: float, vwap_value: float | None,
                        market_regime_detail: dict | None) -> dict:
    """
    Computes the full weighted breakdown. All inputs are values
    signal_engine.py already computes per-symbol during rule evaluation —
    this function has no side effects and does no data fetching, purely a
    scoring transform, which is what makes it independently unit-testable.
    """
    regime = (market_regime_detail or {}).get("regime", REGIME_UNKNOWN)

    breakdown = {
        "trend": _trend_score(breakout_margin_atr),
        "volume": _volume_score(volume_ratio),
        "momentum": _momentum_score(rsi_value),
        "vwap": _vwap_score(vwap_passed, close, vwap_value),
        "market": _market_score(regime),
    }
    total = round(sum(breakdown.values()))

    return {
        "confidence_pct": max(0, min(100, total)),
        "breakdown": breakdown,
        "weights": WEIGHTS,
        "market_regime_used": regime,
    }
