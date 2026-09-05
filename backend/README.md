# NEO Signal Terminal — Stage 4

Personal-use Kotak Neo trading-terminal backend foundation.

## Included

- Kotak Neo TOTP + MPIN session flow
- Market WebSocket + order/position feed with reconnect/resubscribe
- Live tick cache and stale-feed health status
- 1m / 3m / 5m / 15m candle builder from broker-delivered ticks
- Instrument search cache and exact option resolution
- ATM-neighbour option scan with broker quote enrichment
- Deterministic option-quality ranking: premium, distance, spread, volume/OI availability
- Deterministic baseline signal engine (minimum R:R 1:1.85)
- Signal lifecycle: ACTIVE → ENTRY → T1/T2 / SL / EXPIRED
- Live tick-driven lifecycle state broadcasts over `/ws/ticks`
- Risk gate: max qty/order value/open positions/daily loss/slippage/duplicate protection
- Portfolio positions, holdings, limits and order-book read endpoints
- Live order placement remains intentionally locked

## Important live-data note

The engine forwards broker-delivered WebSocket updates and does not invent missing ticks. This should not be represented as exchange raw archival TBT unless the broker/exchange feed explicitly guarantees that level of delivery.

## Main Stage-4 endpoints

- `POST /options/scan` — search strikes around ATM, quote and rank candidates (requires broker login)
- `POST /options/rank` — offline/test ranking of supplied option records
- `POST /signals/evaluate` — deterministic underlying signal evaluation
- `POST /signals/lifecycle` — create tracked signal
- `POST /signals/lifecycle/{id}/price` — test/manual lifecycle update
- `GET /signals/lifecycle` — current tracked signals
- `WS /ws/ticks` — market, candles, orders and lifecycle state-change events

## Development status

Stage 4 is an engine/backend milestone, not the finished mobile app. Real broker credentials and a live-market session are required later for final feed/contract-field verification. Order placement remains locked until replay/paper tests and execution safety checks are completed.

## Stage 5 — guarded live execution

Stage 5 adds a two-gate execution flow. Live submission is only possible when the risk gate is enabled and the execution engine is separately armed. The mobile swipe flow must first create an `/execution/intent`, display the returned order summary, then submit the one-use short-lived confirmation token to `/execution/{intent_id}/confirm`. Direct `/orders/place` is deliberately disabled.

Safety behavior:
- risk preflight runs when an intent is created and runs again immediately before broker submission;
- live-price movement beyond the configured slippage threshold blocks confirmation;
- confirmation tokens are one-use and expire quickly;
- a submitted intent cannot be submitted again;
- SDK `tag` correlation is attached as `NST-<intent_id>`;
- the Kotak order feed reconciles broker states into ACKNOWLEDGED / OPEN / PARTIAL / FILLED / REJECTED / CANCELLED;
- `/execution/kill-switch` immediately disarms execution, disables the trading risk gate and invalidates pending confirmations;
- the kill switch intentionally does **not** create unreviewed exit orders. Explicit exit/basket close semantics belong to the position-management milestone.

Important: keep execution disarmed until a real Kotak login, live-feed verification and a minimal-quantity controlled-market test have been completed by the account owner.

## Stage 6 — Position management and exits

- Normalises Kotak REST/position-feed payloads and keeps raw execution quantity units.
- Calculates live MTM/P&L using the formula documented by the bundled Kotak SDK.
- `/portfolio/positions/live` exposes normalized live positions and aggregate day MTM.
- `/portfolio/exit-intent` creates a normal one-time confirmation intent for partial/full exits.
- `/portfolio/exit-all` requires the literal confirmation `EXIT ALL` plus both execution safety gates.
- Exit plans support SL/T1/T2 monitoring. `auto_exit=false` is the safe default; automatic exit is explicit opt-in.
- Market ticks mark matching positions and broadcast MTM/exit-plan events over `/ws/ticks`.

For a restarted process call `/portfolio/positions/refresh` after login; the REST positions snapshot is treated as authoritative and live WebSocket updates continue from there.

## Stage 7 mobile client
A Flutter light-theme client is included at `../mobile`. It targets the guarded execution and portfolio APIs in this backend.
