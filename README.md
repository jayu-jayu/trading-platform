## Phase 1 Status: COMPLETE

Alembic, historical price cache, the `as_of` refactor, and the backtest
engine foundation are all implemented and tested — see the implementation
summary provided alongside this repo for full details, test results, and
known limitations.

### Deployment fix included in this update

A production deploy previously crashed at startup with a confusing
`sqlite3.OperationalError: no such table: portfolio`. Root cause: **`render.yaml`
is only honored via Render's "New + → Blueprint → Apply" flow.** If a
service was created as a plain Web Service (connecting a repo directly, or
git-pushing to an already-existing service), Render ignores `render.yaml`
entirely and uses whatever Start Command / env vars are set directly in
that service's Dashboard — which may not include the `alembic upgrade head`
step or the correct `DATABASE_URL`.

**Fix:** `app/main.py` now verifies migrations are actually applied
*before* touching any table, and fails immediately with a clear, actionable
error message if not — instead of a confusing crash three steps later. If
you see a `STARTUP FAILED` message in your Render logs now, it will tell
you exactly what to check.

**To actually fix a live deployment in this state:** open your Render
service's **Settings → Start Command** and confirm it reads exactly:
```
sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```
If it doesn't, either update it manually there, or redeploy via
**New + → Blueprint → Apply** pointing at this repo so `render.yaml` takes
over management of that service going forward. Also verify **Environment
→ DATABASE_URL** matches your Postgres add-on's actual connection string.

### Backtest API (new)

```
POST /api/backtest/cache/populate   { symbols, interval, rng }       — fetch & cache historical candles
POST /api/backtest/run              { symbols, start_date, end_date, interval, label }  — run a walk-forward backtest
GET  /api/backtest/runs             — list recent runs
GET  /api/backtest/runs/{id}        — full run detail including every simulated trade
```

The backtest engine reuses `evaluate_symbol()` directly (via the new
`as_of` parameter) — it contains no trading logic of its own, only
simulation mechanics. It reads exclusively from the price cache; populate
that first for whatever symbols/range you want to test.

**Known limitation carried over from `config.py`'s original honesty note:**
Yahoo's unofficial endpoint only provides a rolling ~60-day lookback, so
backtest date ranges are bounded by that regardless of what you request.

---

## ⚠️ Required one-time step before deploying THIS update

This update introduces Alembic for schema migrations, going forward — no
more manual `ALTER TABLE` scrambles. But your Render database already has
tables (created by the old `create_all` approach, including the `tier`
column you already added manually), and Alembic needs to be told that,
**once**, before it will manage anything else correctly.

**Do this BEFORE pushing/deploying this update:**

1. Open Render dashboard → your Postgres database → **Connect** → **PSQL Command**, and open that shell.
2. Confirm what's actually there first:
   ```sql
   \dt
   ```
   You should see `portfolio`, `signal_history`, `positions` — and critically, **no** `price_cache` table yet, and no `alembic_version` table.
3. Now, from your local machine (not the Render shell — Alembic needs your code checked out), pointed at your **production** `DATABASE_URL`:
   ```bash
   export DATABASE_URL="<your Render Postgres external connection string, with postgresql+asyncpg:// scheme>"
   alembic stamp 0001_baseline_schema
   ```
   **This is deliberately NOT `alembic stamp head`.** `head` would also mark the `price_cache` migration as already applied — which is false, since it doesn't exist in your database yet — and `alembic upgrade head` would then silently do nothing, leaving you without the new table. Stamping at `0001_baseline_schema` specifically tells Alembic "everything up to here already exists; anything after this still needs to run." I tested this exact sequence against a simulated copy of your current schema before writing this.
4. That's it for the one-time step. Deploy normally from here — `render.yaml`'s start command now runs `alembic upgrade head` automatically before every boot, so the `price_cache` table gets created on this deploy, and any future migration lands automatically on every deploy after.

If you skip step 3 and deploy anyway, `alembic upgrade head` will try to
`CREATE TABLE portfolio` (etc.) against a database where that table already
exists, and the deploy will fail loudly — which is at least a safe failure
(nothing gets corrupted, the old process just keeps running until you fix
it), but better to avoid it by doing the stamp first.

---

# NSE Intraday Signal Platform — Single-Service Edition

One FastAPI application. No separate frontend build, no login, no Vercel —
just `uvicorn app.main:app` and you have the full dashboard plus API on one
URL. Built for a 1-click Render web service deploy.

```
nse-platform/
├── app/
│   ├── main.py              FastAPI app — serves API + dashboard + startup watchlist health check
│   ├── config.py            Settings, 135-stock + 5-ETF watchlist
│   ├── templates/
│   │   └── index.html       The ENTIRE frontend — one file, inline CSS/JS
│   ├── models/               SignalHistory (+tier), Portfolio (single row), Position
│   ├── schemas/               Pydantic request/response models + diagnostics.py
│   ├── services/
│   │   ├── data_fetcher.py   Concurrent Yahoo Finance chart-query fetching (15m only)
│   │   ├── indicators.py     EMA/RSI/ATR/VWAP/rolling-high calculations
│   │   ├── signal_engine.py  The refined 6-rule engine + full diagnostics + tiering
│   │   ├── sector_map.py     Stock -> sector ETF mapping (Rule 6)
│   │   ├── scanner.py        Orchestrates one full concurrent scan across all symbols
│   │   └── paper_trading.py  Position sizing, open/close, P&L, candidate-signal persistence
│   ├── scheduler/jobs.py     APScheduler — runs scans during market hours
│   └── api/                  signals.py, prices.py, portfolio.py routes
├── scripts/
│   └── validate_watchlist.py Run locally to check every symbol resolves before deploying
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

All 6 must pass for an **Institutional** signal. Verified with targeted unit
tests against both crafted pass and fail scenarios for each rule.

**Watchlist:** 135 liquid NSE F&O stocks across banking, IT, energy, metals,
autos, FMCG, pharma, cement/industrials, telecom/retail, and chemicals,
plus 5 liquid ETFs (NIFTYBEES, BANKBEES, GOLDBEES, JUNIORBEES, ITBEES).
Configurable in `config.py`. See the honesty note in that file's comments —
this list was curated from public F&O reference sources, not pulled live
from NSE's official quarterly circular, so run `scripts/validate_watchlist.py`
before each deploy to catch any symbol that's changed or been delisted.

**Signal window:** 09:15–15:15 IST. Since every rule runs on 15-minute
candles, the practical earliest usable scan is ~09:30 (the 09:15 candle is
still forming until then) — the 09:15 start doesn't cost anything, it's
just worth knowing it isn't quite "catching signals at the literal open."

## Scan Diagnostics — see exactly why a symbol did or didn't fire

Every scan now evaluates **every** watchlist symbol (not just qualifying
ones) and keeps a full per-rule breakdown: which of the 6 rules passed,
which failed, and the exact numbers involved (e.g. *"Volume ratio 1.31x is
below the 1.5x relative-volume bar"*). Available at `GET /api/signals/diagnostics`
and rendered as a filterable, expandable table on the dashboard below the
signal feed — sorted so near-misses surface first.

## Tiered Signal System

| Tier | Rules passed | Where it shows up |
|------|--------------|---------------------|
| **Institutional** | 6/6 | Main feed, solid card, auto-persisted to `signal_history`, broadcast live over WebSocket |
| **Developing** | 4-5/6 | Main feed, dashed amber card labeled "DEVELOPING 4/6" or "5/6" — lower-confidence, shown for visibility |
| **Weak** | <4/6 | Diagnostics table only, not shown as a feed card |
| **No Data** | — | Diagnostics table only — not enough candle history yet |

**Developing-tier cards are NOT auto-persisted or auto-traded.** They're
computed fresh every scan and only written to `signal_history` if you
explicitly click "Open Paper Position" on one — at that moment,
`POST /api/portfolio/positions/open-candidate` persists it (tagged
`tier: DEVELOPING`) and opens the position in the same step, so you still
get a full audit trail without treating every near-miss as a real signal.

## Deploy to Render (1-click via render.yaml)

1. Push this repo to GitHub.
2. In Render: **New +** → **Blueprint** → connect the repo. Render reads
   `render.yaml` automatically and provisions both the web service and a
   free Postgres database, wiring `DATABASE_URL` between them.
3. Click **Apply**. First deploy takes a few minutes.
4. Open the service URL — you're straight into the dashboard.

If this is an **update to an already-running deployment**, do the manual
DB step at the very top of this file first.

Render hands out `DATABASE_URL` as `postgres://...` — `config.py` already
normalizes that to the `postgresql+asyncpg://` scheme SQLAlchemy's async
engine needs, so no manual edit required there.

### Manual deploy (any host)

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Alembic — schema migrations from here on

Going forward, any schema change is a migration, not a manual `ALTER TABLE`.

```bash
# After changing a model in app/models/*.py:
alembic revision --autogenerate -m "describe the change"

# Review the generated file in alembic/versions/ before applying —
# autogenerate is good but not infallible, especially for renames.

# Apply it locally:
alembic upgrade head

# Applying to Render happens automatically on deploy (see render.yaml),
# but you can also run it manually against production if needed:
export DATABASE_URL="<production connection string>"
alembic upgrade head
```

`app/main.py` no longer runs `Base.metadata.create_all` — schema is
entirely Alembic's responsibility now. This matters if you're testing
locally against a brand new empty database: run `alembic upgrade head`
before starting the app, not after.

## Historical Price Cache (foundation for the backtest engine)

`app/services/price_cache.py` fetches and stores historical OHLCV candles,
upserting on `(symbol, interval, candle_timestamp)` so repeated calls over
overlapping ranges never duplicate rows — verified with an idempotency test
(populate the same range twice, confirm the row count doesn't change).

```python
from app.services.price_cache import populate_cache, get_cached_candles

# Fetch and store — safe to re-run, it upserts
summary = await populate_cache(settings.STOCK_WATCHLIST, interval="15m", rng="5d")
# {"symbols_fetched": 135, "candles_stored": 4200, "errors": [...]}

# Read back for the backtest engine
candles = await get_cached_candles("RELIANCE.NS", "15m", start=..., end=...)
```

This is the foundation the backtest engine (next step) will build on —
it reads from this cache instead of hitting Yahoo Finance on every
backtest iteration.

## Verify the watchlist before deploying

```bash
python scripts/validate_watchlist.py
```

Needs real network access (won't work in a sandboxed CI runner) — checks
all 140 symbols against Yahoo Finance and prints exactly which ones (if
any) fail to resolve, so you can fix `config.py` before deploying instead
of finding out from a quieter-than-expected scan. The app also runs this
same check automatically in the background on every startup and logs any
failures — check your Render logs after a deploy to see it.

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
in the lifespan handler) for a fresh database — but remember, this only
creates missing tables, it doesn't alter existing ones (see the migration
note at the top of this file).

## What's new in this update

- **Scan diagnostics** — full per-rule pass/fail breakdown for every symbol,
  every scan, not just qualifying ones (`GET /api/signals/diagnostics`)
- **Tiered signals** — Institutional (6/6) and Developing (4-5/6) cards,
  both shown in the main feed with distinct styling; Developing signals are
  lazily persisted only when you act on them
- **Signal window widened** to 09:15–15:15 IST (was 09:45–14:30)
- **Watchlist expanded** from 20 to 135 stocks (+5 ETFs unchanged), spanning
  9 sectors, with a validation script and startup health check to catch
  dead tickers before they silently reduce your scan coverage
- **Removed a real inefficiency**: the scanner was fetching unused 1-hour
  candle data for every symbol (leftover from an earlier rule version that
  no longer exists) — dropped it, roughly halving requests per scan at the
  new watchlist size

## What's different from the original two-service version

- **No auth** — `User` model, JWT, login/register endpoints all removed
- **No React/Vite** — the old `frontend/` project is gone; `templates/index.html`
  is the entire UI, vanilla JS, no build step
- **Single shared portfolio** — `Portfolio` is a single DB row (id=1),
  not scoped per-user; `Position` no longer has a `user_id`
- **New rule set** — VWAP cross-and-hold, ATR breakout, volume spike, Nifty
  gatekeeper, RSI momentum reversal, sector/ETF correlation (replaces the
  earlier support-proximity + green-candle-surge + news-sentiment version)
- **ETFs added** — the scanner now covers 5 liquid NSE ETFs alongside the
  stock watchlist, with `asset_type` (`STOCK`/`ETF`) tracked throughout
- **Default capital raised** to ₹5,00,000 (was ₹500)

## Known limitations to be aware of

- **Data source is still unofficial** Yahoo Finance chart-query parsing —
  fine for paper trading, not something to build real-money execution on
  without switching to a licensed broker API (Kite Connect / Upstox / Fyers).
  At 140 symbols, be mindful this is also more requests per scan against an
  unofficial endpoint than the original 25-symbol version — if you start
  seeing fetch errors in the startup health check or diagnostics, rate
  limiting is the likely cause; increasing `SCAN_INTERVAL_MINUTES` helps.
- **No auth means no per-user history.** If you deploy this publicly, every
  visitor sees and can act on the same shared portfolio and position list.
  Fine for a personal dashboard or demo; not fine for multiple people using
  it independently — that would need auth reintroduced
- **Sector/ETF correlation (Rule 6)** uses a simplified map (banking stocks
  → BANKBEES, IT stocks → ITBEES, everything else → NIFTYBEES) rather than
  a full sector-relative-strength model — a reasonable approximation, not
  institutional-grade sector analytics
- **The watchlist is a curated static list, not a live NSE feed** — see the
  honesty note in `config.py`; re-run `scripts/validate_watchlist.py`
  periodically, especially after NSE's quarterly F&O eligibility review
- **Loosening thresholds vs. widening the watchlist**: the Developing tier
  and expanded watchlist both increase how often you'll see *something* in
  the feed, but neither one makes the underlying 6-rule filter itself less
  selective — that's intentional. Don't mistake "more cards visible" for
  "signals are easier to qualify"; the institutional bar hasn't moved.
