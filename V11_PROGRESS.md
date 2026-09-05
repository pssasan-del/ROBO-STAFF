# V11 — Compact Trading Terminal UI Rebuild

Based on the 2026-09-05 installed-app recording review.

## Changed
- Removed oversized Home AI/account presentation from the primary viewport.
- Home rebuilt as a compact broker terminal: MARKET PULSE, Day P&L, Positions, Scanner readiness, Kotak/feed/execution state, latest signal.
- NIFTY / BANKNIFTY / SENSEX are forced into one responsive row (no horizontal scroll).
- Visual system moved from green/teal-dominant to deep navy + electric cyan/blue. Green/red are reserved primarily for semantic market/trading states.
- Manual Trade header tightened to ORDER TERMINAL.
- Generic green SEARCH KOTAK action renamed FIND INSTRUMENT and inherits cyan primary theme.
- Existing Kotak execution/risk confirmation logic, options, orders, portfolio, scanner, and signals retained.
- Scanner backend source still asserts exactly 45 symbols in Group A and 45 in Group B.

## Validation available in this environment
- Dart UTF-8/NUL sanity: PASS
- Structural delimiter count sanity: PASS
- Python backend compile: PASS
- Backend tests: 20/20 PASS

## Not claimed
Flutter SDK is not available in this environment, so this package is not claimed as an APK-build pass. GitHub Actions remains the compile/build gate.
