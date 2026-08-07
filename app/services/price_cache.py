*** Begin Patch
*** Update File: app/services/price_cache.py
@@
 async def clear_cache(symbol: str | None = None, interval: str | None = None) -> int:
     """Deletes cached candles, optionally scoped to a symbol/interval. Returns rows deleted."""
     async with AsyncSessionLocal() as session:
         query = delete(PriceCache)
         if symbol:
             query = query.where(PriceCache.symbol == symbol)
         if interval:
             query = query.where(PriceCache.interval == interval)
         result = await session.execute(query)
         await session.commit()
         return result.rowcount
+
+
+async def validate_cached_candles(symbol: str, interval: str,
+                                  start: datetime | None = None, end: datetime | None = None) -> dict:
+    """
+    Non-destructive validation of cached 15-minute candles for `symbol`.
+
+    Returns a dict describing counts, warnings, and errors. Keys:
+      - valid: bool
+      - symbol, interval
+      - candle_count
+      - duplicate_count
+      - gap_count
+      - invalid_ohlc_count
+      - negative_volume_count
+      - timezone_errors
+      - coverage_start
+      - coverage_end
+      - warnings: list[str]
+      - errors: list[str]
+
+    This function does NOT modify any data.
+    """
+    candles = await get_cached_candles(symbol, interval, start=start, end=end)
+
+    result = {
+        "valid": True,
+        "symbol": symbol,
+        "interval": interval,
+        "candle_count": 0,
+        "duplicate_count": 0,
+        "gap_count": 0,
+        "invalid_ohlc_count": 0,
+        "negative_volume_count": 0,
+        "timezone_errors": 0,
+        "coverage_start": None,
+        "coverage_end": None,
+        "warnings": [],
+        "errors": [],
+    }
+
+    if not candles:
+        result["valid"] = False
+        result["errors"].append("empty dataset")
+        return result
+
+    # Extract timestamps and basic fields
+    timestamps = [c.candle_timestamp for c in candles]
+    opens = [c.open for c in candles]
+    highs = [c.high for c in candles]
+    lows = [c.low for c in candles]
+    closes = [c.close for c in candles]
+    volumes = [getattr(c, "volume", 0) for c in candles]
+
+    result["candle_count"] = len(candles)
+    result["coverage_start"] = min(timestamps)
+    result["coverage_end"] = max(timestamps)
+
+    # Duplicates
+    if len(set(timestamps)) != len(timestamps):
+        result["duplicate_count"] = len(timestamps) - len(set(timestamps))
+        result["valid"] = False
+        result["errors"].append(f"{result['duplicate_count']} duplicate timestamps")
+
+    # Non-monotonic (timestamps must strictly increase)
+    non_mono = any(timestamps[i] >= timestamps[i + 1] for i in range(len(timestamps) - 1))
+    if non_mono:
+        result["valid"] = False
+        result["errors"].append("non-monotonic timestamps detected")
+
+    # Timezone errors (expect tz-aware datetimes)
+    tz_errors = sum(1 for ts in timestamps if getattr(ts, "tzinfo", None) is None)
+    if tz_errors:
+        result["timezone_errors"] = tz_errors
+        result["valid"] = False
+        result["errors"].append(f"{tz_errors} timestamps missing tzinfo or invalid timezone")
+
+    # OHLC validity and negative volume
+    invalid_ohlc = 0
+    neg_vol = 0
+    for o, h, l, c, v in zip(opens, highs, lows, closes, volumes):
+        if not (h >= o and h >= c and l <= o and l <= c and h >= l):
+            invalid_ohlc += 1
+        if v is None:
+            # treat missing volume as zero — warn but not fatal
+            result["warnings"].append("missing volume values treated as zero")
+        elif v < 0:
+            neg_vol += 1
+
+    if invalid_ohlc:
+        result["invalid_ohlc_count"] = invalid_ohlc
+        result["valid"] = False
+        result["errors"].append(f"{invalid_ohlc} candles with invalid OHLC relationships")
+
+    if neg_vol:
+        result["negative_volume_count"] = neg_vol
+        result["valid"] = False
+        result["errors"].append(f"{neg_vol} candles with negative volume")
+
+    # Gaps: expected 15-minute cadence. Count gaps where delta > 1.5 * 15min
+    gap_count = 0
+    fifteen = timedelta(minutes=15)
+    for i in range(len(timestamps) - 1):
+        delta = timestamps[i + 1] - timestamps[i]
+        if delta > fifteen * 1.5:
+            gap_count += int(delta / fifteen) - 1
+
+    if gap_count:
+        result["gap_count"] = gap_count
+        result["warnings"].append(f"{gap_count} missing 15m candles detected (gaps)")
+
+    # Coverage check if start/end were requested
+    if start and result["coverage_start"] > start:
+        result["valid"] = False
+        result["errors"].append("coverage start is after requested start")
+    if end and result["coverage_end"] < end:
+        result["valid"] = False
+        result["errors"].append("coverage end is before requested end")
+
+    return result
*** End Patch
