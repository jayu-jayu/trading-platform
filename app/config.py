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

    # Curated liquid NSE F&O universe (~115 symbols), organized by sector.
    #
    # HONESTY NOTE: NSE reviews F&O eligibility quarterly (stocks are added
    # and removed based on volume/market-cap criteria), and this list was
    # curated from public F&O reference sources as of August 2026 — it is
    # NOT a live pull from NSE's official circular. A wrong or delisted
    # ticker here fails *silently* (that symbol's fetch just errors out and
    # gets skipped — nothing breaks, you just quietly get fewer symbols
    # scanned than you think). Two things mitigate this:
    #   1. `scripts/validate_watchlist.py` — run it locally against a real
    #      network connection to check every symbol actually resolves on
    #      Yahoo Finance before you deploy, and to catch NSE's next quarterly
    #      review before it silently shrinks your scan coverage.
    #   2. The app logs a startup warning (see main.py) listing any symbol
    #      that failed to fetch on the first scan after deploy.
    # For the authoritative, always-current list, NSE publishes it directly:
    # https://www.nseindia.com/products-services/equity-derivatives-list-underlyings
    STOCK_WATCHLIST: list[str] = [
        # Banking & Financials
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS",
        "INDUSINDBK.NS", "BANKBARODA.NS", "PNB.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS",
        "AUBANK.NS", "BANDHANBNK.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS",
        "CHOLAFIN.NS", "MUTHOOTFIN.NS", "LICHSGFIN.NS", "PFC.NS", "RECLTD.NS",
        "SBILIFE.NS", "HDFCLIFE.NS", "ICICIGI.NS", "ICICIPRULI.NS", "SBICARD.NS",
        "HDFCAMC.NS", "ANGELONE.NS", "CDSL.NS", "BSE.NS", "PAYTM.NS",

        # IT & Technology
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
        "LTIM.NS", "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "OFSS.NS",

        # Energy, Oil & Gas, Power
        "RELIANCE.NS", "ONGC.NS", "IOC.NS", "BPCL.NS", "GAIL.NS",
        "NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS", "ADANIPOWER.NS", "ADANIENSOL.NS",
        "JSWENERGY.NS", "COALINDIA.NS", "PETRONET.NS",

        # Metals & Mining
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "HINDZINC.NS",
        "SAIL.NS", "NMDC.NS", "NATIONALUM.NS", "JINDALSTEL.NS",

        # Autos & Auto Ancillaries
        "MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS",
        "TVSMOTOR.NS", "HEROMOTOCO.NS", "ASHOKLEY.NS", "BOSCHLTD.NS", "MOTHERSON.NS",
        "BALKRISIND.NS", "APOLLOTYRE.NS", "EXIDEIND.NS",

        # FMCG & Consumer
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS",
        "MARICO.NS", "TATACONSUM.NS", "GODREJCP.NS", "VBL.NS", "UNITDSPR.NS",
        "COLPAL.NS", "PGHH.NS",

        # Pharma & Healthcare
        "SUNPHARMA.NS", "DIVISLAB.NS", "CIPLA.NS", "DRREDDY.NS", "TORNTPHARM.NS",
        "ZYDUSLIFE.NS", "AUROPHARMA.NS", "LUPIN.NS", "ALKEM.NS", "BIOCON.NS",
        "APOLLOHOSP.NS", "MAXHEALTH.NS", "LAURUSLABS.NS", "IPCALAB.NS",

        # Cement, Building Materials & Industrials
        "ULTRACEMCO.NS", "GRASIM.NS", "SHREECEM.NS", "AMBUJACEM.NS", "ACC.NS",
        "LT.NS", "SIEMENS.NS", "ABB.NS", "CUMMINSIND.NS", "HAVELLS.NS",
        "VOLTAS.NS", "POLYCAB.NS", "BEL.NS", "HAL.NS", "BHARATFORG.NS",

        # Telecom, Retail & Consumer Internet
        "BHARTIARTL.NS", "ADANIENT.NS", "ADANIPORTS.NS", "DMART.NS", "TITAN.NS",
        "TRENT.NS", "ASIANPAINT.NS", "PIDILITIND.NS", "NAUKRI.NS", "ETERNAL.NS",
        "DLF.NS", "INDIGO.NS", "IRCTC.NS",

        # Chemicals & Agri
        "UPL.NS", "SRF.NS", "PIIND.NS", "DEEPAKNTR.NS", "AARTIIND.NS",
        "TATACHEM.NS",
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
