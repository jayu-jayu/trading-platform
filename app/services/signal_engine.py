"""
The refined 6-Rule Institutional Signal Engine (v2):

  Rule 1 — Institutional VWAP Cross & Hold: price crossed above VWAP within
           the last 6 candles AND has held above it for the last 2 candles
           (filters out single-tick VWAP pokes that immediately fail back).
  Rule 2 — Multi-period ATR Breakout: current close breaks above the prior
           20-period high by at least 0.25x ATR — a volatility-adjusted
           breakout confirmation, not just any new high.
  Rule 3 — Volume Spike: current candle volume >= 1.5x the 10-period
           average volume (relative volume filter).
  Rule 4 — Nifty Trend Gatekeeper: Nifty 50 above its own 15m 20-EMA =
           BULLISH regime gate; no signals generated otherwise.
  Rule 5 — RSI Momentum Reversal: RSI14 dipped below 45 within the last 5
           candles, then has now crossed back up through 50 — a genuine
           reversal-into-momentum, not just "RSI is high".
  Rule 6 — Sector/ETF Correlation Scan: the symbol's mapped sector ETF
           (see sector_map.py) is also above its own 15m 20-EMA, confirming
           the move isn't an isolated single-stock spike.

A signal only qualifies if all 6 rules pass. Risk management (ATR-based
SL/target) is computed alongside qualification, not as a gating rule.
"""
from datetime import datetime, time
import pandas as pd
import pytz

from app.services.indicators import chart_result_to_df, add_indicators, compute_atr_targets
from app.services.sector_map import get_sector_proxy

IST = pytz.timezone("Asia/Kolkata")

SIGNAL_START = time(9, 45)
SIGNAL_END = time(14, 30)

ATR_BREAKOUT_MULTIPLE = 0.25
VOLUME_SPIKE_MULTIPLE = 1.5
RSI_DIP_THRESHOLD = 45.0
RSI_REVERSAL_THRESHOLD = 50.0
ATR_SL_MULTIPLE = 1.0
ATR_TARGET_MULTIPLE = 1.5
VWAP_HOLD_CANDLES = 2
VWAP_CROSS_LOOKBACK = 6


def check_time_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    return SIGNAL_START <= now.time() <= SIGNAL_END


def is_market_open(now: datetime | None = None) -> bool:
    """NSE cash market hours: 09:15–15:30 IST, Mon–Fri."""
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return time(9, 15) <= now.time() <= time(15, 30)


def get_market_regime(nifty_raw: dict) -> str:
    """Rule 4 — Nifty above its own 15m 20-EMA = BULLISH regime."""
    df = chart_result_to_df(nifty_raw.get("raw") if nifty_raw else None)
    if df is None or len(df) < 25:
        return "UNKNOWN"
    df = add_indicators(df)
    last = df.iloc[-1]
    if pd.isna(last["ema20"]):
        return "UNKNOWN"
    return "BULLISH" if last["close"] > last["ema20"] else "BEARISH"


def _check_vwap_cross_and_hold(df: pd.DataFrame) -> bool:
    """Rule 1 — crossed above VWAP within the lookback window and has
    held above it for the last VWAP_HOLD_CANDLES candles."""
    if len(df) < VWAP_CROSS_LOOKBACK + 1:
        return False

    window = df.tail(VWAP_CROSS_LOOKBACK + 1).reset_index(drop=True)
    if window["vwap"].isna().any():
        return False

    crossed = False
    for i in range(1, len(window)):
        prev, curr = window.iloc[i - 1], window.iloc[i]
        if prev["close"] <= prev["vwap"] and curr["close"] > curr["vwap"]:
            crossed = True

    held = (df.tail(VWAP_HOLD_CANDLES)["close"] > df.tail(VWAP_HOLD_CANDLES)["vwap"]).all()
    return crossed and held


def _check_atr_breakout(df: pd.DataFrame) -> bool:
    """Rule 2 — close breaks above the prior 20-period high by >= 0.25x ATR."""
    last = df.iloc[-1]
    if pd.isna(last["rolling_high_20"]) or pd.isna(last["atr14"]):
        return False
    breakout_level = last["rolling_high_20"] + (ATR_BREAKOUT_MULTIPLE * last["atr14"])
    return last["close"] > breakout_level


def _check_volume_spike(df: pd.DataFrame) -> tuple[bool, float]:
    """Rule 3 — current volume >= 1.5x the 10-period average."""
    last = df.iloc[-1]
    if pd.isna(last["avg_vol_10"]) or last["avg_vol_10"] == 0:
        return False, 0.0
    ratio = last["volume"] / last["avg_vol_10"]
    return ratio >= VOLUME_SPIKE_MULTIPLE, round(ratio, 2)


def _check_rsi_momentum_reversal(df: pd.DataFrame) -> bool:
    """Rule 5 — RSI dipped below 45 recently, then crossed back up through 50."""
    if len(df) < 6:
        return False
    recent = df.tail(6)
    dipped = (recent["rsi14"].iloc[:-1] < RSI_DIP_THRESHOLD).any()

    prev_rsi, curr_rsi = df.iloc[-2]["rsi14"], df.iloc[-1]["rsi14"]
    if pd.isna(prev_rsi) or pd.isna(curr_rsi):
        return False
    crossed_up = prev_rsi < RSI_REVERSAL_THRESHOLD <= curr_rsi

    return bool(dipped and crossed_up)


def _strength_score(volume_ratio: float, rsi: float, breakout_margin_atr: float) -> int:
    """0-100 confidence score for the signal feed's ranking display."""
    base = 40
    volume_bonus = min(int((volume_ratio - VOLUME_SPIKE_MULTIPLE) * 15), 20)
    rsi_bonus = min(int(rsi - RSI_REVERSAL_THRESHOLD), 15) if rsi else 0
    breakout_bonus = min(int(breakout_margin_atr * 20), 25)
    return max(0, min(100, base + volume_bonus + rsi_bonus + breakout_bonus))


async def evaluate_symbol(symbol: str, asset_type: str, df_15m_raw: dict,
                           market_regime: str, sector_15m_raw: dict | None) -> dict | None:
    """Runs all 6 rules against one symbol's already-fetched 15m data.
    Returns a qualified signal dict, or None if any rule fails."""

    # Rule 4 — gatekeeper (defensive re-check; the scanner already gates the whole batch)
    if market_regime != "BULLISH":
        return None

    if not check_time_window():
        return None

    df = chart_result_to_df(df_15m_raw.get("raw") if df_15m_raw else None)
    if df is None or len(df) < 25:
        return None
    df = add_indicators(df)
    last = df.iloc[-1]

    rules_passed = ["nifty_trend_gatekeeper", "time_window"]

    # Rule 1
    if not _check_vwap_cross_and_hold(df):
        return None
    rules_passed.append("vwap_cross_and_hold")

    # Rule 2
    if not _check_atr_breakout(df):
        return None
    rules_passed.append("atr_breakout")

    # Rule 3
    volume_ok, volume_ratio = _check_volume_spike(df)
    if not volume_ok:
        return None
    rules_passed.append("volume_spike")

    # Rule 5
    if not _check_rsi_momentum_reversal(df):
        return None
    rules_passed.append("rsi_momentum_reversal")

    # Rule 6 — sector/ETF correlation
    sector_proxy = get_sector_proxy(symbol)
    if symbol == sector_proxy:
        sector_ok = True  # an ETF checked against itself trivially passes
    else:
        sector_df = chart_result_to_df(sector_15m_raw.get("raw") if sector_15m_raw else None)
        if sector_df is None or len(sector_df) < 25:
            return None
        sector_df = add_indicators(sector_df)
        sector_last = sector_df.iloc[-1]
        sector_ok = (not pd.isna(sector_last["ema20"])) and (sector_last["close"] > sector_last["ema20"])
    if not sector_ok:
        return None
    rules_passed.append("sector_etf_correlation")

    # Risk management — ATR-based SL/target
    entry_price = float(last["close"])
    atr_value = float(last["atr14"]) if not pd.isna(last["atr14"]) else None
    if atr_value is None or atr_value <= 0:
        return None
    stop_loss, target = compute_atr_targets(entry_price, atr_value, ATR_SL_MULTIPLE, ATR_TARGET_MULTIPLE)

    breakout_margin_atr = (entry_price - last["rolling_high_20"]) / atr_value if atr_value else 0
    strength = _strength_score(volume_ratio, float(last["rsi14"]), breakout_margin_atr)

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "signal_type": "BUY",
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target": target,
        "atr_value": round(atr_value, 2),
        "rsi_value": round(float(last["rsi14"]), 2),
        "vwap_value": round(float(last["vwap"]), 2) if not pd.isna(last["vwap"]) else None,
        "volume_ratio": volume_ratio,
        "rules_passed": rules_passed,
        "sector_proxy": sector_proxy,
        "market_regime": market_regime,
        "strength_score": strength,
    }
