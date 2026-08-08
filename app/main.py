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
from app.db.session import AsyncSessionLocal
from app.api.router import api_router
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.services.paper_trading import get_or_create_portfolio
from app.services.data_fetcher import fetch_all

# Model imports kept here so they're available to the rest of the app at
# import time (Alembic's env.py imports them separately for its own use).
from app.models import signal, portfolio, position, price_cache, backtest, shadow_ledger  # noqa: F401

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


async def _verify_migrations_applied(session):
    """
    Fails fast and LOUDLY if migrations haven't actually been applied,
    instead of letting the first real query (get_or_create_portfolio,
    below) crash with a confusing "no such table" error that gives no clue
    about the actual cause. This does not bypass anything — the app still
    refuses to start under the same underlying condition — it just makes
    that condition immediately diagnosable instead of a mystery.

    Root causes this catches: DATABASE_URL pointing at an empty/wrong
    database, or `alembic upgrade head` never having run before this
    process started (on Render, this happens if the service was deployed
    as a plain Web Service rather than via the Blueprint flow — render.yaml
    is ONLY read through 'New + -> Blueprint -> Apply', not a normal git-push
    deploy to an already-existing service).
    """
    from sqlalchemy import text
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    repo_root = BASE_DIR.parent
    alembic_cfg = AlembicConfig(str(repo_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(repo_root / "alembic"))
    expected_head = ScriptDirectory.from_config(alembic_cfg).get_current_head()

    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        row = result.first()
    except Exception as exc:
        raise RuntimeError(
            "STARTUP FAILED: the 'alembic_version' table doesn't exist, which means "
            "database migrations have never been applied to this DATABASE_URL. This "
            "app no longer auto-creates tables — Alembic owns schema management — so "
            "`alembic upgrade head` must run against this database before the app starts.\n\n"
            "On Render specifically: render.yaml's startCommand runs this automatically, "
            "but render.yaml is ONLY applied if this service was deployed via "
            "'New + -> Blueprint -> Apply'. A plain Web Service (created by connecting a "
            "repo directly, or git-pushing to an already-existing service) ignores "
            "render.yaml entirely and uses whatever Start Command is set in that service's "
            "Dashboard -> Settings instead. Check that field reads exactly:\n"
            '  sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"\n\n'
            f"Original database error: {exc}"
        ) from exc

    if row is None:
        raise RuntimeError(
            "STARTUP FAILED: 'alembic_version' table exists but is empty — migrations "
            "partially applied or interrupted mid-run. Run `alembic upgrade head` manually "
            "against DATABASE_URL to resolve, then redeploy."
        )

    current = row[0]
    if current != expected_head:
        raise RuntimeError(
            f"STARTUP FAILED: database is at migration '{current}' but this code expects "
            f"'{expected_head}'. Run `alembic upgrade head` against DATABASE_URL before "
            "starting this app."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema management is now Alembic's job, not this app's — migrations
    # run via `alembic upgrade head` before this process starts (see
    # render.yaml's startCommand and the README migration guide). Running
    # create_all here too would risk it silently creating a table Alembic
    # doesn't know about, then `alembic upgrade head` failing with
    # "table already exists" on the next migration.

    async with AsyncSessionLocal() as session:
        await _verify_migrations_applied(session)
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
