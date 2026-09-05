$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  throw 'Flutter SDK is not on PATH. Install Flutter stable, reopen PowerShell, then rerun this script.'
}
$backup = Join-Path $env:TEMP ('neo_signal_android_backup_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item android\app\src\main\AndroidManifest.xml $backup\AndroidManifest.xml
Copy-Item android\app\build.gradle.kts $backup\app_build.gradle.kts
Copy-Item android\build.gradle.kts $backup\root_build.gradle.kts
Copy-Item android\settings.gradle.kts $backup\settings.gradle.kts
Copy-Item android\gradle.properties $backup\gradle.properties
Copy-Item android\app\src\main\res $backup\res -Recurse
Copy-Item android\app\src\main\kotlin $backup\kotlin -Recurse
try {
  flutter create . --platforms=android --project-name neo_signal_terminal --org com.neosignal
  Copy-Item $backup\AndroidManifest.xml android\app\src\main\AndroidManifest.xml -Force
  Copy-Item $backup\app_build.gradle.kts android\app\build.gradle.kts -Force
  Copy-Item $backup\root_build.gradle.kts android\build.gradle.kts -Force
  Copy-Item $backup\settings.gradle.kts android\settings.gradle.kts -Force
  Copy-Item $backup\gradle.properties android\gradle.properties -Force
  Remove-Item android\app\src\main\res -Recurse -Force
  Copy-Item $backup\res android\app\src\main\res -Recurse
  Remove-Item android\app\src\main\kotlin -Recurse -Force
  Copy-Item $backup\kotlin android\app\src\main\kotlin -Recurse
  flutter pub get
  flutter analyze
  Write-Host 'Flutter bootstrap + analyze completed.' -ForegroundColor Green
} finally {
  Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue
}
