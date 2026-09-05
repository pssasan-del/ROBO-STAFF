# NEO Signal Terminal V12 — Error Correction Pass

User decision: one unresolved scanner symbol is acceptable. 44 live instruments is treated as operational coverage; no effort was spent forcing the 45th symbol.

## Corrected
- Scanner UI no longer treats 44/45 as a blocking failure; it reports live/ready/warming counts and labels unresolved rows as skipped.
- Scanner backend exposes `coverage_ok` when at least 44 instruments resolve.
- Strategy warm-up diagnostics use the resolved universe, so a fresh 44-stock scan reports warming instruments instead of a misleading 0/0 state.
- Kotak instrument search now returns normalized `trading_symbol`, `exchange_segment`, and `instrument_token` metadata where available.
- Manual Trade prefers normalized rows, de-duplicates search results, and shows segment/type/short instrument ID instead of `- • token -`.
- Live quote loading state is isolated to the selected instrument; the whole page no longer looks stuck while results are already visible.
- Raw Account JSON panels were removed from normal UI. Account snapshot now shows order/holding/journal counts plus readable fund/margin values.
- Backend URL moved under collapsed `Advanced connection`.
- Kill Switch changed to danger styling and now requires a confirmation dialog.
- Existing robotic Home, Signals, Trade, Options, Orders, Portfolio and risk-gated execution were preserved.

## Validation
- Backend Python compile: PASS
- Backend tests: 20/20 PASS
- Dart source UTF-8 / NUL sanity: PASS
- Delimiter count sanity for main.dart: balanced
- Flutter SDK is not available in this environment, so GitHub Actions remains the APK compile gate.
