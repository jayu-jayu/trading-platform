*** Begin Patch
*** Update File: README.md
@@
 ### Backtest API (new)
@@
 The backtest engine reuses `evaluate_symbol()` directly (via the new
 `as_of` parameter) — it contains no trading logic of its own, only
 simulation mechanics. It reads exclusively from the price cache; populate
 that first for whatever symbols/range you want to test.
@@
 ```
 POST /api/backtest/cache/populate   { symbols, interval, rng }       — fetch & cache historical candles
 POST /api/backtest/run              { symbols, start_date, end_date, interval, label }  — run a walk-forward backtest
 GET  /api/backtest/runs             — list recent runs
 GET  /api/backtest/runs/{id}        — full run detail including every simulated trade
 ```
+
+Backtest execution semantics (entry/exit)
+- The backtester evaluates signals only after the signal candle has closed.
+- ENTRY MODE (canonical default): entry_at_signal_candle_close.
+  - entry_price is set to the signal-candle close.
+  - exit simulation begins from the immediately following candle (the backtester does not consider the signal candle itself as a candidate exit).
+- This is a modeling assumption for deterministic backtests and does not guarantee a real-world fill price — live execution may differ.
+- P&L reported is per-unit price movement. No slippage, commissions, or fees are modeled in Phase 1.1.
*** End Patch
