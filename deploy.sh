#!/bin/sh
set -eu
APP=/opt/fly-casino
STATE=/var/lib/fly-casino
STAMP=$(date +%Y%m%d-%H%M%S)
install -d "$APP/templates" "$STATE/clones" "$STATE/backups"
if [ -f "$STATE/state.json" ]; then
  cp -a "$STATE/state.json" "$STATE/backups/state-pre-v3-$STAMP.json"
fi
install -m 0644 app.py simulation.py brain.py world.py README.md "$APP/"
install -m 0644 index.html "$APP/templates/index.html"
install -m 0644 fly-casino.service /etc/systemd/system/fly-casino.service
python3 -m py_compile "$APP/app.py" "$APP/simulation.py" "$APP/brain.py" "$APP/world.py"
systemctl daemon-reload
systemctl enable fly-casino
systemctl restart fly-casino
