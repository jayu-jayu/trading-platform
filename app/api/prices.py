from fastapi import APIRouter
from app.config import settings
from app.services.data_fetcher import fetch_all
from app.services.indicators import chart_result_to_df
from app.schemas.price import PriceQuote, PriceListResponse

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/", response_model=PriceListResponse)
async def get_live_prices():
    """Current price snapshot for stocks + ETFs, fetched concurrently."""
    stock_results, etf_results = await _fetch_watchlists()
    quotes = []
    for r, asset_type in [(sr, "STOCK") for sr in stock_results] + [(er, "ETF") for er in etf_results]:
        df = chart_result_to_df(r.get("raw"))
        if df is None or len(df) < 2:
            continue
        last, prev = df.iloc[-1], df.iloc[-2]
        change_pct = round(((last["close"] - prev["close"]) / prev["close"]) * 100, 2)
        quotes.append(PriceQuote(
            symbol=r["symbol"], asset_type=asset_type,
            last_price=round(float(last["close"]), 2),
            change_pct=change_pct,
            volume=int(last["volume"]),
            timestamp=str(last["timestamp"]),
        ))
    return PriceListResponse(prices=quotes)


async def _fetch_watchlists():
    import asyncio
    stock_task = fetch_all(settings.STOCK_WATCHLIST, interval="15m", rng="1d")
    etf_task = fetch_all(settings.ETF_WATCHLIST, interval="15m", rng="1d")
    return await asyncio.gather(stock_task, etf_task)
