# NEO Signal Terminal Integrated V4

Added in V4:
- Scanner readiness diagnostics based on persisted closed 5-minute history.
- Scanner status now exposes ready/warming counts and per-symbol history depth; minimum strict history = 24 closed 5M candles.
- Signal lifecycle now tracks T3 and exposes aggregate stats.
- `/signals/stats` endpoint and signal stats included in `/app/bootstrap`.
- Home robotic HUD now shows scanner readiness and latest qualified signal.
- Signals screen now shows live/win/loss/average-score metrics and richer signal details (T3, RR, score, RSI, Williams %R, timeframe, reason).
- Scanner screen now shows resolved/ready/warming/failed live metrics.

Validation boundary:
- Backend Python compile + tests are run during packaging.
- Flutter SDK is not installed in this environment, so Flutter analyze/APK build is not claimed.
