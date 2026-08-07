*** Begin Patch
*** Update File: app/services/backtest_engine.py
@@
-from app.services.price_cache import get_cached_candles
+from app.services.price_cache import get_cached_candles, validate_cached_candles
+import logging
+logger = logging.getLogger(__name__)
@@
-            candles = _localize(await get_cached_candles(symbol, interval, start_date, end_date))
+            # Preflight data-quality validation for this symbol
+            validation = await validate_cached_candles(symbol, interval, start_date, end_date)
+            if not validation.get("valid", False):
+                # Critical errors: skip this symbol for this run and log details.
+                logger.warning("Skipping backtest for %s due to data validation errors: %s", symbol, validation["errors"])
+                continue
+
+            candles = _localize(await get_cached_candles(symbol, interval, start_date, end_date))
*** End Patch
