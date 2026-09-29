# ROBO STAFF — V4 Precision Scalp

Version: `FRESH_V4.0_PRECISION_SCALP_2026-09-29`

## Why V4 exists
V3.6/V3.7 research showed a high fast-SL rate and at least one 100/100 bearish alert while the 1h/15m context was bullish. V4 fixes that class of failure instead of merely changing thresholds.

## Core idea
V4 is a trend-continuation pullback/retest system, not a raw breakout chaser.

1. 1m and 5m must agree on direction.
2. 15m alignment is a hard requirement.
3. Strongly opposite 1h trend is a hard veto.
4. Opposite 5m structure is a hard veto.
5. 5m ADX >= 14, DI ratio >= 1.08.
6. Volume cannot be weak on both 1m and 5m.
7. 1m RSI and Williams %R must be in a reset/continuation zone, not exhaustion.
8. Price cannot be overextended from 5m EMA9/VWAP.
9. There must be >= 0.60 ATR room to the next major obstacle.
10. Entry must be a pullback reclaim, retest confirmation, controlled breakout-retest, or strong trend resume.

## Option expression
For this clean epoch V4 emits **OPTION BUY only** so directional edge can be measured without mixing two very different payoff structures.

- Bullish -> Call buy.
- Bearish -> Put buy.
- Contract search: ATM, 1 OTM, 2 OTM.
- Preferred absolute delta: 0.28-0.62.
- Rank >= 72.
- Dust, wide-spread and near-expiry contracts are rejected.

## Scalp risk ladder
Premium risk band is dynamic and must clear spread/tick noise.

- Normal T1 = 1.20R
- T2 = 1.85R
- T3 = 2.50R
- Strong-extension T1 = 1.30R

This differs from the old 1.85R-first-target design because the purpose of V4 is a genuine scalp hit-rate study. It does not imply or guarantee a 90% win rate.

## Research
Fresh tables only:

- `delta_signal_stats_v40`
- `delta_research_signals_v40`

Promotion is evidence-based. Minimum 50 resolved signals, preferred 100, across at least five calendar days. Research may suggest A/B tests but never edits live rules automatically.

## Safety
100% SIGNAL ONLY. No place/modify/cancel/square-off logic and no private Delta trading credentials.
