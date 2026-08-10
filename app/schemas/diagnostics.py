from pydantic import BaseModel
from datetime import datetime


class RuleDiagnostic(BaseModel):
    rule_id: str
    label: str
    passed: bool
    detail: str


class SymbolDiagnostic(BaseModel):
    symbol: str
    asset_type: str
    data_available: bool
    tier: str  # INSTITUTIONAL | DEVELOPING | WEAK | NO_DATA
    rules_passed_count: int
    total_rules: int
    in_time_window: bool
    time_window_detail: str
    rules: list[RuleDiagnostic]

    # Phase 2 additions — all optional, so a diagnostics dict built before
    # these fields existed still validates fine.
    market_regime_detail: dict | None = None
    pivot_levels: dict | None = None
    pivot_description: str | None = None
    confidence_breakdown: dict | None = None


class DiagnosticsResponse(BaseModel):
    scan_timestamp: datetime | None
    market_regime: str
    market_regime_detail: dict | None = None
    diagnostics: list[SymbolDiagnostic]
