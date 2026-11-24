"""Dial indicator bed mesh for the Snapmaker J1 (KlipperScreen screen).

LOCAL CHANGE of the fork BerubePascal/KlipperSnapmakerJ1: this file is not
part of the original KlipperSnapmakerJ1.

What it is for
--------------
The J1 has no bed mesh probing: the designers assumed the thick glass plate
stays flat. This screen measures the bed by hand with a dial indicator
mounted on a carriage in place of its hotend, and saves the result as a
Klipper bed mesh profile (``[bed_mesh dial]`` in
``~/printer_data/config/snapmaker_j1_bed_mesh.cfg``). Prints use it through
the ``LOAD_DIAL_MESH`` macro (printer.cfg) in the slicer start G-code.

How to use it
-------------
Touch screen: Calibration -> "Bed Mesh (Dial Indicator)" -> Start, which
opens this screen.

1. Setup page: choose the toolhead carrying the dial indicator, a grid
   (preset or custom: points in X and Y, margin from the bed edges), the
   bed temperature and the sign of the dial. Start.
2. The printer clears any active mesh, heats the bed (and waits), homes,
   selects the toolhead and moves to the reference point X162 Y187 (the
   point where the J1 bed leveling sets Z=0) with the bed at Z=0. Zero the
   dial there.
3. For each grid point (zigzag from the front-left corner): the bed lowers
   to Z=10, the toolhead moves, the bed comes back to Z=0. Type the dial
   reading on the keypad, then Next. Previous goes back one point.
4. At the end the toolhead returns to the reference point to check the dial
   didn't drift, then the bed lowers, both carriages park and the bed
   heater switches off.
5. Result page: deviations relative to the reference point. Save writes the
   profile and restarts Klipper to load it.

Mesh values
-----------
Klipper's mesh value at a point is the height of the bed there (positive =
bed higher, the nozzle is raised). With "Plunger in = bed higher" (normal
dial indicators: the reading increases when the plunger is pushed in) the
readings are used as they are, otherwise reversed. The saved mesh is shifted
so that it is exactly 0 at the reference point, where the J1 calibration
defines Z=0; so zeroing the dial there is only a convenience.

Main parts
----------
- ``grid_axis``, ``grid_points``, ``serpentine``: the measuring grid.
- ``bilinear``: value of a grid at a point (as Klipper interpolates).
- ``build_mesh``: readings -> mesh relative to the reference point.
- ``mesh_file_text``: the profile file in Klipper's stored-profile format.
- ``Panel``: the screen (setup, measuring with keypad, result).
"""
import datetime
import logging
import os

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from ks_includes.screen_panel import ScreenPanel

from . import style as S

# Name of the screen (KlipperScreen panel), opened from the calibration menu
PANEL = "snapmaker_bed_mesh"
# Calibration point 1 of [snapmaker_j1_probe] (rear center): the J1 bed
# leveling (SNAPMAKER_CAL_DATUM POINT=1) sets the Z origin there
REFERENCE = (162., 187.)
# Print area of the J1 (mm); the grid keeps the margin inside it
BED_X = (0., 324.)
BED_Y = (0., 200.)
# Grid presets (points in X, points in Y); the default is the third
PRESETS = [(3, 3), (5, 5), (7, 5), (9, 7)]
DEFAULT_PRESET = 2
COUNT_MIN, COUNT_MAX = 2, 15
MARGIN_DEFAULT, MARGIN_MIN, MARGIN_MAX, MARGIN_STEP = 15., 5., 40., 5.
BED_TEMP_DEFAULT, BED_TEMP_MAX, BED_TEMP_STEP = 60, 100, 5
# The bed counts as heated this close to its target (C)
BED_READY_MARGIN = 1.
# Bed heights (Z) between points and while measuring, and the speeds
SAFE_Z, MEASURE_Z = 10., 0.
XY_SPEED, Z_SPEED, APPROACH_SPEED = 6000., 600., 300.
# Reference reading change at the end above which the result warns (mm)
DRIFT_WARNING = .03
# Klipper profile name and the file holding it (included by printer.cfg)
PROFILE = "dial"
MESH_FILE = os.path.expanduser(
    "~/printer_data/config/snapmaker_j1_bed_mesh.cfg")
# Klipper's stored-profile version (bed_mesh.py PROFILE_VERSION)
PROFILE_VERSION = 1
# G-code state saved during the measurement (offsets, absolute mode)
STATE_NAME = "_snapmaker_dial_mesh"
KEYPAD = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "-", "0", "."]
MAX_ENTRY = 7
# Look of the chosen option buttons (orange outline, as the primary color)
CHOSEN_CSS = b"""
.snapj1 button.snap-secondary.snap-chosen { border-color: #ff8a00; }
.snapj1 button.snap-secondary.snap-chosen label { color: #ff8a00; }
"""
_css_installed = []


def grid_axis(count, low, high):
    """Evenly spaced positions along one axis.

    Parameters
    ----------
    count : int
        Number of points (at least 2).
    low, high : float
        First and last position (mm).

    Returns
    -------
    list of float
        ``count`` positions from ``low`` to ``high``, rounded to 0.01 mm.
    """
    step = (high - low) / (count - 1)
    return [round(low + i * step, 2) for i in range(count)]


def grid_points(x_count, y_count, margin):
    """Positions of the measuring grid inside the print area.

    Parameters
    ----------
    x_count, y_count : int
        Points in X and in Y.
    margin : float
        Distance of the outer points from the print area edges (mm).

    Returns
    -------
    tuple of (list of float, list of float)
        X positions (left to right) and Y positions (front to back).
    """
    xs = grid_axis(x_count, BED_X[0] + margin, BED_X[1] - margin)
    ys = grid_axis(y_count, BED_Y[0] + margin, BED_Y[1] - margin)
    return xs, ys


def serpentine(x_count, y_count):
    """Measuring order: rows from the front, alternating direction.

    Parameters
    ----------
    x_count, y_count : int
        Points in X and in Y.

    Returns
    -------
    list of tuple of (int, int)
        Grid indexes ``(ix, iy)``; the toolhead never travels back across
        a whole row.
    """
    order = []
    for iy in range(y_count):
        columns = range(x_count) if iy % 2 == 0 else range(x_count - 1, -1, -1)
        order.extend((ix, iy) for ix in columns)
    return order


def _cell(axis, value):
    # Index of the interval of a sorted axis holding value, and the
    # fraction along it (value clamped into the axis range)
    value = min(max(value, axis[0]), axis[-1])
    for i in range(len(axis) - 1):
        if value <= axis[i + 1]:
            return i, (value - axis[i]) / (axis[i + 1] - axis[i])
    return len(axis) - 2, 1.


def bilinear(xs, ys, values, x, y):
    """Value of a grid at a point, interpolated as Klipper's bed mesh does.

    Parameters
    ----------
    xs, ys : list of float
        Grid positions (each at least 2, increasing).
    values : list of list of float
        ``values[iy][ix]``, rows from the front (lowest Y).
    x, y : float
        The point; outside the grid it is clamped to the nearest edge, as
        Klipper does.

    Returns
    -------
    float
        Interpolated value.
    """
    ix, tx = _cell(xs, x)
    iy, ty = _cell(ys, y)
    front = values[iy][ix] * (1 - tx) + values[iy][ix + 1] * tx
    back = values[iy + 1][ix] * (1 - tx) + values[iy + 1][ix + 1] * tx
    return front * (1 - ty) + back * ty


def build_mesh(xs, ys, readings, sign):
    """Turn dial readings into a mesh that is 0 at the reference point.

    Parameters
    ----------
    xs, ys : list of float
        Grid positions.
    readings : dict
        ``{(ix, iy): reading}`` for every grid point (mm).
    sign : float
        1 when a higher reading means a higher bed (plunger pushed in),
        -1 otherwise.

    Returns
    -------
    list of list of float
        ``mesh[iy][ix]`` (mm, positive = bed higher than at the reference
        point), rows from the front.
    """
    raw = [[sign * readings[(ix, iy)] for ix in range(len(xs))]
           for iy in range(len(ys))]
    zero = bilinear(xs, ys, raw, *REFERENCE)
    return [[value - zero for value in row] for row in raw]


def mesh_file_text(xs, ys, mesh, readings, info):
    """The profile file: Klipper's stored-profile format plus comments.

    Parameters
    ----------
    xs, ys : list of float
        Grid positions.
    mesh : list of list of float
        Mesh values (``build_mesh``), rows from the front.
    readings : dict
        Raw dial readings ``{(ix, iy): reading}``, kept as comments.
    info : dict
        ``date``, ``tool``, ``bed_temp``, ``sign``, ``ref_start``,
        ``ref_end`` for the header comments.

    Returns
    -------
    str
        Content of ``snapmaker_j1_bed_mesh.cfg``.

    Notes
    -----
    ``mesh_x_pps``/``mesh_y_pps`` 0 and ``algo = direct``: no upsampling,
    Klipper interpolates linearly between the measured points.
    """
    lines = [
        "# Bed mesh measured with a dial indicator (touch screen:",
        "# Calibration -> Bed Mesh (Dial Indicator); written by",
        "# klipperscreen/snapmaker_j1/bed_mesh.py of the fork). Prints load it",
        "# with LOAD_DIAL_MESH (printer.cfg). Measuring again replaces this file.",
        "#",
        "# Measured: %s, %s toolhead, bed %d C" % (
            info["date"], info["tool"], info["bed_temp"]),
        "# Dial sign: %s" % ("plunger in = bed higher" if info["sign"] > 0
                             else "plunger in = bed lower"),
        "# Reference X%g Y%g: reading %.3f at the start, %.3f at the end" % (
            REFERENCE[0], REFERENCE[1], info["ref_start"], info["ref_end"]),
        "# Raw readings (rows from the front, X left to right):",
        "#   X: " + ", ".join("%g" % x for x in xs),
    ]
    for iy, y in enumerate(ys):
        lines.append("#   Y%g: " % y + ", ".join(
            "%.3f" % readings[(ix, iy)] for ix in range(len(xs))))
    lines += [
        "",
        "[bed_mesh %s]" % PROFILE,
        "version = %d" % PROFILE_VERSION,
        "points =",
    ]
    lines += ["    " + ", ".join("%.4f" % v for v in row) for row in mesh]
    lines += [
        "x_count = %d" % len(xs),
        "y_count = %d" % len(ys),
        "mesh_x_pps = 0",
        "mesh_y_pps = 0",
        "algo = direct",
        "tension = 0.2",
        "min_x = %.3f" % xs[0],
        "max_x = %.3f" % xs[-1],
        "min_y = %.3f" % ys[0],
        "max_y = %.3f" % ys[-1],
        "",
    ]
    return "\n".join(lines)


def write_mesh_file(text):
    """Write the profile file atomically, keeping the previous one as .bak.

    Parameters
    ----------
    text : str
        File content (``mesh_file_text``).

    Raises
    ------
    OSError
        When the file cannot be written.
    """
    if os.path.exists(MESH_FILE):
        os.replace(MESH_FILE, MESH_FILE + ".bak")
    with open(MESH_FILE + ".tmp", "w") as f:
        f.write(text)
    os.replace(MESH_FILE + ".tmp", MESH_FILE)


class Panel(ScreenPanel):
    """The bed mesh screen: setup page, measuring page, result page.

    Parameters
    ----------
    screen : KlipperScreen
        The KlipperScreen instance.
    title : str
        Title shown in the title bar.
    """

    def __init__(self, screen, title):
        super().__init__(screen, title or _("Bed Mesh"))
        S.install(screen)
        if not _css_installed:
            provider = Gtk.CssProvider()
            provider.load_from_data(CHOSEN_CSS)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 11)
            _css_installed.append(provider)
        # Setup choices
        self.tool = 0
        self.preset = DEFAULT_PRESET
        self.x_count, self.y_count = PRESETS[DEFAULT_PRESET]
        self.margin = MARGIN_DEFAULT
        self.bed_temp = BED_TEMP_DEFAULT
        self.sign = 1.
        # Measurement
        self.running = False
        self.state = "setup"
        self.xs = self.ys = []
        self.order = []
        self.pos = 0
        self.readings = {}
        self.ref_start = self.ref_end = None
        self.entry = ""
        self.busy = False
        self.heat_timer = None
        self.mesh = None
        self.w = {}
        self._show_setup()

    # Helpers
    def _dp(self, value):
        """Android dp of the stock pages in screen pixels."""
        return int(round(S.dp(self._screen, value)))

    @staticmethod
    def _styled(widget, *classes):
        """Add CSS classes to a widget and return it."""
        ctx = widget.get_style_context()
        for name in classes:
            ctx.add_class(name)
        return widget

    def _button(self, label, kind, callback, *args, small=False):
        """A button of the add-on style (kind: primary or secondary)."""
        button = Gtk.Button(label=label, can_focus=False,
                            valign=Gtk.Align.CENTER)
        self._styled(button, "snap-" + kind)
        if small:
            self._styled(button, "snap-small")
        button.connect("clicked", callback, *args)
        return button

    def _text(self, text, *classes, **kwargs):
        """A wrapping label."""
        label = Gtk.Label(label=text, wrap=True, xalign=0,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, **kwargs)
        return self._styled(label, *classes)

    def _set_page(self, child):
        """Replace the content of the screen with a new page."""
        for old in self.content.get_children():
            self.content.remove(old)
        root = Gtk.EventBox(hexpand=True, vexpand=True)
        self._styled(root, "snapj1")
        root.add(child)
        self.content.add(root)
        root.show_all()

    def _gcode(self, script, callback=None):
        """Run g-code; on success call callback, on error abort the run.

        Parameters
        ----------
        script : str
            G-code lines separated by newlines.
        callback : callable or None
            Called without arguments once Klipper finished the script.
        """
        logging.info("Bed mesh: %s", script.replace("\n", "; "))
        self.busy = True
        self._update_buttons()

        def done(result, method, params, *args):
            self.busy = False
            if "error" in result:
                message = result["error"].get("message", str(result["error"]))
                logging.error("Bed mesh: %s", message)
                self._screen.show_popup_message(
                    _("Bed mesh stopped: %s") % message)
                if self.running:
                    self._end_run(show_setup=True)
                return
            self._update_buttons()
            if callback is not None:
                callback()

        self._screen._ws.api.gcode_script(script, done)

    def _stat(self, obj, field, default=None):
        value = self._printer.get_stat(obj, field)
        return default if value in ({}, None) else value

    # Setup page
    def _choice_row(self, title, options, chosen, callback):
        """A titled row of option buttons; the chosen one is outlined."""
        row = Gtk.Box(spacing=self._dp(8))
        row.pack_start(self._text(title, width_chars=12), False, False, 0)
        buttons = []
        for i, name in enumerate(options):
            button = self._button(name, "secondary", callback, i, small=True)
            if i == chosen:
                self._styled(button, "snap-chosen")
            row.pack_start(button, False, False, 0)
            buttons.append(button)
        return row, buttons

    def _stepper(self, row, title, key, value_text, change):
        """Add "title  -  value  +" to a row.

        Parameters
        ----------
        row : Gtk.Box
            Row to add the widgets to.
        title : str
            Label before the buttons.
        key : str
            Name of the value label in ``self.w``.
        value_text : str
            Initial value text.
        change : callable
            Called as ``change(delta)`` with -1 or +1.
        """
        row.pack_start(self._text(title), False, False, 0)
        row.pack_start(self._button("-", "secondary",
                                    lambda w: change(-1), small=True),
                       False, False, 0)
        value = self._styled(Gtk.Label(label=value_text, width_chars=6),
                             "snap-value")
        self.w[key] = value
        row.pack_start(value, False, False, 0)
        row.pack_start(self._button("+", "secondary",
                                    lambda w: change(1), small=True),
                       False, False, self._dp(8))

    def _show_setup(self):
        """Build and show the setup page."""
        self.state = "setup"
        self.w = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      spacing=self._dp(6), vexpand=True)
        for side in ("start", "end", "top"):
            getattr(box, "set_margin_" + side)(self._dp(16))
        box.pack_start(self._text(
            _("Measure the bed with a dial indicator mounted in place of a"
              " hotend. At each point the bed comes up to Z=0; type the"
              " reading."), "snap-progress"), False, False, 0)
        row, self.w["tool"] = self._choice_row(
            _("Toolhead"), [_("Left"), _("Right")], self.tool,
            self._choose_tool)
        box.pack_start(row, False, False, 0)
        names = ["%d×%d" % p for p in PRESETS] + [_("Custom")]
        row, self.w["preset"] = self._choice_row(
            _("Grid"), names, self.preset, self._choose_preset)
        box.pack_start(row, False, False, 0)
        # Custom grid: points in X and Y (only active with "Custom")
        custom = Gtk.Box(spacing=self._dp(8))
        custom.pack_start(self._text(_("Custom"), width_chars=12),
                          False, False, 0)
        self._stepper(custom, "X", "x_count", str(self.x_count),
                      lambda d: self._change("x_count", d))
        self._stepper(custom, "Y", "y_count", str(self.y_count),
                      lambda d: self._change("y_count", d))
        self.w["custom"] = custom
        box.pack_start(custom, False, False, 0)
        # Edge margin and bed temperature
        row = Gtk.Box(spacing=self._dp(8))
        self._stepper(row, _("Margin"), "margin", "%g mm" % self.margin,
                      lambda d: self._change("margin", d))
        self._stepper(row, _("Bed"), "bed_temp", self._temp_text(),
                      lambda d: self._change("bed_temp", d))
        box.pack_start(row, False, False, 0)
        # Dial sign, grid summary and Start
        bottom = Gtk.Box(spacing=self._dp(8))
        bottom.pack_start(self._text(_("Plunger in = bed higher")),
                          False, False, 0)
        switch = Gtk.Switch(active=self.sign > 0, valign=Gtk.Align.CENTER,
                            can_focus=False)
        switch.connect("notify::active", self._sign_changed)
        bottom.pack_start(switch, False, False, 0)
        self.w["summary"] = self._text("", "snap-progress", hexpand=True)
        bottom.pack_start(self.w["summary"], True, True, self._dp(8))
        bottom.pack_end(self._button(_("Start"), "primary", self._start),
                        False, False, 0)
        box.pack_end(bottom, False, False, self._dp(12))
        self._set_page(box)
        self._update_setup()

    def _temp_text(self):
        return "%d°C" % self.bed_temp if self.bed_temp else _("Off")

    def _update_setup(self):
        """Refresh the chosen buttons, values and the grid summary."""
        for key, chosen in (("tool", self.tool), ("preset", self.preset)):
            for i, button in enumerate(self.w[key]):
                ctx = button.get_style_context()
                (ctx.add_class if i == chosen else ctx.remove_class)(
                    "snap-chosen")
        self.w["custom"].set_sensitive(self.preset == len(PRESETS))
        self.w["x_count"].set_label(str(self.x_count))
        self.w["y_count"].set_label(str(self.y_count))
        self.w["margin"].set_label("%g mm" % self.margin)
        self.w["bed_temp"].set_label(self._temp_text())
        xs, ys = grid_points(self.x_count, self.y_count, self.margin)
        self.w["summary"].set_label(
            _("%d points, X %g–%g, Y %g–%g") % (
                len(xs) * len(ys), xs[0], xs[-1], ys[0], ys[-1]))

    def _choose_tool(self, widget, index):
        self.tool = index
        self._update_setup()

    def _choose_preset(self, widget, index):
        self.preset = index
        if index < len(PRESETS):
            self.x_count, self.y_count = PRESETS[index]
        self._update_setup()

    def _change(self, key, delta):
        """Step a setup value up or down within its limits.

        Parameters
        ----------
        key : str
            ``x_count``, ``y_count``, ``margin`` or ``bed_temp``.
        delta : int
            -1 or +1.
        """
        step, low, high = {
            "x_count": (1, COUNT_MIN, COUNT_MAX),
            "y_count": (1, COUNT_MIN, COUNT_MAX),
            "margin": (MARGIN_STEP, MARGIN_MIN, MARGIN_MAX),
            "bed_temp": (BED_TEMP_STEP, 0, BED_TEMP_MAX)}[key]
        value = min(max(getattr(self, key) + delta * step, low), high)
        setattr(self, key, value)
        self._update_setup()

    def _sign_changed(self, switch, param):
        self.sign = 1. if switch.get_active() else -1.

    # Measuring
    def _start(self, widget):
        """Check the printer is free, then prepare: heat, home, Z=10."""
        state = self._stat("print_stats", "state", "standby")
        if state in ("printing", "paused"):
            self._screen.show_popup_message(
                _("Not available while a print is running."))
            return
        carriage = self._stat("dual_carriage", "carriage_1", "")
        if carriage in ("COPY", "MIRROR"):
            self._screen.show_popup_message(
                _("Not available in duplication or mirror mode."))
            return
        self.xs, self.ys = grid_points(self.x_count, self.y_count,
                                       self.margin)
        self.order = serpentine(len(self.xs), len(self.ys))
        self.readings = {}
        self.pos = 0
        self.ref_start = self.ref_end = None
        self.running = True
        self._show_run()
        self._set_status(_("Homing and heating the bed..."))
        lines = [
            "SAVE_GCODE_STATE NAME=%s" % STATE_NAME,
            # The measurement must see the bed without any correction
            "BED_MESH_CLEAR",
            "_SNAPMAKER_RESET_MODE",
            "SET_GCODE_OFFSET X=0 Y=0 Z=0",
            "M140 S%d" % self.bed_temp,
            "G28",
            "T%d" % self.tool,
            # T1 applies its Y offset; the grid is in machine coordinates
            "SET_GCODE_OFFSET X=0 Y=0 Z=0",
            "G90",
            "G1 Z%.1f F%d" % (SAFE_Z, Z_SPEED),
            "M400",
        ]
        self._gcode("\n".join(lines), self._wait_heat)

    def _wait_heat(self):
        """Poll the bed temperature until it reached its target."""
        if not self.bed_temp:
            self._goto_reference("ref_start")
            return
        self.state = "heat"
        self.heat_timer = GLib.timeout_add_seconds(1, self._check_heat)
        self._check_heat()

    def _check_heat(self):
        if not self.running:
            self.heat_timer = None
            return False
        temp = self._stat("heater_bed", "temperature", 0.)
        self._set_status(_("Heating the bed: %.1f / %d°C") % (
            temp, self.bed_temp))
        if temp >= self.bed_temp - BED_READY_MARGIN:
            if self.heat_timer is not None:
                GLib.source_remove(self.heat_timer)
                self.heat_timer = None
            self._goto_reference("ref_start")
            return False
        return True

    def _move_script(self, x, y):
        """Lower the bed, move the toolhead, raise the bed to Z=0."""
        return "\n".join([
            "G90",
            "G1 Z%.1f F%d" % (SAFE_Z, Z_SPEED),
            "G1 X%.2f Y%.2f F%d" % (x, y, XY_SPEED),
            "G1 Z%.1f F%d" % (MEASURE_Z, APPROACH_SPEED),
            "M400",
        ])

    def _goto_reference(self, state):
        """Measure at the reference point (state ref_start or ref_end)."""
        self.state = "moving"
        self._set_status(_("Moving to the reference point..."))
        value = self.ref_start if state == "ref_start" else self.ref_end

        def arrived():
            self.state = state
            self._show_prompt(value)

        self._gcode(self._move_script(*REFERENCE), arrived)

    def _goto_point(self):
        """Measure the grid point at self.pos."""
        ix, iy = self.order[self.pos]
        self.state = "moving"
        self._set_status(_("Moving to point %d of %d...") % (
            self.pos + 1, len(self.order)))

        def arrived():
            self.state = "point"
            self._show_prompt(self.readings.get((ix, iy)))

        self._gcode(self._move_script(self.xs[ix], self.ys[iy]), arrived)

    # Measuring page
    def _show_run(self):
        """Build the measuring page: text on the left, keypad on the right."""
        self.w = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        main = Gtk.Box(spacing=self._dp(16), vexpand=True)
        for side in ("start", "end", "top"):
            getattr(main, "set_margin_" + side)(self._dp(16))
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=self._dp(8), hexpand=True)
        self.w["title"] = self._text("", "snap-title")
        self.w["status"] = self._text("", hexpand=True)
        self.w["entry"] = self._styled(
            Gtk.Label(label="", xalign=0), "snap-value")
        left.pack_start(self.w["title"], False, False, 0)
        left.pack_start(self.w["status"], False, False, 0)
        left.pack_start(self.w["entry"], False, False, self._dp(8))
        main.pack_start(left, True, True, 0)
        grid = Gtk.Grid(row_spacing=self._dp(6), column_spacing=self._dp(6),
                        valign=Gtk.Align.CENTER)
        for i, key in enumerate(KEYPAD + ["⌫"]):
            button = self._button(key, "secondary", self._key, key,
                                  small=True)
            grid.attach(button, i % 3, i // 3, 1, 1)
        self.w["keypad"] = grid
        main.pack_start(grid, False, False, 0)
        box.pack_start(main, True, True, 0)
        bar = Gtk.Box(spacing=self._dp(12))
        for side in ("start", "end", "bottom"):
            getattr(bar, "set_margin_" + side)(self._dp(12))
        bar.pack_start(self._button(_("Abort"), "secondary", self._ask_abort),
                       False, False, 0)
        self.w["next"] = self._button(_("Next"), "primary", self._next)
        bar.pack_end(self.w["next"], False, False, 0)
        self.w["previous"] = self._button(_("Previous"), "secondary",
                                          self._previous)
        bar.pack_end(self.w["previous"], False, False, 0)
        box.pack_end(bar, False, False, 0)
        self._set_page(box)
        self._update_buttons()

    def _set_status(self, text):
        """Show a waiting message (no reading expected)."""
        if "status" not in self.w:
            return
        self.w["title"].set_label(_("Please wait"))
        self.w["status"].set_label(text)
        self.w["entry"].set_label("")
        self._update_buttons()

    def _show_prompt(self, value):
        """Ask for the reading at the current position.

        Parameters
        ----------
        value : float or None
            Reading entered before at this position (going back), shown
            for editing.
        """
        if self.state == "ref_start":
            self.w["title"].set_label(_("Reference point"))
            self.w["status"].set_label(
                _("The bed is at Z=0 under X%g Y%g, where the J1 calibration"
                  " sets Z=0. Zero the dial here, then enter the reading"
                  " (0 if zeroed).") % REFERENCE)
        elif self.state == "ref_end":
            self.w["title"].set_label(_("Check the reference"))
            self.w["status"].set_label(
                _("Back at the reference point X%g Y%g. Enter the reading to"
                  " check that the dial did not move.") % REFERENCE)
        else:
            ix, iy = self.order[self.pos]
            self.w["title"].set_label(_("Point %d of %d") % (
                self.pos + 1, len(self.order)))
            self.w["status"].set_label(
                _("X %g, Y %g (column %d, row %d from the front). Enter the"
                  " dial reading in mm.") % (
                    self.xs[ix], self.ys[iy], ix + 1, iy + 1))
        self.entry = "" if value is None else ("%g" % value)
        self._show_entry()

    def _show_entry(self):
        self.w["entry"].set_label(_("Reading: %s mm") % (self.entry or "_"))
        self._update_buttons()

    def _entry_value(self):
        """The typed reading as a float, or None when not a number."""
        try:
            return float(self.entry)
        except ValueError:
            return None

    def _key(self, widget, key):
        """Keypad: digits, minus (first character only), point, backspace."""
        if self.state not in ("ref_start", "ref_end", "point") or self.busy:
            return
        if key == "⌫":
            self.entry = self.entry[:-1]
        elif len(self.entry) >= MAX_ENTRY:
            return
        elif key == "-":
            if self.entry:
                return
            self.entry = "-"
        elif key == ".":
            if "." in self.entry:
                return
            self.entry += "."
        else:
            self.entry += key
        self._show_entry()

    def _update_buttons(self):
        """Next needs a valid reading; nothing is clickable while moving."""
        if "next" not in self.w:
            return
        asking = (self.state in ("ref_start", "ref_end", "point")
                  and not self.busy)
        self.w["next"].set_sensitive(
            asking and self._entry_value() is not None)
        self.w["previous"].set_sensitive(asking and self.state == "point"
                                         and self.pos > 0)
        self.w["keypad"].set_sensitive(asking)

    def _next(self, widget):
        value = self._entry_value()
        if value is None or self.busy:
            return
        if self.state == "ref_start":
            self.ref_start = value
            self.pos = 0
            self._goto_point()
        elif self.state == "point":
            self.readings[self.order[self.pos]] = value
            if self.pos + 1 < len(self.order):
                self.pos += 1
                self._goto_point()
            else:
                self._goto_reference("ref_end")
        elif self.state == "ref_end":
            self.ref_end = value
            self.mesh = build_mesh(self.xs, self.ys, self.readings, self.sign)
            self._end_run(show_setup=False)
            self._show_result()

    def _previous(self, widget):
        if self.state == "point" and self.pos > 0 and not self.busy:
            value = self._entry_value()
            if value is not None:
                self.readings[self.order[self.pos]] = value
            self.pos -= 1
            self._goto_point()

    def _end_run(self, show_setup):
        """Lower the bed, park, heater off, restore the g-code state.

        Parameters
        ----------
        show_setup : bool
            Return to the setup page (abort or error).
        """
        self.running = False
        if self.heat_timer is not None:
            GLib.source_remove(self.heat_timer)
            self.heat_timer = None
        homed = self._stat("toolhead", "homed_axes", "") or ""
        lines = []
        if "z" in homed:
            lines += ["G90", "G1 Z%.1f F%d" % (SAFE_Z, Z_SPEED)]
        if "x" in homed:
            lines.append("SNAPMAKER_NOZZLE_PARK")
        lines += ["M140 S0",
                  "RESTORE_GCODE_STATE NAME=%s MOVE=0" % STATE_NAME]
        logging.info("Bed mesh: end (%s)", "; ".join(lines))
        # Not through _gcode: an error here must not start another end
        self._screen._ws.api.gcode_script("\n".join(lines))
        if show_setup:
            self._show_setup()

    def _ask_abort(self, widget):
        buttons = [
            {"name": _("Abort"), "response": Gtk.ResponseType.OK,
             "style": "dialog-error"},
            {"name": _("Continue"), "response": Gtk.ResponseType.CANCEL,
             "style": "dialog-info"},
        ]
        label = Gtk.Label(label=_("Stop measuring? The readings are lost."),
                          wrap=True, hexpand=True, vexpand=True,
                          justify=Gtk.Justification.CENTER)
        self._gtk.Dialog(_("Bed Mesh"), buttons, label, self._abort_response)

    def _abort_response(self, dialog, response_id):
        self._gtk.remove_dialog(dialog)
        if response_id == Gtk.ResponseType.OK and self.running:
            self._end_run(show_setup=True)

    # Result page
    def _show_result(self):
        """Deviations relative to the reference point, Save or Discard."""
        self.state = "result"
        self.w = {}
        values = [v for row in self.mesh for v in row]
        low, high = min(values), max(values)
        drift = self.sign * (self.ref_end - self.ref_start)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      spacing=self._dp(6), vexpand=True)
        for side in ("start", "end", "top"):
            getattr(box, "set_margin_" + side)(self._dp(16))
        box.pack_start(self._text(_("Bed deviation from the reference point"),
                                  "snap-title"), False, False, 0)
        box.pack_start(self._text(
            _("Lowest %+.3f, highest %+.3f, range %.3f mm (positive = bed"
              " higher, the nozzle is raised there)") % (
                low, high, high - low)), False, False, 0)
        drift_text = _("Reference drift: %+.3f mm") % drift
        if abs(drift) > DRIFT_WARNING:
            drift_text += _(" - more than %.2f mm: check the dial mount and"
                            " measure again") % DRIFT_WARNING
        box.pack_start(self._text(drift_text, "snap-warning"
                                  if abs(drift) > DRIFT_WARNING
                                  else "snap-progress"), False, False, 0)
        # The table as seen from the front of the printer: back row on top
        table = Gtk.Grid(column_spacing=self._dp(10),
                         row_spacing=self._dp(2))
        for col, x in enumerate(self.xs):
            table.attach(self._text("X%g" % x, "snap-progress"),
                         col + 1, 0, 1, 1)
        for row, iy in enumerate(reversed(range(len(self.ys)))):
            table.attach(self._text("Y%g" % self.ys[iy], "snap-progress"),
                         0, row + 1, 1, 1)
            for ix in range(len(self.xs)):
                table.attach(self._text("%+.2f" % self.mesh[iy][ix]),
                             ix + 1, row + 1, 1, 1)
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.add(table)
        box.pack_start(scroll, True, True, 0)
        bar = Gtk.Box(spacing=self._dp(12))
        bar.set_margin_bottom(self._dp(12))
        bar.pack_start(self._button(_("Discard"), "secondary",
                                    self._discard), False, False, 0)
        bar.pack_end(self._button(_("Save and Restart"), "primary",
                                  self._save), False, False, 0)
        box.pack_end(bar, False, False, 0)
        self._set_page(box)

    def _discard(self, widget):
        self.mesh = None
        self._show_setup()

    def _save(self, widget):
        """Write the profile and restart Klipper to load it."""
        info = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tool": _("left") if self.tool == 0 else _("right"),
            "bed_temp": self.bed_temp, "sign": self.sign,
            "ref_start": self.ref_start, "ref_end": self.ref_end,
        }
        text = mesh_file_text(self.xs, self.ys, self.mesh, self.readings,
                              info)
        try:
            write_mesh_file(text)
        except OSError as e:
            logging.exception("Bed mesh: writing %s", MESH_FILE)
            self._screen.show_popup_message(
                _("The mesh could not be saved: %s") % e)
            return
        logging.info("Bed mesh saved to %s", MESH_FILE)
        self._screen.show_popup_message(
            _("Bed mesh saved. Klipper restarts to load it."), level=1)
        self.mesh = None
        self._show_setup()
        self._screen._ws.api.gcode_script("RESTART")

    # KlipperScreen hooks
    def back(self):
        """Back button: ask before leaving a measurement."""
        if self.running:
            self._ask_abort(None)
            return True
        if self.state == "result":
            self._discard(None)
            return True
        return False

    def process_update(self, action, data):
        """Nothing to do: the bed temperature is polled while heating."""
        return
