# Home page of the touch screen (replaces KlipperScreen's main menu)
#
# Copyright (C) 2026  Nimrasol
#
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Three columns: the heaters (current temperature, a kept target, 220C
# for the nozzles by default, and ON/OFF), loading and unloading once a
# nozzle is hot, and the service work (homing, moving the nozzles in for
# service, distributing fresh grease, the light page, motors and heaters
# off).  Below them Print, Move and Calibration; the Menu button in the
# action bar opens the rest (More, also Temperature and Extrude).  The
# heaters are set with SET_HEATER_TEMPERATURE, which does not block
# Klipper.
import logging
import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from ks_includes.screen_panel import ScreenPanel
from ks_includes.widgets.keypad import Keypad

from . import settings

PANEL = "snapmaker_service"
CONTROL = "snapmaker_menu"
# Panel of the calibration menu (see __init__)
CALIBRATION_PANEL = "snapmaker_calibration"
LIGHT_PANEL = "snapmaker_light"
# Grid columns of the three parts (heaters wider)
COLUMNS = (10, 8, 8)
TARGETS = "service_targets"
HEATERS = (("extruder", "Left Nozzle", 220, 0),
           ("extruder1", "Right Nozzle", 220, 1),
           ("heater_bed", "Heater Bed", 60, None))
# Load and unload once the nozzle is this close to its target
READY_MARGIN = 5
MIN_EXTRUDE_TEMP = 170
def _white_icon(themedir, name, size):
    # A theme symbol in white (the theme's greys replaced)
    with open(os.path.join(themedir, name + ".svg")) as f:
        svg = f.read()
    for grey in ("#c4c5cc", "#595a66"):
        svg = svg.replace(grey, "#f7f8fa")
    loader = GdkPixbuf.PixbufLoader()
    loader.set_size(int(size), int(size))
    loader.write(svg.encode())
    loader.close()
    return loader.get_pixbuf()


class MenuButton:
    # The menu button in the action bar of the home page opens the menu of
    # KlipperScreen (More); the home page shows no title and no heaters in
    # the title bar, it has them itself
    def __init__(self, screen):
        self.screen = screen
        base = screen.base_panel
        button = screen.gtk.Button("settings", scale=base.abscale)
        button.set_no_show_all(True)
        button.hide()
        button.connect("clicked", self._clicked)
        base.control[CONTROL] = button
        base.action_bar.add(button)
        base.action_bar.reorder_child(
            button, base.action_bar.get_children().index(
                base.control["home"]) + 1)
        self.button = button
        add_content = base.add_content

        def _add_content(panel):
            add_content(panel)
            home = (panel is not None
                    and panel is self.screen.panels.get("main_menu"))
            button.set_visible(home)
            item_box = base.control["item_box"]
            item_box.set_no_show_all(home)
            item_box.set_visible(not home)
            # The title stays (empty), it keeps WLAN and clock on the right
            if home:
                base.titlelbl.set_label("")

        base.add_content = _add_content

    def _clicked(self, widget):
        self.screen._go_to_submenu(widget, "more")


class Panel(ScreenPanel):
    def __init__(self, screen, title, items=None):
        super().__init__(screen, title or _("Home"))
        self.rows = {}
        self.filament = {}
        self.ready = {}
        self.keypad_heater = None
        self.serviced = False
        targets = settings.get(TARGETS, {})
        self.targets = {heater: targets.get(heater, default)
                        for heater, _name, default, _tool in HEATERS}

        # Three parts side by side, as wide as their share of the page (a
        # grid over all of them would widen to its widest button)
        gap = self._gtk.font_size // 2
        width = self._gtk.content_width - 3 * gap
        self.widths = [int(width * c / sum(COLUMNS)) for c in COLUMNS]
        # One column per part with its main button below it (Print, Move,
        # Calibration), so both gaps are the same
        parts = Gtk.Box(spacing=gap, vexpand=True, margin_bottom=gap // 2)
        self.parts = []
        columns = []
        for part_width in self.widths:
            part = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                           spacing=gap // 2, margin=gap // 2)
            grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                            vexpand=True, row_spacing=gap // 2,
                            column_spacing=gap // 2)
            part.pack_start(grid, True, True, 0)
            # Each part in a container of its own (snap-home-part)
            container = Gtk.EventBox()
            container.get_style_context().add_class("snap-home-part")
            container.add(part)
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                             spacing=gap)
            column.set_size_request(part_width, -1)
            column.pack_start(container, True, True, 0)
            parts.pack_start(column, False, False, 0)
            columns.append(column)
            self.parts.append(grid)
        for row, (heater, name, _default, tool) in enumerate(HEATERS):
            self._heater_row(row, heater, _(name), tool)
        # Loading and unloading, per nozzle and both at once
        self.both = {}
        for row, (tool, name) in enumerate(((0, "T0"), (1, "T1"),
                                            (2, _("Both")))):
            self._filament_row(row, tool, name)
        self.buttons = {
            "nozzles": self._gtk.Button("extruder", _("Nozzle Service"),
                                        "color1"),
            "home": self._gtk.Button("home", _("Home All"), "color2"),
            "grease": self._gtk.Button("refresh", _("Distribute Grease"),
                                       "color3"),
            # As on the move page: the axes can be moved by hand afterwards
            "motors_off": self._gtk.Button("motor-off", _("Disable Motors"),
                                           "color2"),
        }
        self.buttons["nozzles"].connect("clicked", self._nozzles)
        self.buttons["home"].connect("clicked", self._home)
        self.buttons["grease"].connect("clicked", self._grease)
        self.buttons["motors_off"].connect(
            "clicked", self._screen._confirm_send_action,
            _("Are you sure you wish to disable motors?"),
            "printer.gcode.script", {"script": "M18"})
        # The light page (Fine Tuning is on the print page and in the menu,
        # where it is needed)
        self.light = self._gtk.Button("light", _("Light"), "color4")
        self.light.connect("clicked", self._open, LIGHT_PANEL, _("Light"))
        off = self._gtk.Button("cool-down", _("All Heaters Off"), "color1")
        off.connect("clicked", self._all_off)
        # Moves first (home, then the tasks that need it), the two switches
        # that turn something off at the end, set off in red
        for i, button in enumerate((
                self.buttons["home"], self.buttons["nozzles"],
                self.buttons["grease"], self.light, self.buttons["motors_off"],
                off)):
            self.parts[2].attach(button, i % 2, i // 2, 1, 1)
        for button in (self.buttons["motors_off"], off):
            button.get_style_context().add_class("snap-switch-off")
        # Print, Move and Calibration below the three parts
        for (icon, label, panel), column in zip((
                ("resume", _("Print"), "gcodes"),
                ("move", _("Move"), "move"),
                ("bed-level", _("Calibration"), CALIBRATION_PANEL)),
                columns):
            button = self._gtk.Button(icon, label, None, self.bts,
                                      Gtk.PositionType.LEFT, 1)
            button.set_vexpand(False)
            button.set_size_request(-1, self._gtk.font_size * 4)
            # Without the button margin: aligned with the part above
            button.get_style_context().add_class("snap-home-nav")
            button.connect("clicked", self._open, panel, label)
            column.pack_start(button, False, False, 0)
            if panel == "gcodes":
                # The main task: the orange primary gradient, with a white
                # symbol (the theme draws it grey)
                button.get_style_context().add_class("active")
                size = self._gtk.img_scale * self.bts
                button.set_image(Gtk.Image.new_from_pixbuf(
                    _white_icon(self._gtk.themedir, icon, size)))
        self.page = parts

        self.keypad = Keypad(screen, self._keypad_ok, self._keypad_close,
                             entry_max=3)
        # Back closes the keypad as on every page (not its X); whole
        # degrees only (no point); the current target is the grey
        # placeholder, which typing replaces and OK alone keeps
        for button in (self.keypad.top_box.get_children()[1:]
                       + [b for b in self.keypad.get_children()[1]
                          .get_children() if b.get_label() == "."]):
            button.set_no_show_all(True)
            button.hide()
        entry = self.keypad.entry
        self.keypad.get_value = lambda: float(
            entry.get_text() or entry.get_placeholder_text() or "nan")
        # A refused value stays for correction (_edit empties the entry)
        self.keypad.clear = lambda: None
        self.keypad_title = Gtk.Label(hexpand=True)
        self.keypad_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                  spacing=self._gtk.font_size // 2,
                                  halign=Gtk.Align.CENTER, hexpand=True,
                                  vexpand=True)
        self.keypad_box.set_size_request(screen.width // 3, -1)
        self.keypad_box.add(self.keypad_title)
        self.keypad_box.pack_start(self.keypad, True, True, 0)
        # The material presets of the temperature page beside the keypad
        # (filled per heater in _edit)
        self.presets = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                               spacing=self._gtk.font_size // 2,
                               valign=Gtk.Align.CENTER)
        self.presets.set_size_request(screen.width // 5, -1)
        self.edit_box = Gtk.Box(spacing=self._gtk.font_size,
                                halign=Gtk.Align.CENTER)
        self.edit_box.pack_start(self.keypad_box, False, False, 0)
        self.edit_box.pack_start(self.presets, False, False, 0)
        self.content.add(self.page)

    def _open(self, widget, panel, title):
        self._screen.show_panel(panel, title)

    def _nozzle_diameter(self, heater):
        section = self._printer.get_config_section(heater) or {}
        try:
            return float(section.get("nozzle_diameter"))
        except (TypeError, ValueError):
            return None

    # A heater: one tile with name, nozzle diameter, current and target
    # temperature (a tap sets the target), and ON/OFF
    def _heater_row(self, row, heater, name, tool):
        image = ("bed" if tool is None else "extruder-%d" % (tool,))
        size = self._gtk.img_scale * self.bts
        box = Gtk.Box(spacing=self._gtk.font_size // 2)
        box.pack_start(self._gtk.Image(image, size, size), False, False, 0)
        # Name and nozzle diameter on the left, the temperatures on the right
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        valign=Gtk.Align.CENTER, hexpand=True)
        names.add(Gtk.Label(label=name, xalign=0,
                            ellipsize=Pango.EllipsizeMode.END))
        diameter = self._nozzle_diameter(heater) if tool is not None else None
        if diameter:
            small = Gtk.Label(xalign=0)
            small.set_markup("<small>Ø %g mm</small>" % (diameter,))
            names.add(small)
        box.pack_start(names, True, True, 0)
        temps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        valign=Gtk.Align.CENTER)
        temp = Gtk.Label(label="-", xalign=1)
        target = Gtk.Label(xalign=1)
        temps.add(temp)
        temps.add(target)
        temps.set_margin_end(self._gtk.font_size // 2)
        box.pack_end(temps, False, False, 0)
        label = Gtk.Button(hexpand=True, vexpand=True)
        label.add(box)
        for css in ("graph_label_" + heater, "graph_label"):
            label.get_style_context().add_class(css)
        label.connect("clicked", self._edit, heater)
        power = self._gtk.Button(None, _("ON"), "color1")
        power.connect("clicked", self._power, heater)
        # Tile and ON/OFF as one block: no gap, inner corners square, a thin
        # line between them (snap-heater-* in the theme)
        unit = Gtk.Box(hexpand=True)
        label.get_style_context().add_class("snap-heater-tile")
        power.get_style_context().add_class("snap-heater-power")
        power.set_size_request(self.widths[0] // 5, -1)
        power.set_hexpand(False)
        unit.pack_start(label, True, True, 0)
        unit.pack_start(power, False, False, 0)
        self.parts[0].attach(unit, 0, row, 10, 1)
        self.rows[heater] = {"temp": temp, "target": target, "tile": label,
                             "power": power}
        self._show_target(heater)

    def _filament_row(self, row, tool, name):
        grid = self.parts[1]
        # The name column narrow, the buttons wide enough for one line
        grid.attach(Gtk.Label(label=name), 0, row, 2, 1)
        load = self._gtk.Button("arrow-down", _("Load"), "color3", lines=1)
        unload = self._gtk.Button("arrow-up", _("Unload"), "color2", lines=1)
        load.connect("clicked", self._filament, "SNAPMAKER_LOAD_FILAMENT",
                     tool)
        unload.connect("clicked", self._filament,
                       "SNAPMAKER_UNLOAD_FILAMENT", tool)
        grid.attach(load, 2, row, 4, 1)
        grid.attach(unload, 6, row, 4, 1)
        if tool == 2:
            self.both = {"load": load, "unload": unload}
        else:
            heater = "extruder1" if tool == 1 else "extruder"
            self.filament[heater] = {"load": load, "unload": unload}

    def _show_target(self, heater):
        # The arrow: the temperature the heater goes to (short, so the
        # name keeps its room); while it is on the one it really heats to,
        # which a print or the web interface may have set
        current = self._stat(heater, "target") if self._printer else 0
        self.rows[heater]["target"].set_markup(
            "<small>→ %d°C</small>" % (current or self.targets[heater],))

    def activate(self):
        self._refresh()

    def process_update(self, action, data):
        if action == "notify_status_update":
            self._refresh()

    def _stat(self, heater, name):
        return self._printer.get_stat(heater, name) or 0

    def _refresh(self):
        if self._printer is None:
            return
        ready_all = {}
        for heater, widgets in self.rows.items():
            temp = self._stat(heater, "temperature")
            current = self._stat(heater, "target")
            widgets["temp"].set_label("%.1f°C" % (temp,))
            on = current > 0
            widgets["power"].set_label(_("OFF") if on else _("ON"))
            self._show_target(heater)
            # A heater that is on: orange frame, as a selected heater
            for key in ("tile", "power"):
                context = widgets[key].get_style_context()
                if on:
                    context.add_class("snap-heater-on")
                else:
                    context.remove_class("snap-heater-on")
            if heater in self.filament:
                ready = (on and current >= MIN_EXTRUDE_TEMP
                         and temp >= current - READY_MARGIN)
                self._set_ready(self.filament[heater], ready)
                ready_all[heater] = ready
        self.ready = dict(ready_all)
        self.ready[2] = all(ready_all.values())
        self._set_ready(self.both, self.ready[2])

    def _set_ready(self, buttons, ready):
        # Not insensitive: a tap on a button that is not ready explains why
        for button in buttons.values():
            context = button.get_style_context()
            if ready:
                context.remove_class("snap-not-ready")
            else:
                context.add_class("snap-not-ready")

    # Target temperatures
    def _max_temp(self, heater):
        section = self._printer.get_config_section(heater) or {}
        try:
            return float(section.get("max_temp", 300))
        except (TypeError, ValueError):
            return 300.

    def _edit(self, widget, heater):
        self.keypad_heater = heater
        name = next(name for h, name, _d, _t in HEATERS if h == heater)
        self.keypad_title.set_label(_(name))
        # The current target, ready to change
        self.keypad.entry.set_text("")
        self.keypad.entry.set_placeholder_text(str(self.targets[heater]))
        for child in self.presets.get_children():
            self.presets.remove(child)
        # Preheat sections name the bed "bed", the nozzles by their object
        key = "bed" if heater == "heater_bed" else heater
        for material, values in self._config.get_preheat_options().items():
            temp = (values or {}).get(key)
            if temp:
                button = self._gtk.Button(None, "%s  %d°C" % (material, temp))
                button.set_size_request(-1, self._gtk.font_size * 4)
                button.connect("clicked",
                               lambda w, t=temp: self._keypad_ok(t))
                self.presets.add(button)
        self.content.remove(self.page)
        self.content.add(self.edit_box)
        self._screen.base_panel.set_control_sensitive(True, "back")
        self._screen.base_panel.control[CONTROL].hide()
        self.content.show_all()

    def _keypad_close(self, widget=None):
        if self.keypad_heater is None:
            return
        self.keypad_heater = None
        self.content.remove(self.edit_box)
        self._screen.base_panel.set_control_sensitive(False, "back")
        self._screen.base_panel.control[CONTROL].show()
        self.content.add(self.page)
        self.content.show_all()

    def _keypad_ok(self, value):
        heater = self.keypad_heater
        limit = self._max_temp(heater)
        if not 0 < value <= limit:
            self._screen.show_popup_message(
                _("Temperature must be between 1 and %d°C") % (limit,),
                level=2)
            return
        self.targets[heater] = int(value)
        settings.save(TARGETS, self.targets)
        self._show_target(heater)
        # A heater that is on follows the new target at once
        if self._stat(heater, "target") > 0:
            self._set_target(heater, self.targets[heater])
        self._keypad_close()

    def back(self):
        if self.keypad_heater is not None:
            self._keypad_close()
            return True
        return False

    def _set_target(self, heater, temp):
        self._screen._ws.api.gcode_script(
            "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%d" % (heater, temp))

    def _power(self, widget, heater):
        on = self._stat(heater, "target") > 0
        self._set_target(heater, 0 if on else self.targets[heater])

    # Filament, service, homing, grease
    def _filament(self, widget, macro, tool):
        # At the nozzle service position (moves there unless it is there)
        # TOOL=2: both at once, each at its own target
        heater = "extruder1" if tool == 1 else "extruder"
        if not self.ready.get(2 if tool == 2 else heater):
            self._screen.show_popup_message(
                _("Switch the nozzle on (ON) and wait until it is hot"),
                level=1)
            return
        self._screen._ws.api.gcode_script(
            "%s TOOL=%d TEMP=%d SERVICE=1" % (macro, tool,
                                              self._stat(heater, "target")))
        self._set_serviced(True)

    def _set_serviced(self, serviced):
        self.serviced = serviced
        self.buttons["nozzles"].set_label(_("Park Nozzles") if serviced
                                          else _("Nozzle Service"))

    def _nozzles(self, widget):
        self._screen._ws.api.gcode_script(
            "SNAPMAKER_NOZZLE_PARK" if self.serviced
            else "SNAPMAKER_NOZZLE_SERVICE")
        self._set_serviced(not self.serviced)

    def _all_off(self, widget):
        for heater, _name, _default, _tool in HEATERS:
            self._set_target(heater, 0)

    def _home(self, widget):
        self._screen._confirm_send_action(
            widget, _("Home all axes? The nozzles and the bed move."),
            "printer.gcode.script", {"script": "G28"})

    def _grease(self, widget):
        label = Gtk.Label(hexpand=True, vexpand=True,
                          halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                          wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                          justify=Gtk.Justification.CENTER,
                          max_width_chars=48)
        label.set_markup("%s\n\n%s" % (
            GLib.markup_escape_text(
                _("Moves both nozzles, the bed and the Z axis once over"
                  " their travel to spread fresh grease (about a minute)."
                  " Tap again for another run.")),
            GLib.markup_escape_text(
                _("Remove everything from the build plate first."))))
        buttons = [
            {"name": _("Start"), "response": Gtk.ResponseType.OK,
             "style": "dialog-info"},
            {"name": _("Cancel"), "response": Gtk.ResponseType.CANCEL,
             "style": "dialog-secondary"},
        ]

        def response(dialog, response_id):
            self._gtk.remove_dialog(dialog)
            if response_id == Gtk.ResponseType.OK:
                self._set_serviced(False)
                self._screen._ws.api.gcode_script(
                    "SNAPMAKER_DISTRIBUTE_GREASE")

        self._gtk.Dialog(_("Distribute Grease"), buttons, label, response)
