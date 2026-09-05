#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v flutter >/dev/null || { echo 'Flutter SDK is not on PATH'; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp android/app/src/main/AndroidManifest.xml "$tmp/AndroidManifest.xml"
cp android/app/build.gradle.kts "$tmp/app_build.gradle.kts"
cp android/build.gradle.kts "$tmp/root_build.gradle.kts"
cp android/settings.gradle.kts "$tmp/settings.gradle.kts"
cp android/gradle.properties "$tmp/gradle.properties"
cp -R android/app/src/main/res "$tmp/res"
cp -R android/app/src/main/kotlin "$tmp/kotlin"
flutter create . --platforms=android --project-name neo_signal_terminal --org com.neosignal
cp "$tmp/AndroidManifest.xml" android/app/src/main/AndroidManifest.xml
cp "$tmp/app_build.gradle.kts" android/app/build.gradle.kts
cp "$tmp/root_build.gradle.kts" android/build.gradle.kts
cp "$tmp/settings.gradle.kts" android/settings.gradle.kts
cp "$tmp/gradle.properties" android/gradle.properties
rm -rf android/app/src/main/res android/app/src/main/kotlin
cp -R "$tmp/res" android/app/src/main/res
cp -R "$tmp/kotlin" android/app/src/main/kotlin
flutter pub get
flutter analyze
echo 'Flutter bootstrap + analyze completed.'
