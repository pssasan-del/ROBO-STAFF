# ROBO STAFF Fresh V3.1 hotfix

Purpose: stop fast false/weak SL clusters seen immediately after Fresh V3 launch without enabling order execution.

Changes:
- Use the latest completed 5m EMA5/EMA9 crossover only; ignore a crossover forming inside the live 5m candle.
- Require 5m ADX >= 22, RVOL >= 0.80, DI alignment and HH/HL or LH/LL structure.
- Require Daily and 5m Fibonacci Pivot location to agree with direction.
- Reject 15m/1h opposition.
- Require Python score >= 80.
- Tighten option execution quality to <=4% spread, meaningful premium, and SL/T1 room beyond spread/tick noise.
- Start clean research/stat tables: delta_research_signals_v31 and delta_signal_stats_v31.
- Preserve executable paper pricing: BUY ask->bid, SELL bid->ask.
- Preserve RR 1:1.85, AI non-blocking, market replay, recovery tracking, and SIGNAL ONLY / NO ORDER EXECUTION.
