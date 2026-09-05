# NEO Signal Terminal — V8 Build Gate

V8 is a release-hygiene and GitHub-build validation package based on V7.

- Preserves V7 robotic HUD and all trading/scanner/signal functionality.
- Removes runtime SQLite databases, local Android SDK path, Flutter generated plugin metadata, build logs, pytest cache and Python caches from the distributable source.
- Adds repository-level .gitignore for secrets, runtime state, Python, Flutter and IDE artifacts.
- GitHub Actions build gate now runs `flutter analyze --no-fatal-infos` before release APK compilation.
- Release APK still injects APP_API_TOKEN only from GitHub Actions secrets.
- Backend Python compile and regression tests are re-run before packaging.
- APK build success is not claimed until the GitHub Actions workflow itself completes green.
