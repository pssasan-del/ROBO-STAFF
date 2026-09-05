# V5 Progress

- Added protected Signal -> Trade flow.
- Signal details now expose TRADE THIS SIGNAL only when a broker trading_symbol is present.
- Signal trade ticket prefills side and reference price from the signal, asks quantity/product, then calls /execution/intent.
- Existing risk gate, execution arm and one-time confirmation remain mandatory before broker submission.
- Signals without an exact broker trading_symbol cannot be executed directly; UI directs the user to Manual Trade to select the exact Kotak instrument.
- Preserved Manual, Options and Orders trading desks and 45+45 scanner.
- Backend regression suite: 20/20 tests passed.
- Source UTF-8/NUL sanity check passed.
- Flutter SDK was not available in the build container, so APK/analyze validation is still required in GitHub Actions or a Flutter environment.
