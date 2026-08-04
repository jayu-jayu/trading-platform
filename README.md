# NSE Intraday Signal Platform — Single-Service Edition

One FastAPI application. No separate frontend build, no login, no Vercel —
just `uvicorn app.main:app` and you have the full dashboard plus API on one
URL. Built for a 1-click Render web service deploy.

```
nse-platform/
├── app/
│   ├── main.py              FastAPI app — serves API + the dashboard itself
│   ├── config.py            Settings, watchlist, ETF list
│   ├── templates/
│   │   └── index.html       The ENTIRE frontend — one file, inline CSS/JS
│   ├── models/               SignalHistory, Portfolio (single row), Position
│   ├── schemas/               Pydantic request/response models
│   ├── services/
│   │   ├── data_fetcher.py   Concurrent Yahoo Finance chart-query fetching
│   │   ├── indicators.py     EMA/RSI/ATR/VWAP/rolling-high calculations
│   │   ├── signal_engine.py  The refined 6-rule engine
│   │   ├── sector_map.py     Stock -> sector ETF mapping (Rule 6)
│   │   ├── scanner.py        Orchestrates one full concurrent scan
│   │   └── paper_trading.py  Position sizing, open/close, P&L
│   ├── scheduler/jobs.py     APScheduler — runs scans during market hours
│   └── api/                  signals.py, prices.py, portfolio.py routes
├── requirements.txt
├── render.yaml               1-click Render deploy config (web + Postgres)
└── .env.example
```

## No login, by design

There is exactly one paper-trading portfolio, shared by anyone who opens
the URL. Opening the dashboard drops you straight into the live signal
feed — no sign-up, no auth token, nothing gating the view. This matches
what you asked for; if you ever want to put this behind a password (e.g.
before sharing the URL publicly), the cleanest option is Render's built-in
"Basic Auth" environment toggle rather than rebuilding a login system.

## The refined 6-Rule Engine

| # | Rule | What it checks |
|---|------|-----------------|
| 1 | Institutional VWAP Cross & Hold | Price crossed above VWAP recently AND has held above it for 2+ candles (not a single-tick poke) |
| 2 | Multi-period ATR Breakout | Close breaks above the prior 20-period high by ≥0.25x ATR — a volatility-adjusted breakout, not just any new high |
| 3 | Volume Spike | Current candle volume ≥ 1.5x the 10-period average (relative volume filter) |
| 4 | Nifty Trend Gatekeeper | Nifty 50 above its own 15m 20-EMA = market regime BULLISH; no signals otherwise |
| 5 | RSI Momentum Reversal | RSI14 dipped below 45 in the last 5 candles, then crossed back up through 50 |
| 6 | Sector/ETF Correlation Scan | The stock's mapped sector ETF (see `sector_map.py`) is also trending above its own 20-EMA — confirms the move isn't an isolated single-stock spike |

All 6 must pass. Verified with targeted unit tests against both crafted
pass and fail scenarios for each rule — see the conversation for details,
or re-run similar tests yourself against `app/services/signal_engine.py`.

**Watchlist:** 20 liquid Nifty 50 stocks + 5 liquid NSE ETFs (NIFTYBEES,
BANKBEES, GOLDBEES, JUNIORBEES, ITBEES), configurable in `config.py`.

## Deploy to Render (1-click via render.yaml)

1. Push this repo to GitHub.
2. In Render: **New +** → **Blueprint** → connect the repo. Render reads
   `render.yaml` automatically and provisions both the web service and a
   free Postgres database, wiring `DATABASE_URL` between them.
3. Click **Apply**. First deploy takes a few minutes.
4. Open the service URL — you're straight into the dashboard.

Render hands out `DATABASE_URL` as `postgres://...` — `config.py` already
normalizes that to the `postgresql+asyncpg://` scheme SQLAlchemy's async
engine needs, so no manual edit required.

### Manual deploy (any host)

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Run locally

```bash
# Postgres via Docker (or point DATABASE_URL at any Postgres instance)
docker run -d --name nse-pg -e POSTGRES_USER=nse_user -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=nse_platform -p 5432:5432 postgres:16-alpine

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # DATABASE_URL already points at the Docker container above

uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` — dashboard and API on the same origin, no
CORS config needed since there's no separate frontend server anymore.

Tables are created automatically on first startup (`Base.metadata.create_all`
in the lifespan handler) — no Alembic migration step required for this
single-portfolio schema.

## What's different from the previous two-service version

- **No auth** — `User` model, JWT, login/register endpoints all removed
- **No React/Vite** — the old `frontend/` project is gone; `templates/index.html`
  is the entire UI, vanilla JS, no build step
- **Single shared portfolio** — `Portfolio` is a single DB row (id=1),
  not scoped per-user; `Position` no longer has a `user_id`
- **New rule set** — VWAP cross-and-hold, ATR breakout, volume spike, Nifty
  gatekeeper, RSI momentum reversal, sector/ETF correlation (replaces the
  earlier support-proximity + green-candle-surge + news-sentiment version)
- **ETFs added** — the scanner now covers 5 liquid NSE ETFs alongside the
  20 stocks, with `asset_type` (`STOCK`/`ETF`) tracked throughout
- **Default capital raised** to ₹5,00,000 (was ₹500)

## Known limitations to be aware of

- **Data source is still unofficial** Yahoo Finance chart-query parsing —
  fine for paper trading, not something to build real-money execution on
  without switching to a licensed broker API (Kite Connect / Upstox / Fyers)
- **No auth means no per-user history.** If you deploy this publicly, every
  visitor sees and can act on the same shared portfolio and position list.
  Fine for a personal dashboard or demo; not fine for multiple people using
  it independently — that would need auth reintroduced
- **Sector/ETF correlation (Rule 6)** uses a simplified two-bucket map
  (banking stocks → BANKBEES, IT stocks → ITBEES, everything else →
  NIFTYBEES) rather than a full sector-relative-strength model — a
  reasonable approximation, not institutional-grade sector analytics
