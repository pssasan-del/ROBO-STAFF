# V6 Progress

## Added
- Portfolio HUD metrics: open, tracked and marked positions.
- Safer per-position exit workflow with 25%, 50%, 100% presets and custom quantity.
- Lot-size-aware preset rounding for derivative positions.
- Exit still goes through `/portfolio/exit-intent` and the one-time execution confirmation flow.
- Explicit `EXIT ALL POSITIONS` control with typed `EXIT ALL` confirmation.
- Existing SL/target exit-plan controls retained.

## Validation
- Backend Python compile check: PASS.
- Backend regression tests: 20/20 PASS.
- UTF-8 source read: PASS.
- Flutter/Dart SDK is not installed in the packaging environment, so Flutter analyzer/APK compile is still pending external validation.

## Safety
- Exit-all does not bypass backend gates: Kotak login, risk trading gate and execution arm are required by the backend.
- Runtime `.env` is not included.
