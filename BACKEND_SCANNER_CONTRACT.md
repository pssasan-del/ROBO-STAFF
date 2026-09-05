# NEO Signal — 90-stock scanner backend contract

The uploaded source archive contains the Flutter mobile project only; the Oracle FastAPI backend source is not included. The final scanner requires these server routes to be implemented in the existing Oracle backend.

## Required routes

- `POST /scanner/start` body `{ "group": "A" }` or `{ "group": "B" }`
  - Group A: 45 symbols
  - Group B: 45 symbols
  - only one group active at a time
- `POST /scanner/stop` body `{}`
- `GET /scanner/status`
  - returns active group, running state, scanned count, qualified count, last scan timestamp
- `GET /scanner/universe`
  - returns the two fixed 45-symbol groups

## Signal rules retained from project requirements

- Closed-candle evaluation, no invented candles
- 5-minute core setup; 1m/15m confirmation can be added when sufficient history exists
- minimum R:R 1.85
- strict quality filtering; do not force a daily quota
- signal output: symbol, side, entry, stop, T1, T2, optional T3, score, reason, timestamp
- scanner must be manually started from the app and must stop immediately on Stop

## Important

Do not claim the 45/45 buttons control the Oracle scanner until these routes exist and have been tested against the live Kotak Neo session.
