# NEO Signal Terminal Integrated V3

This package is based on the user's current Oracle backend plus the mobile source.

Implemented in V3:
- Robotic neon/glass design system retained and darkened consistently across reusable UI widgets.
- 90-stock scanner remains connected to the real `/scanner/start`, `/scanner/stop`, `/scanner/status` backend endpoints.
- Trade tab upgraded into a three-mode Trade Desk:
  - Manual: Kotak instrument search, live quote lookup, BUY/SELL, MIS/CNC/NRML, MKT/L/SL/SL-M, quantity, limit/trigger, execution intent and one-time confirmation.
  - Options: existing option quality scan + live premium selection + execution intent/confirm flow.
  - Orders: live broker order list, refresh, modify and cancel actions using `/orders/modify` and `/orders/cancel`.
- Confirmation dialog no longer hardcodes BUY label; it reflects the execution side.
- UTF-8 source sanity checked; no NUL-byte corruption.
- Oracle backend source compiles and its test suite passes: 20 tests.

Validation boundary:
- Flutter SDK is not installed in the build container used to prepare this package, so `flutter analyze`/APK build is NOT claimed as passed here.
- Run GitHub Actions or local Flutter analyze before installing the APK.
