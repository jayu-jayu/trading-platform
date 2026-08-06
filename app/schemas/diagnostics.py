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


class DiagnosticsResponse(BaseModel):
    scan_timestamp: datetime | None
    market_regime: str
    diagnostics: list[SymbolDiagnostic]
