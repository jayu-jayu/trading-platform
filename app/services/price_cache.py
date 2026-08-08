"""
Historical price cache: populate once from Yahoo Finance, read repeatedly.

This exists so the (upcoming) backtest engine doesn't re-fetch the same
historical candles from Yahoo's unofficial endpoint on every run — both to
protect your live scanner's rate-limit headroom at 140 symbols, and because
repeated backtest iterations would otherwise be re-downloading identical
data every single time.

Usage (once the backtest engine lands, this becomes automatic — for now
it's callable standalone):

    await populate_cache(["RELIANCE.NS", "TCS.NS"], interval="15m", rng="5d")
    candles = await get_cached_candles("RELIANCE.NS", "15m", start, end)
"""
from datetime import datetime
import pandas as pd
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.session import AsyncSessionLocal
from app.models.price_cache import PriceCache
from app.services.data_fetcher import fetch_all
from app.services.indicators import chart_result_to_df


async def populate_cache(symbols: list[str], interval: str = "15m", rng: str = "5d") -> dict:
    """
    Fetches candles for every symbol and upserts them into price_cache.
    Returns a summary dict: {"symbols_fetched": N, "candles_stored": N, "errors": [...]}.

    Safe to call repeatedly — re-fetching an overlapping date range just
    upserts the same rows (unique constraint on symbol+interval+candle_timestamp),
    it doesn't create duplicates.
    """
    results = await fetch_all(symbols, interval=interval, rng=rng)

    errors = []
    total_candles = 0

    async with AsyncSessionLocal() as session:
        for r in results:
            if r["error"] is not None:
                errors.append({"symbol": r["symbol"], "error": r["error"]})
                continue

            df = chart_result_to_df(r["raw"])
            if df is None or len(df) == 0:
                errors.append({"symbol": r["symbol"], "error": "No candle data returned"})
                continue

            rows = [
                {
                    "symbol": r["symbol"],
                    "interval": interval,
                    "candle_timestamp": row["timestamp"].to_pydatetime(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]) if not pd.isna(row["volume"]) else 0,
                    "fetched_at": datetime.utcnow(),
                }
                for _, row in df.iterrows()
            ]

            if not rows:
                continue

            # Dialect-aware upsert: ON CONFLICT DO UPDATE keeps this idempotent
            # regardless of whether you're running against Postgres (prod) or
            # SQLite (local/testing).
            if session.bind.dialect.name == "postgresql":
                stmt = pg_insert(PriceCache).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "interval", "candle_timestamp"],
                    set_={
                        "open": stmt.excluded.open, "high": stmt.excluded.high,
                        "low": stmt.excluded.low, "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume, "fetched_at": stmt.excluded.fetched_at,
                    },
                )
            else:
                stmt = sqlite_insert(PriceCache).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol", "interval", "candle_timestamp"],
                    set_={
                        "open": stmt.excluded.open, "high": stmt.excluded.high,
                        "low": stmt.excluded.low, "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume, "fetched_at": stmt.excluded.fetched_at,
                    },
                )

            await session.execute(stmt)
            total_candles += len(rows)

        await session.commit()

    return {
        "symbols_fetched": len(symbols) - len(errors),
        "candles_stored": total_candles,
        "errors": errors,
    }


async def get_cached_candles(symbol: str, interval: str,
                              start: datetime | None = None, end: datetime | None = None) -> list[PriceCache]:
    """Reads cached candles for one symbol, optionally bounded by a date range —
    this is what the backtest engine will call instead of hitting Yahoo directly."""
    async with AsyncSessionLocal() as session:
        query = select(PriceCache).where(PriceCache.symbol == symbol, PriceCache.interval == interval)
        if start:
            query = query.where(PriceCache.candle_timestamp >= start)
        if end:
            query = query.where(PriceCache.candle_timestamp <= end)
        query = query.order_by(PriceCache.candle_timestamp)

        result = await session.execute(query)
        return result.scalars().all()


async def clear_cache(symbol: str | None = None, interval: str | None = None) -> int:
    """Deletes cached candles, optionally scoped to a symbol/interval. Returns rows deleted."""
    async with AsyncSessionLocal() as session:
        query = delete(PriceCache)
        if symbol:
            query = query.where(PriceCache.symbol == symbol)
        if interval:
            query = query.where(PriceCache.interval == interval)
        result = await session.execute(query)
        await session.commit()
        return result.rowcount
