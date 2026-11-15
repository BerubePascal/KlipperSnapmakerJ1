#!/bin/bash
# Build the main controller firmware for the installed Klipper and install
# it, with Klipper stopped meanwhile
#
# Copyright (C) 2026  Nimrasol
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Run as root (sudo systemd-run) by the KlipperScreen add-on when Klipper
# cannot talk to the main controller: after a Klipper update that changed
# the protocol, or with the stock firmware still on the controller.  The
# log is shown in Mainsail (Machine -> Log Files).
set -e

J1="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
USER_NAME="$(stat -c %U "$J1")"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
LOG="$HOME_DIR/printer_data/logs/snapmaker_j1_mcu_update.log"

exec >> "$LOG" 2>&1
echo "== $(date) main controller firmware update"
# Klipper holds the serial port; it starts again whatever happens
trap 'systemctl start klipper; echo "== $(date) Klipper started"' EXIT
systemctl stop klipper
runuser -u "$USER_NAME" -- env KLIPPER_DIR="$HOME_DIR/klipper" \
    "$J1/firmware/build.sh"
runuser -u "$USER_NAME" -- "$HOME_DIR/klippy-env/bin/python" \
    "$J1/scripts/snapmaker_j1_flash.py" -w 30 "$J1/firmware/out/mc.bin"
echo "== done"
