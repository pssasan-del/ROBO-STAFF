# ROBO STAFF V13 — Diagnostics / Entry Backtest

Production signal rules are intentionally unchanged.

Added:
- persistent aggregate performance statistics in PostgreSQL when `DATABASE_URL` is configured (file fallback otherwise)
- OPTION BUY / OPTION SELL W/L split
- BTC / ETH / GOLD W/L split
- AI CONFIRM / REJECT / WAIT / NO-AI W/L split
- time-to-SL buckets: under 5m, 5–15m, over 15m
- bounded 2-hour post-SL watch; counts whether original T1/T2 is later reached
- Settings → `🧪 Entry Backtest` inline button
- read-only Delta 5m entry-timing diagnostic comparing current bar, +1, +2 and +3 bars

Important limitation: the Entry Backtest is an underlying 5m diagnostic using ATR-normalized risk. It is not represented as an exact historical option-premium backtest because this package does not contain a verified historical option-candle source. Live option signals, 12% premium SL, T1/T2/T3, Python scoring and non-blocking AI confirmation remain unchanged.

Memory controls:
- live unresolved signals capped at 50 (existing)
- post-SL watches capped at 50 and expire after 2 hours
- only aggregate counters are persisted; no candle history, AI prompts or order books are stored
