#!/bin/bash
# Detiene y elimina la captura diaria programada.
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.airbnb-explorer.capture.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Captura diaria eliminada."
