"""
Async market data via direct Yahoo Finance chart-query parsing — same
approach for stocks, ETFs, and the Nifty index. Fully concurrent across
the whole watchlist using a single shared httpx.AsyncClient.

NOTE: unofficial endpoint. Fine for paper trading; swap for a licensed
broker API (Kite Connect / Upstox / Fyers) before any real-money features.
"""
import httpx
import asyncio
from typing import Any

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NSESignalPlatform/1.0)"}


async def _fetch_one(client: httpx.AsyncClient, symbol: str, interval: str, rng: str) -> dict[str, Any]:
    try:
        resp = await client.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"interval": interval, "range": rng},
            headers=HEADERS,
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        return {"symbol": symbol, "raw": result, "error": None}
    except Exception as exc:
        return {"symbol": symbol, "raw": None, "error": str(exc)}


async def fetch_all(symbols: list[str], interval: str = "15m", rng: str = "5d") -> list[dict]:
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_one(client, sym, interval, rng) for sym in symbols]
        return await asyncio.gather(*tasks)


async def fetch_index(symbol: str, interval: str = "15m", rng: str = "5d") -> dict:
    async with httpx.AsyncClient() as client:
        return await _fetch_one(client, symbol, interval, rng)


async def fetch_full_scan_data(symbols: list[str], nifty_symbol: str) -> dict:
    """One concurrent batch: Nifty index + all symbols' 15m candles.
    (v3 engine is 15m-only — no 1h fetch here anymore; that was dead weight
    the earlier MTF-trend rule needed but the current rule set doesn't.)"""
    async with httpx.AsyncClient() as client:
        nifty_task = _fetch_one(client, nifty_symbol, "15m", "5d")
        s15_tasks = [_fetch_one(client, s, "15m", "5d") for s in symbols]
        results = await asyncio.gather(nifty_task, *s15_tasks)

    nifty_raw = results[0]
    s15_results = results[1:]

    return {
        "nifty": nifty_raw,
        "15m": {r["symbol"]: r for r in s15_results},
    }
