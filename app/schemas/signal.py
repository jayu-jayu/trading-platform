from pydantic import BaseModel, ConfigDict
from datetime import datetime


class SignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    asset_type: str
    signal_type: str
    entry_price: float
    stop_loss: float
    target: float
    atr_value: float
    rsi_value: float | None
    vwap_value: float | None
    volume_ratio: float | None
    rules_passed: list[str]
    sector_proxy: str | None
    market_regime: str
    strength_score: int | None
    outcome: str
    generated_at: datetime
    tier: str = "INSTITUTIONAL"
    rules_passed_count: int = 6


class SignalListResponse(BaseModel):
    scan_timestamp: datetime | None
    market_regime: str
    total_scanned: int
    signals: list[SignalResponse]
    developing_signals: list[SignalResponse] = []


class MarketStatusResponse(BaseModel):
    is_market_open: bool
    is_signal_window: bool
    market_regime: str
    server_time_ist: datetime
