from pydantic import BaseModel


class PriceQuote(BaseModel):
    symbol: str
    asset_type: str
    last_price: float
    change_pct: float
    volume: int
    timestamp: str


class PriceListResponse(BaseModel):
    prices: list[PriceQuote]
