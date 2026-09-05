@echo off
cd /d "%~dp0"
where flutter >nul 2>nul || (echo Flutter is not on PATH.& pause & exit /b 1)
flutter pub get || (pause & exit /b 1)
flutter analyze || (pause & exit /b 1)
flutter build apk --debug || (pause & exit /b 1)
echo.
echo APK: build\app\outputs\flutter-apk\app-debug.apk
pause
