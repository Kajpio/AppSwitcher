#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.kajpio.appswitcher"
PLIST_SRC="$PROJECT_DIR/$LABEL.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DST="$LAUNCH_AGENTS_DIR/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

mkdir -p "$LAUNCH_AGENTS_DIR"

# Stop any existing LaunchAgent or manually launched instance first
launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
pkill -f "AppSwitcher/python/main.py" 2>/dev/null || true

/usr/bin/python3 -c '
import sys
src, dst, project_dir = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, "r", encoding="utf-8") as f:
    content = f.read().replace("__PROJECT_DIR__", project_dir)
with open(dst, "w", encoding="utf-8") as f:
    f.write(content)
' "$PLIST_SRC" "$PLIST_DST" "$PROJECT_DIR"

plutil -lint "$PLIST_DST" >/dev/null
launchctl bootstrap "$GUI_DOMAIN" "$PLIST_DST"

echo "Installed and started LaunchAgent: $PLIST_DST"
echo "Logs: /tmp/appswitcher.log"
