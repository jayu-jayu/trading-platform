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


class OpenCandidateRequest(BaseModel):
    """
    Used to open a paper position on a DEVELOPING-tier card straight from
    the dashboard. Unlike OpenPositionRequest (which references an already
    -persisted institutional signal by id), a developing-tier signal isn't
    written to signal_history until someone actually acts on it — this
    carries the full computed payload so the backend can persist it and
    open the position in one step.
    """
    symbol: str
    asset_type: str
    signal_type: str = "BUY"
    entry_price: float
    stop_loss: float
    target: float
    atr_value: float
    rsi_value: float | None = None
    vwap_value: float | None = None
    volume_ratio: float | None = None
    rules_passed: list[str] = []
    sector_proxy: str | None = None
    market_regime: str
    strength_score: int | None = None
    tier: str = "DEVELOPING"
