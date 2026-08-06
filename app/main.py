"""
NSE Intraday Stock & ETF Signal Platform — single-service deployment.

One FastAPI app serves both the JSON API (under /api/*) and the dashboard
itself (a single embedded HTML/JS template at "/", no separate frontend
build, no login). Designed for a 1-click Render web service deploy.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.api.router import api_router
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.services.paper_trading import get_or_create_portfolio
from app.services.data_fetcher import fetch_all

# Register models on Base.metadata before create_all runs
from app.models import signal, portfolio, position  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger("nse_platform.startup")


async def _check_watchlist_health():
    """
    Fire-and-forget startup check: fetches every configured symbol once and
    logs (doesn't crash the app) any that fail — the fastest way to notice
    a stale ticker after NSE's quarterly F&O review, without needing to run
    scripts/validate_watchlist.py manually after every deploy.
    """
    try:
        results = await fetch_all(settings.full_watchlist, interval="15m", rng="1d")
        dead = [r["symbol"] for r in results if r["error"] is not None]
        if dead:
            logger.warning(
                "Watchlist health check: %d of %d symbols failed to fetch on startup: %s. "
                "These will silently be skipped in scans until fixed in app/config.py.",
                len(dead), len(results), ", ".join(dead),
            )
        else:
            logger.info("Watchlist health check: all %d symbols resolved correctly.", len(results))
    except Exception as exc:
        logger.warning("Watchlist health check failed to run: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await get_or_create_portfolio(session)  # ensure the single portfolio row exists

    start_scheduler()
    asyncio.create_task(_check_watchlist_health())  # runs in background, doesn't block startup
    yield
    stop_scheduler()


app = FastAPI(
    title="NSE Intraday Signal Platform",
    description="Single-service deployment: 6-rule institutional engine + embedded dashboard.",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serves the entire dashboard — single HTML file, no build step."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
