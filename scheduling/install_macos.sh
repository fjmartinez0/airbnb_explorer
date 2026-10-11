#!/bin/bash
# Programa la captura diaria con launchd (macOS).
# Uso: ./scheduling/install_macos.sh [HORA]      (por defecto 8 = 8 a.m.)
set -euo pipefail

HOUR="${1:-8}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$(command -v python3)}"
LABEL="com.airbnb-explorer.capture"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

"$PYTHON" -c "import playwright" 2>/dev/null || {
  echo "Este Python ($PYTHON) no tiene playwright. Instala requirements.txt primero."; exit 1; }

mkdir -p "$PROJECT_DIR/data" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>explorer</string>
    <string>capture</string>
    <string>--scheduled</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$PROJECT_DIR/data/launchd.log</string>
  <key>StandardErrorPath</key><string>$PROJECT_DIR/data/launchd.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Programado: captura diaria a las ${HOUR}:00."
echo "Python:   $PYTHON"
echo "Proyecto: $PROJECT_DIR"
echo "Para probarlo ahora: launchctl start $LABEL"
