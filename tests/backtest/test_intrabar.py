import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest

from app.services import backtest_engine


def make_row(high, low, close, ts):
    return SimpleNamespace(open=close, high=high, low=low, close=close, candle_timestamp=ts)


def run_sim(symbol, interval, entry_time, entry_price, stop_loss, target, candles):
    async def fake_get_cached_candles(sym, inter, start=None, end=None):
        return candles

    # Patch the price cache reader in the module under test
    original = backtest_engine.get_cached_candles
    backtest_engine.get_cached_candles = fake_get_cached_candles
    try:
        return asyncio.run(backtest_engine._simulate_exit(symbol, interval, entry_time, entry_price, stop_loss, target))
    finally:
        backtest_engine.get_cached_candles = original


def test_ambiguous_prefers_sl():
    entry_time = datetime(2026, 1, 1, 10, 0, 0)
    candles = [make_row(104, 97, 100, entry_time + timedelta(minutes=15))]

    res = run_sim("FOO", "15m", entry_time, 100, 98, 103, candles)
    assert res["exit_reason"] == "SL_HIT"
    assert res["exit_price"] == 98


def test_target_only():
    entry_time = datetime(2026, 1, 1, 10, 0, 0)
    candles = [make_row(104, 99, 100, entry_time + timedelta(minutes=15))]

    res = run_sim("FOO", "15m", entry_time, 100, 98, 103, candles)
    assert res["exit_reason"] == "TARGET_HIT"
    assert res["exit_price"] == 103


def test_stop_only():
    entry_time = datetime(2026, 1, 1, 10, 0, 0)
    candles = [make_row(101, 97, 100, entry_time + timedelta(minutes=15))]

    res = run_sim("FOO", "15m", entry_time, 100, 98, 103, candles)
    assert res["exit_reason"] == "SL_HIT"
    assert res["exit_price"] == 98


def test_neither_continues_then_target():
    entry_time = datetime(2026, 1, 1, 10, 0, 0)
    # first candle neither, second hits target
    c1 = make_row(102, 99, 101, entry_time + timedelta(minutes=15))
    c2 = make_row(104, 99, 103, entry_time + timedelta(minutes=30))
    candles = [c1, c2]

    res = run_sim("FOO", "15m", entry_time, 100, 98, 103, candles)
    assert res["exit_reason"] == "TARGET_HIT"
    assert res["exit_price"] == 103


def test_eod_exit_when_no_hits():
    entry_time = datetime(2026, 1, 1, 10, 0, 0)
    # single future candle that doesn't hit either level -> EOD_EXIT
    c1 = make_row(102, 99, 101, entry_time + timedelta(minutes=15))
    candles = [c1]

    res = run_sim("FOO", "15m", entry_time, 100, 98, 103, candles)
    assert res["exit_reason"] == "EOD_EXIT"
    assert res["exit_price"] == 101


def test_no_exit_data_when_no_future_candles():
    entry_time = datetime(2026, 1, 1, 10, 0, 0)
    candles = []

    res = run_sim("FOO", "15m", entry_time, 100, 98, 103, candles)
    assert res["exit_reason"] == "NO_EXIT_DATA"
    assert res["exit_price"] is None
