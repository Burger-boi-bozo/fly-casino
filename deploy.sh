#!/bin/sh
set -eu
APP=/opt/fly-casino
STATE=/var/lib/fly-casino
STAMP=$(date +%Y%m%d-%H%M%S)
install -d "$APP/templates" "$APP/data" "$STATE/clones" "$STATE/backups"
[ ! -f "$STATE/state.json" ] || cp -a "$STATE/state.json" "$STATE/backups/state-pre-v4-$STAMP.json"
[ ! -f "$STATE/colony-v4.json" ] || cp -a "$STATE/colony-v4.json" "$STATE/backups/colony-pre-v4-$STAMP.json"
install -m 0644 app.py simulation.py brain.py world.py colony.py connectome.py README.md "$APP/"
install -m 0644 data/connectome_v783_subset.json "$APP/data/connectome_v783_subset.json"
install -m 0644 index.html "$APP/templates/index.html"
install -m 0644 fly-casino.service /etc/systemd/system/fly-casino.service
python3 -m py_compile "$APP/app.py" "$APP/simulation.py" "$APP/brain.py" "$APP/world.py" "$APP/colony.py" "$APP/connectome.py"
systemctl daemon-reload
systemctl enable fly-casino
systemctl restart fly-casino
