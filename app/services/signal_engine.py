"""
The refined 6-Rule Institutional Signal Engine (v3 — with rejection-reason
diagnostics).

  Rule 1 — Institutional VWAP Cross & Hold
  Rule 2 — Multi-period ATR Breakout
  Rule 3 — Volume Spike (Relative Volume >= 1.5x)
  Rule 4 — Nifty Trend Gatekeeper
  Rule 5 — RSI Momentum Reversal
  Rule 6 — Sector/ETF Correlation Scan

Key change from v2: `evaluate_symbol` now ALWAYS returns a full diagnostic
breakdown — one entry per rule, each with a pass/fail flag and a
human-readable detail string showing the actual numbers involved — instead
of silently returning None the moment one rule fails. This is what powers
the "why didn't this fire" visibility and is the foundation for the tiered
signal system (6/6 = Institutional, 4-5/6 = Developing, <4/6 = Weak).

A signal is only "qualified" (eligible for paper trading / persistence)
when all 6 rules pass. Everything else is diagnostic-only.

NOTE on the 09:15 start: since all rules operate on 15-minute candles, the
first candle of the day (09:15-09:30) is still forming until 09:30 — so in
practice the earliest scan with a usable, closed candle is ~09:30, not
09:15. Setting the window to 09:15 doesn't cost anything (early scans will
just show NO_DATA / insufficient-history until the first candle closes),
but it's worth knowing this isn't quite "catching signals at market open"
in the way it might sound.
"""
from datetime import datetime, time
from dataclasses import dataclass, field
import pandas as pd
import pytz

from app.services.indicators import chart_result_to_df, add_indicators, compute_atr_targets
from app.services.sector_map import get_sector_proxy
from app.services.market_analysis import compute_pivot_levels, describe_price_vs_pivots
from app.services.confidence_engine import compute_confidence
from app.services.sector_strength import compute_relative_strength

IST = pytz.timezone("Asia/Kolkata")

SIGNAL_START = time(9, 15)
SIGNAL_END = time(15, 15)

ATR_BREAKOUT_MULTIPLE = 0.25
VOLUME_SPIKE_MULTIPLE = 1.5
RSI_DIP_THRESHOLD = 45.0
RSI_REVERSAL_THRESHOLD = 50.0
ATR_SL_MULTIPLE = 1.0
ATR_TARGET_MULTIPLE = 1.5
VWAP_HOLD_CANDLES = 2
VWAP_CROSS_LOOKBACK = 6

TOTAL_RULES = 6
INSTITUTIONAL_THRESHOLD = 6   # all 6 rules pass
DEVELOPING_THRESHOLD = 4      # 4 or 5 of 6 pass


@dataclass
class RuleResult:
    """One rule's outcome for one symbol — the building block of diagnostics."""
    rule_id: str
    label: str
    passed: bool
    detail: str


@dataclass
class SymbolDiagnostics:
    """Full per-symbol breakdown from one scan, whether or not it qualified."""
    symbol: str
    asset_type: str
    data_available: bool
    rule_results: list[RuleResult] = field(default_factory=list)
    rules_passed_count: int = 0
    tier: str = "NO_DATA"  # INSTITUTIONAL | DEVELOPING | WEAK | NO_DATA
    in_time_window: bool = True
    time_window_detail: str = ""
    qualified_signal: dict | None = None  # populated only when tier == INSTITUTIONAL and in_time_window
    developing_signal: dict | None = None  # populated when tier == DEVELOPING and in_time_window

    # Phase 2 additions — all diagnostic-only, never gate qualification or tier.
    market_regime_detail: dict | None = None  # TRENDING_UP/DOWN, SIDEWAYS, HIGH_VOLATILITY (see market_analysis.py)
    pivot_levels: dict | None = None
    pivot_description: str = ""
    confidence_breakdown: dict | None = None  # {trend, volume, momentum, vwap, market} — see confidence_engine.py

    # Phase 3 additions — also diagnostic-only.
    relative_strength: dict | None = None  # stock vs Nifty (see sector_strength.py)
    sector_relative_strength: dict | None = None  # sector proxy vs Nifty
    mtf_confirmation: dict | None = None  # set post-hoc by scanner.py, only for near-qualifying symbols — see mtf_engine.py

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "data_available": self.data_available,
            "tier": self.tier,
            "rules_passed_count": self.rules_passed_count,
            "total_rules": TOTAL_RULES,
            "in_time_window": self.in_time_window,
            "time_window_detail": self.time_window_detail,
            "rules": [
                {"rule_id": r.rule_id, "label": r.label, "passed": r.passed, "detail": r.detail}
                for r in self.rule_results
            ],
            "market_regime_detail": self.market_regime_detail,
            "pivot_levels": self.pivot_levels,
            "pivot_description": self.pivot_description,
            "confidence_breakdown": self.confidence_breakdown,
            "relative_strength": self.relative_strength,
            "sector_relative_strength": self.sector_relative_strength,
            "mtf_confirmation": self.mtf_confirmation,
        }


def check_time_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    return SIGNAL_START <= now.time() <= SIGNAL_END


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return time(9, 15) <= now.time() <= time(15, 30)


def get_market_regime(nifty_raw: dict) -> str:
    df = chart_result_to_df(nifty_raw.get("raw") if nifty_raw else None)
    if df is None or len(df) < 25:
        return "UNKNOWN"
    df = add_indicators(df)
    last = df.iloc[-1]
    if pd.isna(last["ema20"]):
        return "UNKNOWN"
    return "BULLISH" if last["close"] > last["ema20"] else "BEARISH"


# ---------------------------------------------------------------------------
# Each _check_* function now returns (passed, detail_string) so the reason
# is captured at the exact point of evaluation, not reconstructed after.
# ---------------------------------------------------------------------------

def _check_nifty_gatekeeper(market_regime: str) -> tuple[bool, str]:
    if market_regime == "BULLISH":
        return True, "Nifty 50 is above its 15m 20-EMA (regime BULLISH)."
    if market_regime == "BEARISH":
        return False, "Nifty 50 is below its 15m 20-EMA (regime BEARISH) — market-wide gate shut."
    return False, "Nifty 50 regime could not be determined (insufficient index data)."


def _check_vwap_cross_and_hold(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < VWAP_CROSS_LOOKBACK + 1:
        return False, "Not enough candles yet to evaluate a VWAP cross."

    window = df.tail(VWAP_CROSS_LOOKBACK + 1).reset_index(drop=True)
    if window["vwap"].isna().any():
        return False, "VWAP not yet available for the lookback window (too early in session)."

    crossed = False
    for i in range(1, len(window)):
        prev, curr = window.iloc[i - 1], window.iloc[i]
        if prev["close"] <= prev["vwap"] and curr["close"] > curr["vwap"]:
            crossed = True

    hold_slice = df.tail(VWAP_HOLD_CANDLES)
    held = (hold_slice["close"] > hold_slice["vwap"]).all()
    last = df.iloc[-1]

    if crossed and held:
        return True, f"Crossed above VWAP within last {VWAP_CROSS_LOOKBACK} candles and held for {VWAP_HOLD_CANDLES}+ candles."
    if not crossed:
        return False, f"No VWAP cross within the last {VWAP_CROSS_LOOKBACK} candles (close {last['close']:.2f} vs VWAP {last['vwap']:.2f})."
    return False, f"Crossed VWAP but hasn't held for {VWAP_HOLD_CANDLES} full candles yet — looks like a fakeout so far."


def _check_atr_breakout(df: pd.DataFrame) -> tuple[bool, str]:
    last = df.iloc[-1]
    if pd.isna(last["rolling_high_20"]) or pd.isna(last["atr14"]):
        return False, "Not enough history yet to compute the 20-period breakout reference."

    breakout_level = last["rolling_high_20"] + (ATR_BREAKOUT_MULTIPLE * last["atr14"])
    margin_atr = (last["close"] - last["rolling_high_20"]) / last["atr14"] if last["atr14"] else 0

    if last["close"] > breakout_level:
        return True, f"Close {last['close']:.2f} broke above prior 20-period high {last['rolling_high_20']:.2f} by {margin_atr:.2f}x ATR (needed {ATR_BREAKOUT_MULTIPLE}x)."
    return False, f"Close {last['close']:.2f} is only {margin_atr:.2f}x ATR above the prior high {last['rolling_high_20']:.2f} — needed {ATR_BREAKOUT_MULTIPLE}x."


def _check_volume_spike(df: pd.DataFrame) -> tuple[bool, str, float]:
    last = df.iloc[-1]
    if pd.isna(last["avg_vol_10"]) or last["avg_vol_10"] == 0:
        return False, "Not enough history yet to compute average volume.", 0.0

    ratio = last["volume"] / last["avg_vol_10"]
    if ratio >= VOLUME_SPIKE_MULTIPLE:
        return True, f"Volume ratio {ratio:.2f}x meets the {VOLUME_SPIKE_MULTIPLE}x relative-volume bar.", round(ratio, 2)
    return False, f"Volume ratio {ratio:.2f}x is below the {VOLUME_SPIKE_MULTIPLE}x relative-volume bar.", round(ratio, 2)


def _check_rsi_momentum_reversal(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 6:
        return False, "Not enough candles yet to evaluate an RSI reversal."

    recent = df.tail(6)
    dip_mask = recent["rsi14"].iloc[:-1] < RSI_DIP_THRESHOLD
    dipped = bool(dip_mask.any())
    min_recent_rsi = recent["rsi14"].iloc[:-1].min()

    prev_rsi, curr_rsi = df.iloc[-2]["rsi14"], df.iloc[-1]["rsi14"]
    if pd.isna(prev_rsi) or pd.isna(curr_rsi):
        return False, "RSI not yet available for the last two candles."

    crossed_up = prev_rsi < RSI_REVERSAL_THRESHOLD <= curr_rsi

    if dipped and crossed_up:
        return True, f"RSI dipped to {min_recent_rsi:.1f} (below {RSI_DIP_THRESHOLD}) then reversed up through {RSI_REVERSAL_THRESHOLD} — now {curr_rsi:.1f}."
    if not dipped:
        return False, f"RSI hasn't dipped below {RSI_DIP_THRESHOLD} recently (recent low: {min_recent_rsi:.1f}) — no reversal setup, just drift."
    return False, f"RSI dipped to {min_recent_rsi:.1f} but hasn't crossed back up through {RSI_REVERSAL_THRESHOLD} yet (currently {curr_rsi:.1f})."


def _check_sector_correlation(symbol: str, sector_15m_raw: dict | None) -> tuple[bool, str, str]:
    sector_proxy = get_sector_proxy(symbol)
    if symbol == sector_proxy:
        return True, "Symbol IS the broad-market ETF proxy — trivially aligned with itself.", sector_proxy

    sector_df = chart_result_to_df(sector_15m_raw.get("raw") if sector_15m_raw else None)
    if sector_df is None or len(sector_df) < 25:
        return False, f"Sector proxy {sector_proxy} data unavailable — can't confirm sector participation.", sector_proxy

    sector_df = add_indicators(sector_df)
    sector_last = sector_df.iloc[-1]
    if pd.isna(sector_last["ema20"]):
        return False, f"Sector proxy {sector_proxy} EMA not yet available.", sector_proxy

    if sector_last["close"] > sector_last["ema20"]:
        return True, f"Sector proxy {sector_proxy} is also above its 15m 20-EMA — move is sector-wide, not isolated.", sector_proxy
    return False, f"Sector proxy {sector_proxy} is BELOW its 15m 20-EMA — this looks like an isolated single-stock move.", sector_proxy


def _tier_for_count(count: int) -> str:
    if count >= INSTITUTIONAL_THRESHOLD:
        return "INSTITUTIONAL"
    if count >= DEVELOPING_THRESHOLD:
        return "DEVELOPING"
    return "WEAK"


async def evaluate_symbol(symbol: str, asset_type: str, df_15m_raw: dict | None,
                           market_regime: str, sector_15m_raw: dict | None,
                           as_of: datetime | None = None,
                           market_regime_detail: dict | None = None,
                           nifty_15m_raw: dict | None = None) -> SymbolDiagnostics:
    """
    Runs ALL 6 rules for one symbol and returns a full diagnostic breakdown
    — every rule's pass/fail and the exact numbers involved — regardless of
    whether earlier rules failed. Only when all 6 pass does the result also
    carry a `qualified_signal` dict with computed entry/target/SL.

    `as_of`: the timestamp to evaluate the time-window rule against. Live
    scanning omits this (defaults to real current time, unchanged behavior).
    The backtest engine passes the historical timestamp being simulated —
    this is the ONLY real-time dependency in the entire rule-evaluation
    path, which is what makes reusing this exact function for backtesting
    safe: every other check operates purely on the `df_15m_raw` /
    `sector_15m_raw` data handed to it, never on the wall clock.

    `market_regime_detail`: OPTIONAL (Phase 2). The richer regime
    classification (TRENDING_UP/DOWN, SIDEWAYS, HIGH_VOLATILITY) from
    market_analysis.py, computed once per scan from Nifty data — same
    market-wide scope as `market_regime` itself, just a finer-grained
    read. Omitting this parameter is fully safe: it only feeds the
    diagnostic confidence breakdown's Market sub-score, never any of the
    6 gating rules, so existing callers that don't pass it are unaffected
    apart from that one diagnostic field falling back to a neutral default.

    `nifty_15m_raw`: OPTIONAL (Phase 3). Nifty's own raw 15m data, used to
    compute relative strength (stock vs Nifty, sector-proxy vs Nifty) —
    diagnostic-only, same safety guarantee as market_regime_detail above.
    Costs nothing extra to provide since scanner.py already fetches this
    for the existing gatekeeper check.
    """
    diag = SymbolDiagnostics(symbol=symbol, asset_type=asset_type, data_available=True)

    df = chart_result_to_df(df_15m_raw.get("raw") if df_15m_raw else None)
    if df is None or len(df) < 25:
        diag.data_available = False
        diag.tier = "NO_DATA"
        diag.rule_results = [
            RuleResult("insufficient_data", "Data Availability", False,
                       "Not enough recent candle data to evaluate any rule for this symbol yet.")
        ]
        return diag

    df = add_indicators(df)
    last = df.iloc[-1]

    results: list[RuleResult] = []

    gate_passed, gate_detail = _check_nifty_gatekeeper(market_regime)
    results.append(RuleResult("nifty_trend_gatekeeper", "Nifty Trend Gatekeeper", gate_passed, gate_detail))

    vwap_passed, vwap_detail = _check_vwap_cross_and_hold(df)
    results.append(RuleResult("vwap_cross_and_hold", "VWAP Cross & Hold", vwap_passed, vwap_detail))

    breakout_passed, breakout_detail = _check_atr_breakout(df)
    results.append(RuleResult("atr_breakout", "ATR Breakout", breakout_passed, breakout_detail))

    volume_passed, volume_detail, volume_ratio = _check_volume_spike(df)
    results.append(RuleResult("volume_spike", "Volume Spike", volume_passed, volume_detail))

    rsi_passed, rsi_detail = _check_rsi_momentum_reversal(df)
    results.append(RuleResult("rsi_momentum_reversal", "RSI Momentum Reversal", rsi_passed, rsi_detail))

    sector_passed, sector_detail, sector_proxy = _check_sector_correlation(symbol, sector_15m_raw)
    results.append(RuleResult("sector_etf_correlation", "Sector/ETF Correlation", sector_passed, sector_detail))

    diag.rule_results = results
    diag.rules_passed_count = sum(1 for r in results if r.passed)
    diag.tier = _tier_for_count(diag.rules_passed_count)

    effective_time = as_of or datetime.now(IST)
    diag.in_time_window = check_time_window(effective_time)
    diag.time_window_detail = (
        "Within the 09:15-15:15 IST signal window." if diag.in_time_window
        else "Outside the 09:15-15:15 IST signal window — rules can still be evaluated, "
             "but no new trade signal will be issued until the window reopens."
    )

    # --- Phase 2: diagnostic-only additions, computed for EVERY symbol
    # regardless of tier — none of this can change rules_passed_count,
    # tier, or qualification. Wrapped defensively so a Phase 2 computation
    # issue can never take down the core (already-proven) rule evaluation
    # above it.
    diag.market_regime_detail = market_regime_detail
    try:
        pivots = compute_pivot_levels(df, as_of=effective_time)
        diag.pivot_levels = pivots
        diag.pivot_description = describe_price_vs_pivots(float(last["close"]), pivots)
    except Exception as exc:
        diag.pivot_description = f"Pivot calculation unavailable: {exc}"

    atr_for_breakout = float(last["atr14"]) if not pd.isna(last["atr14"]) else None
    breakout_margin_atr_diag = (
        (float(last["close"]) - last["rolling_high_20"]) / atr_for_breakout
        if atr_for_breakout and not pd.isna(last["rolling_high_20"]) else 0.0
    )
    try:
        diag.confidence_breakdown = compute_confidence(
            breakout_margin_atr=breakout_margin_atr_diag,
            volume_ratio=volume_ratio,
            rsi_value=float(last["rsi14"]) if not pd.isna(last["rsi14"]) else None,
            vwap_passed=vwap_passed,
            close=float(last["close"]),
            vwap_value=float(last["vwap"]) if not pd.isna(last["vwap"]) else None,
            market_regime_detail=market_regime_detail,
        )
    except Exception as exc:
        diag.confidence_breakdown = None
        diag.pivot_description = diag.pivot_description or f"Confidence scoring unavailable: {exc}"
    # --- end Phase 2 additions ---

    # --- Phase 3: relative strength vs Nifty, diagnostic-only. Costs
    # nothing extra (Nifty data is already in hand), wrapped defensively
    # for the same reason as the Phase 2 block above.
    try:
        nifty_df = chart_result_to_df(nifty_15m_raw.get("raw") if nifty_15m_raw else None)
        if nifty_df is not None and len(nifty_df) >= 21:
            diag.relative_strength = compute_relative_strength(df, nifty_df, label=symbol.replace(".NS", ""))

            sector_df = chart_result_to_df(sector_15m_raw.get("raw") if sector_15m_raw else None)
            if sector_df is not None and len(sector_df) >= 21:
                diag.sector_relative_strength = compute_relative_strength(
                    sector_df, nifty_df, label=f"sector proxy ({sector_proxy.replace('.NS', '')})"
                )
    except Exception:
        pass  # relative strength is enrichment only — never let it affect the core result
    # --- end Phase 3 relative strength ---

    if diag.tier in ("INSTITUTIONAL", "DEVELOPING") and diag.in_time_window:
        entry_price = float(last["close"])
        atr_value = float(last["atr14"]) if not pd.isna(last["atr14"]) else None
        if atr_value and atr_value > 0:
            stop_loss, target = compute_atr_targets(entry_price, atr_value, ATR_SL_MULTIPLE, ATR_TARGET_MULTIPLE)

            # strength_score keeps its original name and 0-100 range for
            # backward compatibility with everything that already reads it
            # (dashboard cards, sort order, the DB column) — the VALUE now
            # comes from the Phase 2 weighted confidence matrix instead of
            # the old flat heuristic, rather than maintaining two scores.
            confidence = diag.confidence_breakdown or compute_confidence(
                breakout_margin_atr=breakout_margin_atr_diag, volume_ratio=volume_ratio,
                rsi_value=float(last["rsi14"]) if not pd.isna(last["rsi14"]) else None,
                vwap_passed=vwap_passed, close=entry_price,
                vwap_value=float(last["vwap"]) if not pd.isna(last["vwap"]) else None,
                market_regime_detail=market_regime_detail,
            )
            strength = confidence["confidence_pct"]
            breakdown = confidence["breakdown"]

            signal_payload = {
                "symbol": symbol,
                "asset_type": asset_type,
                "signal_type": "BUY",
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target": target,
                "atr_value": round(atr_value, 2),
                "rsi_value": round(float(last["rsi14"]), 2),
                "vwap_value": round(float(last["vwap"]), 2) if not pd.isna(last["vwap"]) else None,
                "volume_ratio": volume_ratio,
                "rules_passed": [r.rule_id for r in results if r.passed],
                "sector_proxy": sector_proxy,
                "market_regime": market_regime,
                "strength_score": strength,
                "tier": diag.tier,
                "rules_passed_count": diag.rules_passed_count,
                # Phase 2 additions to the payload — new keys only, nothing
                # existing removed or renamed.
                "trend_score": breakdown["trend"],
                "volume_score": breakdown["volume"],
                "momentum_score": breakdown["momentum"],
                "vwap_score": breakdown["vwap"],
                "market_score": breakdown["market"],
                "market_regime_detail": (market_regime_detail or {}).get("regime"),
            }

            if diag.tier == "INSTITUTIONAL":
                # Only institutional (6/6) signals are auto-persisted and
                # broadcast by the scanner — see services/scanner.py.
                diag.qualified_signal = signal_payload
            else:
                # Developing (4-5/6) signals are shown as lower-confidence
                # cards in the feed but NOT auto-persisted — they're only
                # written to signal_history if someone explicitly opens a
                # paper position on one (see /portfolio/positions/open-candidate).
                diag.developing_signal = signal_payload

    return diag
