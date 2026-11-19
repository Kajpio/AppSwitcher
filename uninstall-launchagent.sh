#!/usr/bin/env bash
set -euo pipefail

LABEL="com.kajpio.appswitcher"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
rm -f "$PLIST_DST"
pkill -f "AppSwitcher/python/main.py" 2>/dev/null || true

echo "Stopped and removed LaunchAgent: $PLIST_DST"
