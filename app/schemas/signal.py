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

    # Phase 2 additions — all optional with safe defaults, so any existing
    # code constructing a SignalResponse without them still works.
    trend_score: float | None = None
    volume_score: float | None = None
    momentum_score: float | None = None
    vwap_score: float | None = None
    market_score: float | None = None
    market_regime_detail: str | None = None

    # Phase 3 additions
    mtf_confirmed: bool | None = None
    sector_relative_strength_pct: float | None = None


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
