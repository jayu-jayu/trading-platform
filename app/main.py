"""
NSE Intraday Stock & ETF Signal Platform — single-service deployment.

One FastAPI app serves both the JSON API (under /api/*) and the dashboard
itself (a single embedded HTML/JS template at "/", no separate frontend
build, no login). Designed for a 1-click Render web service deploy.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.api.router import api_router
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.services.paper_trading import get_or_create_portfolio

# Register models on Base.metadata before create_all runs
from app.models import signal, portfolio, position  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await get_or_create_portfolio(session)  # ensure the single portfolio row exists

    start_scheduler()
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
