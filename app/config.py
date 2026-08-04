"""
Central settings for the single-service deployment. No auth, no per-user
scoping — this app runs one shared paper-trading portfolio for whoever
opens the URL, by design (see README).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    ENVIRONMENT: str = "production"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Render (and most managed Postgres providers) hand out URLs as
        postgres:// or postgresql://, but SQLAlchemy's async engine needs
        the asyncpg driver explicitly in the scheme. Normalize automatically
        so deployment doesn't break on this easy-to-miss detail."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    SCAN_INTERVAL_MINUTES: int = 5
    DEFAULT_VIRTUAL_CAPITAL: float = 500_000.0

    # Liquid NSE Nifty 50 stocks
    STOCK_WATCHLIST: list[str] = [
        "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
        "TATASTEEL.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS", "ITC.NS",
        "LT.NS", "BHARTIARTL.NS", "MARUTI.NS", "SUNPHARMA.NS", "TATAMOTORS.NS",
        "HINDUNILVR.NS", "BAJFINANCE.NS", "ADANIENT.NS", "NTPC.NS", "POWERGRID.NS",
    ]

    # Liquid intraday-tradeable NSE ETFs, scanned alongside stocks
    ETF_WATCHLIST: list[str] = [
        "NIFTYBEES.NS", "BANKBEES.NS", "GOLDBEES.NS", "JUNIORBEES.NS", "ITBEES.NS",
    ]

    NIFTY_INDEX_SYMBOL: str = "^NSEI"

    @property
    def full_watchlist(self) -> list[str]:
        return self.STOCK_WATCHLIST + self.ETF_WATCHLIST


settings = Settings()
