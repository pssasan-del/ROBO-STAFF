# NEO Signal Terminal — V9 Compile-Fix Gate

V9 is a corrective build-gate release based on V8.

- Fixed two Dart syntax defects in `mobile/lib/main.dart`:
  - removed an extra closing brace after `ModifyOrderDialog`;
  - restored a missing closing parenthesis in `OptionChainTable` score cell.
- Added a GitHub Actions Dart syntax parse gate before `flutter analyze`:
  - `dart format --output=none lib/main.dart lib/king_bro_theme.dart`
- Removed runtime SQLite state from the distributable package.
- Removed Python caches and stale backup/source scratch files from backend.
- UTF-8 / NUL sanity check passed for Dart sources.
- Backend Python compilation passed.
- Backend regression suite: 20/20 tests passed.
- APK build success is still not claimed until the GitHub Actions Flutter job completes green.
