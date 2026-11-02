#!/bin/bash
# Installs the iPhone Duo watcher to check every 48 seconds on this Mac, on clock slot 0 (the cloud tracker takes slot 24).
# Personal settings go in local.env next to this script (git ignores it); see local.env.example.

DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/local.env" ] || { cp "$DIR/local.env.example" "$DIR/local.env"; echo "Created local.env - fill it in, then re-run."; exit 1; }
PLIST=~/Library/LaunchAgents/com.mike.duowatch.plist
cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.mike.duowatch</string>
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$DIR/duo_watch.py</string><string>--loop</string><string>0</string></array>
<key>KeepAlive</key><true/>
<key>RunAtLoad</key><true/>
<key>StandardErrorPath</key><string>$HOME/duo_watch.err</string>
<key>StandardOutPath</key><string>$HOME/duo_watch.out</string>
</dict></plist>
P
launchctl unload "$PLIST" 2>/dev/null; launchctl load "$PLIST"

# keep the Mac from idle-sleeping so checks keep running (closing a laptop lid still sleeps it)
AWAKE=~/Library/LaunchAgents/com.mike.duowatch.awake.plist
cat > "$AWAKE" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.mike.duowatch.awake</string>
<key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-i</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
</dict></plist>
P
launchctl unload "$AWAKE" 2>/dev/null; launchctl load "$AWAKE"
echo "Running. Log: ~/duo_watch.log   Stop: launchctl unload $PLIST $AWAKE"
