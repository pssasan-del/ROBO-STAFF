@echo off
setlocal
if "%APP_API_TOKEN%"=="" (
  echo Set APP_API_TOKEN first: set APP_API_TOKEN=your_long_secret
  exit /b 1
)
flutter pub get || exit /b 1
flutter analyze || exit /b 1
flutter build apk --release --dart-define=APP_API_TOKEN=%APP_API_TOKEN% || exit /b 1
echo APK: build\app\outputs\flutter-apk\app-release.apk
