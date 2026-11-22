#!/bin/bash
# Wi-Fi power saving of the Snapmaker J1 off
#
# Copyright (C) 2026  Nimrasol
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Run as root (sudo) by the KlipperScreen add-on when the NetworkManager
# setting is missing (systems installed before it was part of the OS).
# With power saving the Wi-Fi chip holds packets back: pings varied from
# 3 to 111ms and Mainsail lost its connection during prints; without it
# 3 to 21ms.
set -e

CONF=/etc/NetworkManager/conf.d/90-snapmaker-j1-wifi-powersave.conf

cat > "$CONF" <<'EOF'
# Wi-Fi power saving off (2 = disable): it delays packets and Mainsail
# loses its connection (Snapmaker J1)
[connection]
wifi.powersave = 2
EOF

# NetworkManager applies the setting when a connection is activated; the
# running connection gets it at once
for dev in /sys/class/net/*/wireless; do
    [ -e "$dev" ] || continue
    iw dev "$(basename "$(dirname "$dev")")" set power_save off || true
done
