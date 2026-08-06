"""
Indicator calculations shared by every rule in the engine: EMA, RSI, ATR,
VWAP, rolling volume average, and rolling high (for the ATR breakout rule).
"""
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


def chart_result_to_df(raw_result: dict | None) -> pd.DataFrame | None:
    if raw_result is None:
        return None
    try:
        timestamps = raw_result["timestamp"]
        quote = raw_result["indicators"]["quote"][0]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("Asia/Kolkata"),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
        })
        df = df.dropna(subset=["close"]).reset_index(drop=True)
        return df if len(df) > 0 else None
    except (KeyError, IndexError, TypeError):
        return None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ema20"] = EMAIndicator(close=df["close"], window=20).ema_indicator()
    df["ema50"] = EMAIndicator(close=df["close"], window=50).ema_indicator()
    df["rsi14"] = RSIIndicator(close=df["close"], window=14).rsi()
    df["atr14"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    # VWAP, reset each session
    df["session_date"] = df["timestamp"].dt.date
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["_tpv"] = typical_price * df["volume"]
    df["cum_tpv"] = df.groupby("session_date")["_tpv"].cumsum()
    df["cum_vol"] = df.groupby("session_date")["volume"].cumsum()
    df["vwap"] = df["cum_tpv"] / df["cum_vol"].replace(0, np.nan)
    df.drop(columns=["_tpv"], inplace=True)

    # 10-period rolling average volume, excluding current candle (Rule 3)
    df["avg_vol_10"] = df["volume"].shift(1).rolling(window=10).mean()

    # 20-period rolling high, excluding current candle (Rule 2 breakout reference)
    df["rolling_high_20"] = df["high"].shift(1).rolling(window=20).max()

    return df


def compute_atr_targets(entry_price: float, atr_value: float,
                         sl_multiple: float = 1.0, target_multiple: float = 1.5) -> tuple[float, float]:
    stop_loss = round(entry_price - (sl_multiple * atr_value), 2)
    target = round(entry_price + (target_multiple * atr_value), 2)
    return stop_loss, target
