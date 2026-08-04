from pydantic import BaseModel, ConfigDict
from datetime import datetime


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    entry_price: float
    quantity: int
    stop_loss: float
    target: float
    status: str
    exit_price: float | None
    realized_pnl: float | None
    opened_at: datetime
    closed_at: datetime | None


class PortfolioResponse(BaseModel):
    virtual_capital: float
    available_capital: float
    total_realized_pnl: float
    total_trades: int
    winning_trades: int
    win_rate_pct: float
    open_positions: list[PositionResponse]
    closed_positions_today: list[PositionResponse]


class OpenPositionRequest(BaseModel):
    signal_id: int
