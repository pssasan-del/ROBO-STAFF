# ROBO STAFF — Delta Signal Engine Upgrade

## Implemented
- Signal-only Delta engine; no private trading credentials and no order methods.
- Always-on background scanner for configured Delta symbols.
- Multi-timeframe 1D / 1H / 15M / 5M / 1M analysis.
- EMA 5/9/20, VWAP, RSI, Williams %R, ATR, ADX/+DI/-DI, relative volume, Fibonacci pivots and basic HH/HL/LH/LL structure context.
- 1-minute trigger cannot override higher-timeframe direction.
- Choppy and overextended filters.
- Delta options scan around ~3 OTM strikes, with option BUY and option SELL signal families.
- Option liquidity screening using available spread/volume/OI data.
- Existing Gemini -> Groq AI router reused as optional, non-blocking second opinion.
- AI outage/quota/timeout/malformed response does not suppress a Python-valid alert; alert reports NO AI CONFIRMATION.
- Compact Telegram keyboard: Latest, Daily, Weekly, Data, System, Settings, Home.
- Daily/weekly aggregate performance counters with bounded 35-day retention; no candle/order-book/AI prompt history persisted by this module.
- Candle fetch limit bounded by DELTA_CANDLE_LIMIT (hard capped at 300); unresolved in-RAM signal monitor hard capped at 50.
- Existing custom strategy engine and legacy text commands preserved as fallback.

## Safety / scope
- NO Delta order placement, modification, cancellation or position closing is implemented in this module.
- This build is for signals/alerts only.
- Render sleep cannot be bypassed by application code if the selected Render plan enforces sleeping. The app retains health/heartbeat/reconnect behavior for recovery while the service is running.

## Validation performed in build environment
- `python -m py_compile` passes for the modified/new runtime modules.
- Runtime imports for `app`, Telegram keyboard, performance store and Delta auto engine pass.
- Compact keyboard structure and empty aggregate report were instantiated successfully.
- Live Delta network smoke test could NOT be completed in the build environment because outbound DNS resolution was unavailable. This must be runtime-tested on Render/Oracle.
- Existing repository `test_safety.py` has a pre-existing self-matching test defect: it searches all root Python files for the literal `place_order`, including its own forbidden-string list, so that test fails even without trading code. The broader repository also contains legacy/current test-layout conflicts noted during audit; this upgrade does not claim the full legacy suite passes.

## Important deployment variables
See `env.example`, especially DELTA_AUTO_SIGNAL_ENGINE, DELTA_SIGNAL_SCAN_SECONDS, DELTA_CANDLE_LIMIT, DELTA_MIN_SCORE, DELTA_AI_CONFIRMATION and DELTA_STATS_PATH.
