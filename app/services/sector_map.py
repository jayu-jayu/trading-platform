"""
Lightweight sector/ETF correlation map for Rule 6. Real institutional desks
run full sector-relative-strength models; this is a pragmatic approximation:
each stock is mapped to the most liquid NSE ETF that tracks its sector, and
Rule 6 checks that ETF is also in a bullish short-term trend before
confirming the individual stock's signal — catching cases where one stock
spikes in isolation without real sector participation.
"""

SECTOR_ETF_MAP: dict[str, str] = {
    # Banking / financials -> BANKBEES (Bank Nifty ETF)
    "HDFCBANK.NS": "BANKBEES.NS",
    "ICICIBANK.NS": "BANKBEES.NS",
    "SBIN.NS": "BANKBEES.NS",
    "AXISBANK.NS": "BANKBEES.NS",
    "KOTAKBANK.NS": "BANKBEES.NS",
    "BAJFINANCE.NS": "BANKBEES.NS",

    # IT -> ITBEES
    "INFY.NS": "ITBEES.NS",
    "TCS.NS": "ITBEES.NS",

    # Everything else defaults to the broad market ETF (NIFTYBEES) —
    # sensible fallback for conglomerates, metals, energy, autos, pharma
    # where no single-sector ETF is liquid enough to be a reliable proxy.
}

DEFAULT_SECTOR_ETF = "NIFTYBEES.NS"


def get_sector_proxy(symbol: str) -> str:
    """Returns the ETF used to validate sector participation for `symbol`.
    An ETF checked against itself (or NIFTYBEES) trivially passes — that's
    intentional, since an ETF's Rule 6 check is really just 'is the broad
    market/sector also trending', which Rule 4 already partially covers."""
    return SECTOR_ETF_MAP.get(symbol, DEFAULT_SECTOR_ETF)
