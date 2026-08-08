"""
Standalone script to verify every symbol in the configured watchlist
actually resolves on Yahoo Finance, before you deploy or after NSE's
quarterly F&O eligibility review might have changed the underlying list.

Run locally (needs real network access — won't work in a sandboxed CI runner
with restricted egress):

    python scripts/validate_watchlist.py

Exits non-zero and prints the exact dead symbols if any are found, so you
can remove or replace them in app/config.py before deploying.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.data_fetcher import fetch_all


async def main():
    all_symbols = settings.full_watchlist + [settings.NIFTY_INDEX_SYMBOL]
    print(f"Checking {len(all_symbols)} symbols against Yahoo Finance...\n")

    results = await fetch_all(all_symbols, interval="15m", rng="1d")

    dead = [r["symbol"] for r in results if r["error"] is not None]
    alive = [r["symbol"] for r in results if r["error"] is None]

    print(f"✓ {len(alive)} symbols resolved correctly")
    if dead:
        print(f"✗ {len(dead)} symbols FAILED — remove or fix these in app/config.py:\n")
        for sym in dead:
            err = next(r["error"] for r in results if r["symbol"] == sym)
            print(f"  {sym}: {err}")
        sys.exit(1)
    else:
        print("\nAll symbols are valid. Safe to deploy.")


if __name__ == "__main__":
    asyncio.run(main())
