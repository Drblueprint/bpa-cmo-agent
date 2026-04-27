#!/bin/bash
# BPA CMO Agent — Scheduler Installer
# Installs a launchd job that runs weekly_report_v2.py every Monday at 7:00am
# and posts it to Google Chat.
#
# Usage:
#   bash install_scheduler.sh          # install + load the job
#   bash install_scheduler.sh remove   # uninstall

set -e

LABEL="com.bpa.cmo.weekly"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
SCRIPT_DIR="$HOME/Desktop/bpa-cmo-agent"
PYTHON_BIN="$(which python3)"
LOG_OUT="$SCRIPT_DIR/scheduler.out.log"
LOG_ERR="$SCRIPT_DIR/scheduler.err.log"

if [ "$1" = "remove" ]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "Removed $LABEL"
  exit 0
fi

mkdir -p "$PLIST_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$SCRIPT_DIR/weekly_report_v2.py</string>
        <string>--days</string>
        <string>7</string>
        <string>--post</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_OUT</string>
    <key>StandardErrorPath</key>
    <string>$LOG_ERR</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed: $PLIST_PATH"
echo "Schedule:  every Monday at 7:00am"
echo "Logs:      $LOG_OUT  /  $LOG_ERR"
echo ""
echo "To run immediately for testing:"
echo "  launchctl start $LABEL"
echo "To remove:"
echo "  bash install_scheduler.sh remove"
