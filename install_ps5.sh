#!/bin/bash
# Installs the PS5 Pro (PlayStation Direct) watcher as a launchd job on this Mac: com.mike.ps5watch.
# It reuses local.env (PS5_NTFY_TOPIC, or DUO_NTFY_TOPIC) and the Duo watcher's keep-awake job if that's installed.
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST=~/Library/LaunchAgents/com.mike.ps5watch.plist
cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.mike.ps5watch</string>
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>-I</string><string>$DIR/ps5_watch.py</string><string>--loop</string></array>
<key>WorkingDirectory</key><string>$DIR</string>
<key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
<key>KeepAlive</key><true/>
<key>RunAtLoad</key><true/>
<key>StandardErrorPath</key><string>$HOME/ps5_watch.err</string>
<key>StandardOutPath</key><string>$HOME/ps5_watch.out</string>
</dict></plist>
P
launchctl unload "$PLIST" 2>/dev/null; launchctl load "$PLIST"
echo "Running. Log: ~/ps5_watch.log   Stop: launchctl unload $PLIST"
