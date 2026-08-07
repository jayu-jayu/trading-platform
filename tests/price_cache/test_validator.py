import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from app.services import price_cache

# Helper to create a simple candle row
def make_row(ts, open, high, low, close, volume=100):
    return SimpleNamespace(candle_timestamp=ts, open=open, high=high, low=low, close=close, volume=volume)

def test_valid_dataset(monkeypatch):
    base = datetime(2026,1,1,10,0,0, tzinfo=timezone.utc)
    candles = [make_row(base + timedelta(minutes=15*i), 100+i, 101+i, 99+i, 100+i) for i in range(30)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is True
    assert res["candle_count"] == len(candles)
    assert res["duplicate_count"] == 0


def test_empty_dataset(monkeypatch):
    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return []

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is False
    assert "empty dataset" in res["errors"]


def test_duplicate_timestamp(monkeypatch):
    ts = datetime(2026,1,1,10,0,0, tzinfo=timezone.utc)
    candles = [make_row(ts,100,101,99,100), make_row(ts,100,101,99,100)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is False
    assert res["duplicate_count"] >= 1


def test_non_monotonic_timestamp(monkeypatch):
    ts1 = datetime(2026,1,1,10,15, tzinfo=timezone.utc)
    ts2 = datetime(2026,1,1,10,0, tzinfo=timezone.utc)
    candles = [make_row(ts1,100,101,99,100), make_row(ts2,101,102,100,101)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is False
    assert "non-monotonic timestamps detected" in res["errors"]


def test_invalid_ohlc(monkeypatch):
    base = datetime(2026,1,1,10,0, tzinfo=timezone.utc)
    # invalid: high < low
    candles = [make_row(base,100,98,99,97)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is False
    assert res["invalid_ohlc_count"] >= 1


def test_negative_volume(monkeypatch):
    base = datetime(2026,1,1,10,0, tzinfo=timezone.utc)
    candles = [make_row(base,100,101,99,100, volume=-10)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is False
    assert res["negative_volume_count"] >= 1


def test_gap_detection(monkeypatch):
    base = datetime(2026,1,1,10,0, tzinfo=timezone.utc)
    # two candles separated by 1 hour => 3 missing 15min candles
    candles = [make_row(base,100,101,99,100), make_row(base + timedelta(hours=1),101,102,100,101)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is True  # gaps are warnings, not fatal by default
    assert res["gap_count"] >= 3


def test_timezone_inconsistency(monkeypatch):
    # first timestamp naive (no tz), second tz-aware
    ts1 = datetime(2026,1,1,10,0,0)  # naive
    ts2 = datetime(2026,1,1,10,15,0, tzinfo=timezone.utc)
    candles = [make_row(ts1,100,101,99,100), make_row(ts2,101,102,100,101)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m"))
    assert res["valid"] is False
    assert res["timezone_errors"] >= 1


def test_insufficient_coverage(monkeypatch):
    base = datetime(2026,1,2,10,0, tzinfo=timezone.utc)
    candles = [make_row(base,100,101,99,100)]

    async def fake_get_cached_candles(symbol, interval, start=None, end=None):
        return candles

    monkeypatch.setattr(price_cache, "get_cached_candles", fake_get_cached_candles)
    res = asyncio.run(price_cache.validate_cached_candles("FOO", "15m", start=datetime(2026,1,1,0,0, tzinfo=timezone.utc)))
    assert res["valid"] is False
    assert "coverage start is after requested start" in res["errors"]
