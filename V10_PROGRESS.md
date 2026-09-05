# NEO Signal Terminal V10 — Release Candidate Gate

V10 does not add new trading behavior. It packages the integrated V9 source with safer deployment helpers so the next proof point is an actual Flutter build.

## Included
- Robotic KING BRO / NEO CORE UI
- NIFTY / BANK NIFTY / SENSEX HUD
- 90-stock scanner: Group A 45 / Group B 45 / Stop
- Signals with Entry, SL, T1/T2/T3, R:R, score and indicators
- Signal-to-trade protected execution flow
- Manual equity/derivative trade ticket
- Option scan/trade flow
- Orders and portfolio controls
- Partial/full exits and safety gates
- GitHub Actions Flutter analyze + release APK workflow
- Windows GitHub deployment helper
- Oracle backend deployment helper with automatic backup and backend tests

## Validation performed in this environment
- Python backend compile: PASS
- Backend pytest: 20/20 PASS
- Flutter executable: NOT AVAILABLE in this environment
- Therefore APK build is NOT claimed as passed until GitHub Actions completes successfully.
