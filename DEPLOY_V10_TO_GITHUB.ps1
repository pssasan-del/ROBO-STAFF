param(
  [string]$Repo = "D:\NEO_BUILD\neo_stage15\neo_signal_terminal"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Source: $root"
Write-Host "Repo:   $Repo"
if (!(Test-Path $Repo)) { throw "Repo path not found: $Repo" }
if (!(Test-Path (Join-Path $Repo ".git"))) { throw "Target is not a git repo: $Repo" }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $Repo "_pre_v10_backup_$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item (Join-Path $Repo "mobile\lib\main.dart") $backup -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Repo "mobile\lib\king_bro_theme.dart") $backup -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Repo ".github\workflows\build-apk.yml") $backup -ErrorAction SilentlyContinue
Copy-Item (Join-Path $root "mobile\lib\main.dart") (Join-Path $Repo "mobile\lib\main.dart") -Force
Copy-Item (Join-Path $root "mobile\lib\king_bro_theme.dart") (Join-Path $Repo "mobile\lib\king_bro_theme.dart") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $Repo ".github\workflows") | Out-Null
Copy-Item (Join-Path $root ".github\workflows\build-apk.yml") (Join-Path $Repo ".github\workflows\build-apk.yml") -Force
Copy-Item (Join-Path $root "mobile\pubspec.yaml") (Join-Path $Repo "mobile\pubspec.yaml") -Force
Push-Location $Repo
try {
  git status --short
  git add mobile/lib/main.dart mobile/lib/king_bro_theme.dart mobile/pubspec.yaml .github/workflows/build-apk.yml
  git commit -m "NEO Signal Terminal V10 release candidate"
  git push
  Write-Host "PUSH COMPLETE. Run GitHub Actions -> Build Android APK."
} finally { Pop-Location }
