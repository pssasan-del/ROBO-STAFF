# MASTER MIND BTC 5m Scalping Alert

Separate signal-only research/alert module. Existing ROBO STAFF FRESH_V3 strategy, cooldowns, statistics and execution safety are not modified by this module.

Locked indicator stack:
- EMA 9 / EMA 95
- McGinley Dynamic 14
- Fibonacci Pivots P/S1/S2/S3/R1/R2/R3
- Momentum(10, close)
- Volume vs SMA20

Setups:
1. Breakout: trend alignment + pivot break + directional candle + volume confirmation + momentum confirmation.
2. Pullback: established EMA95 trend + rejection from EMA9/McGinley/Pivot + momentum curl.
3. Exhaustion Reversal: momentum extreme (>+200 or <-150) + pivot rejection wick + volume spike + hook toward zero.
4. No alert for chop/wait conditions.

Telegram header: `🔴🚨 MASTER MIND SIGNAL ALERT 🚨🔴`

This module never places, modifies, cancels or closes orders.
