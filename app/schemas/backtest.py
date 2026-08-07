from pydantic import BaseModel
from datetime import datetime


class BacktestRunRequest(BaseModel):
    symbols: list[str]
    start_date: datetime
    end_date: datetime
    interval: str = "15m"
    label: str | None = None


class BacktestTradeResponse(BaseModel):
    id: int
    symbol: str
    asset_type: str
    tier: str
    rules_passed: list[str]
    entry_time: datetime
    entry_price: float
    stop_loss: float
    target: float
    exit_time: datetime | None
    exit_price: float | None
    exit_reason: str | None
    pnl: float | None
    pnl_pct: float | None

    class Config:
        from_attributes = True


class BacktestRunResponse(BaseModel):
    id: int
    label: str | None
    symbols: list[str]
    interval: str
    start_date: datetime
    end_date: datetime
    total_trades: int
    institutional_trades: int
    developing_trades: int
    winning_trades: int
    win_rate_pct: float | None
    profit_factor: float | None
    max_drawdown_pct: float | None
    total_pnl: float | None
    status: str
    error_detail: str | None
    created_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class BacktestRunDetail(BacktestRunResponse):
    trades: list[BacktestTradeResponse] = []


class CachePopulateRequest(BaseModel):
    symbols: list[str]
    interval: str = "15m"
    rng: str = "5d"
