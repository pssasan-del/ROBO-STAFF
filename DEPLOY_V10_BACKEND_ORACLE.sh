#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${1:-$HOME/neo_signal_terminal_stage15/neo_signal_terminal}"
PKG_ROOT="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
if [ ! -d "$APP_ROOT/backend/app" ]; then
  echo "Backend target not found: $APP_ROOT/backend/app" >&2
  exit 1
fi
cp -a "$APP_ROOT/backend/app" "$APP_ROOT/backend/app.backup.$STAMP"
cp -a "$PKG_ROOT/backend/app/." "$APP_ROOT/backend/app/"
cd "$APP_ROOT/backend"
if [ -d venv ]; then source venv/bin/activate; fi
python -m compileall -q app
python -m pytest -q
systemctl --user restart neo-backend
sleep 2
systemctl --user --no-pager --full status neo-backend | sed -n '1,22p'
echo "V10 backend deployed; backup: $APP_ROOT/backend/app.backup.$STAMP"
