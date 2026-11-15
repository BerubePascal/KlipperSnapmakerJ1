# Main controller firmware update from the error page of KlipperScreen
#
# Copyright (C) 2026  Nimrasol
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Klipper stops with "Protocol error" when an update of Klipper changed
# its protocol to the main controller, and with "Unable to connect" when
# the controller still runs the stock firmware.  Both are fixed by building
# and installing the firmware for the installed Klipper
# (scripts/snapmaker_j1_mcu_update.sh, a few minutes); without this the
# touch screen offered no way, only SSH.
import logging
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                      "scripts", "snapmaker_j1_mcu_update.sh")
UNIT = "snapmaker-j1-mcu-update"
REASONS = ("Protocol error", "Unable to connect")


def needed(message):
    return any(reason in message for reason in REASONS)


def ask(screen):
    label = Gtk.Label(hexpand=True, vexpand=True, halign=Gtk.Align.CENTER,
                      valign=Gtk.Align.CENTER, wrap=True,
                      wrap_mode=Pango.WrapMode.WORD_CHAR,
                      justify=Gtk.Justification.CENTER, max_width_chars=48)
    label.set_markup("%s\n\n%s" % (
        GLib.markup_escape_text(_("Update the main controller firmware?")),
        GLib.markup_escape_text(
            _("The firmware is built for the installed Klipper and"
              " installed on the main controller. This takes a few"
              " minutes; do not switch the printer off. Klipper starts"
              " again afterwards."))))
    buttons = [
        {"name": _("Update"), "response": Gtk.ResponseType.OK,
         "style": "dialog-info"},
        {"name": _("Cancel"), "response": Gtk.ResponseType.CANCEL,
         "style": "dialog-secondary"},
    ]

    def response(dialog, response_id):
        screen.gtk.remove_dialog(dialog)
        if response_id == Gtk.ResponseType.OK:
            _start(screen)

    screen.gtk.Dialog(_("Controller Firmware"), buttons, label, response)


def _start(screen):
    try:
        subprocess.run(["sudo", "-n", "systemd-run", "--unit", UNIT,
                        "--collect", "bash", os.path.realpath(SCRIPT)],
                       check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as e:
        logging.exception("Starting the firmware update failed")
        screen.show_popup_message(
            _("The firmware update could not be started: %s") % (e,))
        return
    screen.show_popup_message(
        _("Updating the main controller firmware (a few minutes)..."), 1)
