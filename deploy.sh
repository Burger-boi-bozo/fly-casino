#!/bin/sh
set -eu
install -d /opt/fly-casino/templates /var/lib/fly-casino
install -m 0644 app.py simulation.py README.md /opt/fly-casino/
install -m 0644 index.html /opt/fly-casino/templates/index.html
install -m 0644 fly-casino.service /etc/systemd/system/fly-casino.service
systemctl daemon-reload
systemctl enable --now fly-casino
systemctl restart fly-casino
