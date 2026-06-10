#!/bin/zsh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.worldcup.predictor.batch.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.worldcup.predictor.batch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${PROJECT_DIR}/daily_batch_collect.command</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/storage/batch_stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/storage/batch_stderr.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"

echo "每日批量建库已安装：每天 08:30 自动运行。"
echo "日志位置：storage/batch_stdout.log 和 storage/batch_stderr.log"
read -k 1 "?按任意键关闭窗口。"
