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
Touch screen: Calibration -> "Bed Mesh (Dial Indicator)" -> Start opens this
screen.

- Main page: the current settings, the saved mesh, and the buttons
  Settings, Restore Previous (swap back to the mesh saved before the last
  one) and Start.
- Settings page: every value of the measurement (toolhead, grid, margin,
  dial offset from the nozzle, dial unit and direction, bed temperature,
  Z between points, measuring Z, speeds). Numbers are typed on a keypad.
  They are kept between sessions (add-on settings file).
- Start: the printer clears the active mesh, homes, selects the toolhead,
  heats the bed and waits, then puts the dial tip on the reference point
  X162 Y187 (where the J1 bed leveling sets Z=0) with the bed at the
  measuring Z. Zero the dial there.
- Each grid point (zigzag from the front-left corner): the bed lowers to the
  Z between points, the toolhead moves so that the dial tip is over the
  point, the bed comes back to the measuring Z. Type the reading, Next.
  The entry starts at 0 (or the reading typed before at that point),
  highlighted: the first key replaces it, so Next works at once for 0.
  Settings numbers open the same way, with the current value highlighted.
  Previous goes back one point. Abort (or Back) stops at any time: the bed
  lowers, the carriages park, the bed heater switches off and the mesh that
  was active before is loaded again; nothing is saved.
- At the end the dial returns to the reference point to check for drift,
  then the result table is shown. Save writes the profile (the previous file
  is kept as .bak) and restarts Klipper to load it.

Mesh values
-----------
Klipper's mesh value at a point is the height of the bed there (positive =
bed higher, the nozzle is raised). With "Plunger in = bed higher" (normal
dial indicators: the reading increases when the plunger is pushed in) the
readings are used as they are, otherwise reversed. Readings in thousandths
of an inch (typed as 20 for 0.020") are converted to mm. The saved mesh is
shifted so that it is exactly 0 at the reference point, where the J1
calibration defines Z=0; zeroing the dial there is only a convenience.

The mesh is stored at the positions of the dial tip (the grid points), and
Klipper applies it at the position of the nozzle: so the dial offset only
changes where the toolhead goes while measuring.

Main parts
----------
- ``SETTINGS``, ``CHOICES``: the parameters of the Settings page.
- ``grid_axis``, ``grid_points``, ``serpentine``: the measuring grid.
- ``nozzle_limits``, ``unreachable``: travel check with the dial offset.
- ``to_mm``, ``format_value``: dial units.
- ``bilinear``, ``build_mesh``: readings -> mesh relative to the reference.
- ``mesh_file_text``, ``write_mesh_file``, ``restore_previous_file``: the
  profile file.
- ``Panel``: the screen (main, settings, number entry, measuring, result).
"""
import datetime
import logging
import os

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from ks_includes.screen_panel import ScreenPanel

from . import settings as store
from . import style as S

# Name of the screen (KlipperScreen panel), opened from the calibration menu
PANEL = "snapmaker_bed_mesh"
# Calibration point 1 of [snapmaker_j1_probe] (rear center): the J1 bed
# leveling (SNAPMAKER_CAL_DATUM POINT=1) sets the Z origin there
REFERENCE = (162., 187.)
# Print area of the J1 (mm); the grid keeps the margin inside it
BED_X = (0., 324.)
BED_Y = (0., 200.)
# Nozzle X range of each carriage while the other one is parked at its
# endstop ([dual_carriage] safe_distance 24 mm, endstops -13 and ~337),
# with 1-2 mm to spare; Y range of [stepper_y]
NOZZLE_X = {0: (-13., 312.), 1: (12., 335.)}
NOZZLE_Y = (0., 202.)
# Grid presets (points in X, points in Y); the last choice is "Custom"
PRESETS = [(3, 3), (5, 5), (7, 5), (9, 7)]
MM_PER_THOU = .0254
# The bed counts as heated this close to its target (C)
BED_READY_MARGIN = 1.
# Speed of the last approach to the measuring Z (mm/s)
APPROACH_SPEED = 5.
# Seconds between screen saver resets while measuring (the shortest
# KlipperScreen blanking time is 60 s)
AWAKE_INTERVAL = 30
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
# Prefix of the settings in the add-on settings file
KEY = "bed_mesh_"
KEYPAD = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "-", "0", "."]
BACKSPACE = "⌫"
MAX_ENTRY = 8

# Numeric settings: key, title, unit, default, minimum, maximum, integer
SETTINGS = [
    ("x_count", "Custom grid: points in X", "", 7, 2, 15, True),
    ("y_count", "Custom grid: points in Y", "", 5, 2, 15, True),
    ("margin", "Edge margin of the grid", "mm", 15., 0., 60., False),
    ("offset_x", "Dial offset X (dial tip minus nozzle, + = right)", "mm",
     0., -80., 80., False),
    ("offset_y", "Dial offset Y (dial tip minus nozzle, + = back)", "mm",
     0., -80., 80., False),
    ("bed_temp", "Bed temperature (0 = no heating)", "°C", 60, 0, 100, True),
    ("safe_z", "Z between points (bed lowered)", "mm", 10., 1., 50., False),
    ("measure_z", "Measuring Z (bed raised)", "mm", 0., 0., 10., False),
    ("xy_speed", "XY speed", "mm/s", 100., 10., 250., False),
    ("z_speed", "Z speed", "mm/s", 10., 1., 10., False),
]
# Choice settings: key, title, [(value, label)], default
CHOICES = [
    ("tool", "Toolhead with the dial", [(0, "Left"), (1, "Right")], 0),
    ("preset", "Grid", [(i, "%d×%d" % p) for i, p in enumerate(PRESETS)]
     + [(len(PRESETS), "Custom")], 2),
    ("unit", "Dial unit", [("thou", "0.001 in"), ("mm", "mm")], "thou"),
    ("sign", "Plunger in = bed", [(1, "Higher"), (-1, "Lower")], 1),
]

# Look of the chosen option buttons (orange outline, as the primary color)
CHOSEN_CSS = b"""
.snapj1 button.snap-secondary.snap-chosen { border-color: #ff8a00; }
.snapj1 button.snap-secondary.snap-chosen label { color: #ff8a00; }
"""
_css_installed = []


def load_settings():
    """All settings with their saved values (defaults when not saved).

    Returns
    -------
    dict
        ``{key: value}`` for every entry of ``SETTINGS`` and ``CHOICES``.
    """
    values = {}
    for key, _title, _unit, default, low, high, integer in SETTINGS:
        value = store.get(KEY + key, default)
        try:
            value = min(max(float(value), low), high)
        except (TypeError, ValueError):
            value = default
        values[key] = int(round(value)) if integer else value
    for key, _title, options, default in CHOICES:
        value = store.get(KEY + key, default)
        values[key] = value if value in [v for v, _l in options] else default
    return values


def grid_counts(values):
    """Points in X and Y of the chosen grid (preset or custom)."""
    if values["preset"] < len(PRESETS):
        return PRESETS[values["preset"]]
    return values["x_count"], values["y_count"]


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
    """Positions of the measuring grid (dial tip) inside the print area.

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


def nozzle_position(point, offset):
    """Where the nozzle goes so that the dial tip is over a point.

    Parameters
    ----------
    point : tuple of (float, float)
        Dial tip position (mm).
    offset : tuple of (float, float)
        Dial tip minus nozzle position (mm).

    Returns
    -------
    tuple of (float, float)
        Nozzle position (mm).
    """
    return point[0] - offset[0], point[1] - offset[1]


def unreachable(points, offset, tool):
    """Dial positions the nozzle of a carriage cannot reach.

    Parameters
    ----------
    points : list of tuple of (float, float)
        Dial tip positions (mm).
    offset : tuple of (float, float)
        Dial tip minus nozzle position (mm).
    tool : int
        0 for the left carriage, 1 for the right one.

    Returns
    -------
    list of tuple of (float, float)
        The dial positions out of reach (empty when all are fine).
    """
    x_low, x_high = NOZZLE_X[tool]
    bad = []
    for point in points:
        x, y = nozzle_position(point, offset)
        if not (x_low <= x <= x_high and NOZZLE_Y[0] <= y <= NOZZLE_Y[1]):
            bad.append(point)
    return bad


def to_mm(value, unit):
    """A dial reading in mm.

    Parameters
    ----------
    value : float
        Reading as typed: thousandths of an inch (unit ``thou``, 20 means
        0.020") or mm.
    unit : str
        ``thou`` or ``mm``.

    Returns
    -------
    float
        The reading in mm.
    """
    return value * MM_PER_THOU if unit == "thou" else value


def format_value(mm, unit, signed=True):
    """A length in the dial unit for display (thou with 1 decimal, mm 3).

    Parameters
    ----------
    mm : float
        Length in mm.
    unit : str
        ``thou`` or ``mm``.
    signed : bool
        Always show the sign.

    Returns
    -------
    str
        For example ``+12.5`` (thou) or ``+0.318`` (mm), without the unit.
    """
    if unit == "thou":
        return ("%+.1f" if signed else "%.1f") % (mm / MM_PER_THOU)
    return ("%+.3f" if signed else "%.3f") % mm


def unit_name(unit):
    """Short unit label for display."""
    return _("thou") if unit == "thou" else "mm"


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


def build_mesh(xs, ys, readings_mm, sign):
    """Turn dial readings into a mesh that is 0 at the reference point.

    Parameters
    ----------
    xs, ys : list of float
        Grid positions.
    readings_mm : dict
        ``{(ix, iy): reading}`` in mm for every grid point.
    sign : float
        1 when a higher reading means a higher bed (plunger pushed in),
        -1 otherwise.

    Returns
    -------
    list of list of float
        ``mesh[iy][ix]`` (mm, positive = bed higher than at the reference
        point), rows from the front.
    """
    raw = [[sign * readings_mm[(ix, iy)] for ix in range(len(xs))]
           for iy in range(len(ys))]
    zero = bilinear(xs, ys, raw, *REFERENCE)
    return [[value - zero for value in row] for row in raw]


def mesh_file_text(xs, ys, mesh, readings, info):
    """The profile file: Klipper's stored-profile format plus comments.

    Parameters
    ----------
    xs, ys : list of float
        Grid positions (dial tip).
    mesh : list of list of float
        Mesh values in mm (``build_mesh``), rows from the front.
    readings : dict
        Readings as typed ``{(ix, iy): value}``, kept as comments.
    info : dict
        ``date``, ``tool``, ``bed_temp``, ``sign``, ``unit``, ``offset``,
        ``ref_start``, ``ref_end`` (as typed) for the header comments.

    Returns
    -------
    str
        Content of ``snapmaker_j1_bed_mesh.cfg``.

    Notes
    -----
    ``mesh_x_pps``/``mesh_y_pps`` 0 and ``algo = direct``: no upsampling,
    Klipper interpolates linearly between the measured points.
    """
    unit = "0.001 in" if info["unit"] == "thou" else "mm"
    lines = [
        "# Bed mesh measured with a dial indicator (touch screen:",
        "# Calibration -> Bed Mesh (Dial Indicator); written by",
        "# klipperscreen/snapmaker_j1/bed_mesh.py of the fork). Prints load it",
        "# with LOAD_DIAL_MESH (printer.cfg). Measuring again replaces this",
        "# file; the previous one is kept as snapmaker_j1_bed_mesh.cfg.bak.",
        "#",
        "# Measured: %s" % info["date"],
        "# Toolhead: %s, dial offset X%+g Y%+g mm, bed %d C" % (
            info["tool"], info["offset"][0], info["offset"][1],
            info["bed_temp"]),
        "# Dial: readings in %s, plunger in = bed %s" % (
            unit, "higher" if info["sign"] > 0 else "lower"),
        "# Reference X%g Y%g: %g at the start, %g at the end (%s)" % (
            REFERENCE[0], REFERENCE[1], info["ref_start"], info["ref_end"],
            unit),
        "# Readings as typed (%s), rows from the front, X left to right:"
        % unit,
        "#   X: " + ", ".join("%g" % x for x in xs),
    ]
    for iy, y in enumerate(ys):
        lines.append("#   Y%g: " % y + ", ".join(
            "%g" % readings[(ix, iy)] for ix in range(len(xs))))
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


def write_mesh_file(text, path=MESH_FILE):
    """Write the profile file atomically, keeping the previous one as .bak.

    Parameters
    ----------
    text : str
        File content (``mesh_file_text``).
    path : str
        File to write (the default is the one printer.cfg includes).

    Raises
    ------
    OSError
        When the file cannot be written.
    """
    if os.path.exists(path):
        os.replace(path, path + ".bak")
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def restore_previous_file(path=MESH_FILE):
    """Swap the profile file with its .bak (restoring the previous mesh).

    Swapping (rather than overwriting) lets a second restore undo the first.
    Without a current file, the .bak simply becomes the file.

    Parameters
    ----------
    path : str
        The profile file.

    Raises
    ------
    OSError
        When there is no .bak or the files cannot be renamed.
    """
    backup = path + ".bak"
    if not os.path.exists(backup):
        raise OSError("no previous mesh (%s)" % backup)
    if os.path.exists(path):
        os.replace(path, path + ".swap")
        os.replace(backup, path)
        os.replace(path + ".swap", backup)
    else:
        os.replace(backup, path)


def saved_mesh_info(path=MESH_FILE):
    """The "Measured:" and "Toolhead:" lines of a saved profile file.

    Parameters
    ----------
    path : str
        The profile file.

    Returns
    -------
    str or None
        ``"<date>, <toolhead line>"``, or None without a file.
    """
    try:
        with open(path) as f:
            lines = [line[2:].strip() for line in f
                     if line.startswith(("# Measured:", "# Toolhead:"))]
    except OSError:
        return None
    return ", ".join(line.split(":", 1)[1].strip() for line in lines) or "?"


class Panel(ScreenPanel):
    """The bed mesh screen: main, settings, number entry, measuring, result.

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
        self.values = load_settings()
        # Measurement
        self.running = False
        self.page = "main"
        self.state = None
        self.xs = self.ys = []
        self.order = []
        self.pos = 0
        self.readings = {}
        self.ref_start = self.ref_end = None
        self.previous_profile = ""
        self.mesh = None
        self.busy = False
        self.heat_timer = None
        self.awake_timer = None
        # Keypad entry and the page that uses it; a "selected" entry (shown
        # highlighted) is replaced by the first key typed
        self.entry = ""
        self.selected = False
        self.on_entry = None
        self.number_key = None
        self.w = {}
        self._show_main()

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
        # Plain GTK buttons don't restart KlipperScreen's screen saver
        # timer (only its own buttons do): every tap here counts as activity
        button.connect("clicked", self._keep_awake)
        button.connect("clicked", callback, *args)
        return button

    def _keep_awake(self, *args):
        """Count as activity: screen blanking timer and case light dimming.

        Restarts KlipperScreen's screen saver timer (as a touch on one of
        its own buttons would) and the add-on's case light dim timer (which
        also brings a dimmed light back).

        Returns
        -------
        bool
            Always True, so it can run as a repeating GLib timer.
        """
        screen = self._screen
        reset = getattr(screen, "reset_screensaver_timeout", None)
        if reset is None:
            reset = getattr(getattr(screen, "screensaver", None),
                            "reset_timeout", None)
        if reset is not None:
            try:
                reset()
            except TypeError:
                # Some versions take the widget of the signal
                reset(None)
        elif not getattr(self, "_reset_missing_logged", False):
            self._reset_missing_logged = True
            logging.warning("Bed mesh: KlipperScreen has no screen saver"
                            " reset; the screen may blank while measuring")
        light = getattr(screen, "snapmaker_case_light", None)
        if light is not None:
            light.activity()
        return True

    def _text(self, text, *classes, **kwargs):
        """A wrapping label."""
        label = Gtk.Label(label=text, wrap=True, xalign=0,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, **kwargs)
        return self._styled(label, *classes)

    def _page_box(self):
        """A vertical page box with the usual margins."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      spacing=self._dp(6), vexpand=True)
        for side in ("start", "end", "top"):
            getattr(box, "set_margin_" + side)(self._dp(16))
        return box

    def _bar(self):
        """A bottom button bar."""
        bar = Gtk.Box(spacing=self._dp(12))
        bar.set_margin_bottom(self._dp(12))
        return bar

    def _set_page(self, name, child):
        """Replace the content of the screen with a new page."""
        self.page = name
        for old in self.content.get_children():
            self.content.remove(old)
        root = Gtk.EventBox(hexpand=True, vexpand=True)
        self._styled(root, "snapj1")
        root.add(child)
        self.content.add(root)
        root.show_all()

    def _stat(self, obj, field, default=None):
        value = self._printer.get_stat(obj, field)
        return default if value in ({}, None) else value

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
            if not self.running:
                # Aborted meanwhile: the end script is already queued
                return
            if "error" in result:
                message = result["error"].get("message", str(result["error"]))
                logging.error("Bed mesh: %s", message)
                self._screen.show_popup_message(
                    _("Bed mesh stopped: %s") % message)
                self._end_run()
                return
            self._update_buttons()
            if callback is not None:
                callback()

        self._screen._ws.api.gcode_script(script, done)

    def _save_value(self, key, value):
        """Keep a setting (memory and add-on settings file)."""
        self.values[key] = value
        store.save(KEY + key, value)

    # Keypad (number entry and dial readings)
    def _keypad(self):
        """A 3-column keypad calling self._key."""
        grid = Gtk.Grid(row_spacing=self._dp(6), column_spacing=self._dp(6),
                        valign=Gtk.Align.CENTER)
        for i, key in enumerate(KEYPAD + [BACKSPACE]):
            grid.attach(self._button(key, "secondary", self._key, key,
                                     small=True), i % 3, i // 3, 1, 1)
        return grid

    def _key(self, widget, key):
        """Digits, minus (first character only), point, backspace.

        While the entry is selected (just opened, showing the current value
        highlighted), the first key replaces it: a digit, minus or point
        starts a new number, backspace clears it.
        """
        if self.on_entry is None or self.busy:
            return
        if self.selected:
            self.selected = False
            self.entry = ""
            if key == BACKSPACE:
                self.on_entry()
                return
        if key == BACKSPACE:
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
        self.on_entry()

    def _entry_value(self):
        """The typed entry as a float, or None when not a number."""
        try:
            return float(self.entry)
        except ValueError:
            return None

    def _entry_markup(self):
        """The entry for a label (Pango markup): highlighted while selected,
        an underscore when empty."""
        text = GLib.markup_escape_text(self.entry or "_")
        if self.selected:
            return ('<span background="#ff8a00" foreground="#1a1c28">'
                    '&#160;%s&#160;</span>' % text)
        return text

    # Main page
    def _summary(self):
        """Text of the current settings."""
        v = self.values
        x_count, y_count = grid_counts(v)
        tool = _("Left") if v["tool"] == 0 else _("Right")
        lines = [
            _("Toolhead: %s · Grid: %d×%d (%d points), margin %g mm") % (
                tool, x_count, y_count, x_count * y_count, v["margin"]),
            _("Dial: offset X%+g Y%+g mm, readings in %s, plunger in = bed"
              " %s") % (v["offset_x"], v["offset_y"],
                        _("0.001 in") if v["unit"] == "thou" else "mm",
                        _("higher") if v["sign"] > 0 else _("lower")),
            _("Bed %s · Z between points %g mm · measuring at Z %g") % (
                ("%d°C" % v["bed_temp"]) if v["bed_temp"] else _("not heated"),
                v["safe_z"], v["measure_z"]),
        ]
        return "\n".join(lines)

    def _show_main(self):
        """The process page: settings summary, saved mesh, Start."""
        self.on_entry = None
        self.w = {}
        box = self._page_box()
        box.pack_start(self._text(_("Bed Mesh (Dial Indicator)"),
                                  "snap-title"), False, False, 0)
        box.pack_start(self._text(_(
            "Remove the hotend of the toolhead carrying the dial: the bed"
            " comes up to the measuring Z at every point. Zero the dial at"
            " the reference point X%g Y%g, where the J1 sets Z=0.")
            % REFERENCE, "snap-progress"), False, False, 0)
        box.pack_start(self._text(self._summary()), False, False,
                       self._dp(4))
        info = saved_mesh_info()
        box.pack_start(self._text(
            _("Saved mesh: %s") % info if info else _("No mesh saved yet."),
            "snap-progress"), False, False, 0)
        bar = self._bar()
        bar.pack_start(self._button(_("Settings"), "secondary",
                                    self._show_settings), False, False, 0)
        if os.path.exists(MESH_FILE + ".bak"):
            bar.pack_start(self._button(_("Restore Previous"), "secondary",
                                        self._ask_restore), False, False, 0)
        bar.pack_end(self._button(_("Start"), "primary", self._start),
                     False, False, 0)
        box.pack_end(bar, False, False, 0)
        self._set_page("main", box)

    def _ask_restore(self, widget):
        buttons = [
            {"name": _("Restore"), "response": Gtk.ResponseType.OK,
             "style": "dialog-error"},
            {"name": _("Cancel"), "response": Gtk.ResponseType.CANCEL,
             "style": "dialog-info"},
        ]
        label = Gtk.Label(
            label=_("Go back to the mesh saved before the last one? Klipper"
                    " restarts to load it. Restoring again swaps them back."),
            wrap=True, hexpand=True, vexpand=True,
            justify=Gtk.Justification.CENTER)
        self._gtk.Dialog(_("Bed Mesh"), buttons, label, self._restore_response)

    def _restore_response(self, dialog, response_id):
        self._gtk.remove_dialog(dialog)
        if response_id != Gtk.ResponseType.OK:
            return
        if self._stat("print_stats", "state") in ("printing", "paused"):
            self._screen.show_popup_message(
                _("Not available while a print is running."))
            return
        try:
            restore_previous_file()
        except OSError as e:
            logging.exception("Bed mesh: restoring the previous file")
            self._screen.show_popup_message(
                _("The previous mesh could not be restored: %s") % e)
            return
        self._screen.show_popup_message(
            _("Previous mesh restored. Klipper restarts to load it."),
            level=1)
        self._show_main()
        self._screen._ws.api.gcode_script("RESTART")

    # Settings page
    def _show_settings(self, widget=None):
        """Every setting: option buttons and numbers (tap to type)."""
        self.on_entry = None
        self.w = {}
        box = self._page_box()
        box.pack_start(self._text(_("Settings"), "snap-title"),
                       False, False, 0)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=self._dp(6))
        for key, title, options, _default in CHOICES:
            row = Gtk.Box(spacing=self._dp(8))
            row.pack_start(self._text(_(title), hexpand=True), True, True, 0)
            for value, label in options:
                button = self._button(_(label), "secondary",
                                      self._choose, key, value, small=True)
                if self.values[key] == value:
                    self._styled(button, "snap-chosen")
                row.pack_start(button, False, False, 0)
            rows.pack_start(row, False, False, 0)
        custom = self.values["preset"] == len(PRESETS)
        for key, title, unit, _d, _low, _high, integer in SETTINGS:
            row = Gtk.Box(spacing=self._dp(8))
            row.pack_start(self._text(_(title), hexpand=True), True, True, 0)
            value = self.values[key]
            text = ("%d" % value if integer else "%g" % value)
            button = self._button("%s %s" % (text, unit) if unit else text,
                                  "secondary", self._show_number, key)
            # The custom grid counts only matter with "Custom"
            if key in ("x_count", "y_count"):
                button.set_sensitive(custom)
            row.pack_start(button, False, False, 0)
            rows.pack_start(row, False, False, 0)
        scroll = self._gtk.ScrolledWindow()  # touch drag scrolling
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(rows)
        box.pack_start(scroll, True, True, 0)
        bar = self._bar()
        bar.pack_end(self._button(_("Done"), "primary",
                                  lambda w: self._show_main()),
                     False, False, 0)
        box.pack_end(bar, False, False, 0)
        self._set_page("settings", box)

    def _choose(self, widget, key, value):
        self._save_value(key, value)
        self._show_settings()

    def _setting(self, key):
        """The SETTINGS entry of a key."""
        return next(s for s in SETTINGS if s[0] == key)

    def _show_number(self, widget, key):
        """Number entry page for one numeric setting."""
        _key, title, unit, _d, low, high, integer = self._setting(key)
        self.number_key = key
        self.w = {}
        box = self._page_box()
        main = Gtk.Box(spacing=self._dp(16), vexpand=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=self._dp(8), hexpand=True)
        left.pack_start(self._text(_(title), "snap-title"), False, False, 0)
        left.pack_start(self._text(
            (_("Whole number from %d to %d") % (low, high)) if integer else
            (_("From %g to %g %s") % (low, high, unit)), "snap-progress"),
            False, False, 0)
        self.w["entry"] = self._styled(Gtk.Label(label="", xalign=0),
                                       "snap-value")
        left.pack_start(self.w["entry"], False, False, self._dp(8))
        main.pack_start(left, True, True, 0)
        main.pack_start(self._keypad(), False, False, 0)
        box.pack_start(main, True, True, 0)
        bar = self._bar()
        bar.pack_start(self._button(_("Cancel"), "secondary",
                                    lambda w: self._show_settings()),
                       False, False, 0)
        self.w["ok"] = self._button(_("OK"), "primary", self._number_ok)
        bar.pack_end(self.w["ok"], False, False, 0)
        box.pack_end(bar, False, False, 0)
        value = self.values[key]
        self.entry = "%d" % value if integer else "%g" % value
        # The current value is selected: typing replaces it
        self.selected = True
        self.on_entry = self._number_changed
        self._set_page("number", box)
        self._number_changed()

    def _number_valid(self):
        """The typed number when it is in range (and whole if needed)."""
        _key, _t, _u, _d, low, high, integer = self._setting(self.number_key)
        value = self._entry_value()
        if value is None or not low <= value <= high:
            return None
        if integer and value != int(value):
            return None
        return int(value) if integer else value

    def _number_changed(self):
        unit = self._setting(self.number_key)[2]
        self.w["entry"].set_markup("%s %s" % (
            self._entry_markup(), GLib.markup_escape_text(unit)))
        self.w["ok"].set_sensitive(self._number_valid() is not None)

    def _number_ok(self, widget):
        value = self._number_valid()
        if value is None:
            return
        self._save_value(self.number_key, value)
        self._show_settings()

    # Measuring
    def _start(self, widget):
        """Check the printer and the reach, then prepare the measurement."""
        if self._stat("print_stats", "state") in ("printing", "paused"):
            self._screen.show_popup_message(
                _("Not available while a print is running."))
            return
        if self._stat("dual_carriage", "carriage_1", "") in ("COPY",
                                                             "MIRROR"):
            self._screen.show_popup_message(
                _("Not available in duplication or mirror mode."))
            return
        v = self.values
        x_count, y_count = grid_counts(v)
        self.xs, self.ys = grid_points(x_count, y_count, v["margin"])
        offset = (v["offset_x"], v["offset_y"])
        points = [REFERENCE] + [(x, y) for y in self.ys for x in self.xs]
        bad = unreachable(points, offset, v["tool"])
        if bad:
            self._screen.show_popup_message(
                _("With this toolhead and dial offset the nozzle can't reach"
                  " %d point(s), e.g. X%g Y%g. Increase the margin or check"
                  " the offset.") % (len(bad), bad[0][0], bad[0][1]))
            return
        self.order = serpentine(x_count, y_count)
        self.readings = {}
        self.pos = 0
        self.ref_start = self.ref_end = None
        self.mesh = None
        self.running = True
        # The screen (and a case light dimmed with it) stays on for the
        # whole measurement, also while homing, heating and moving
        if self.awake_timer is None:
            self.awake_timer = GLib.timeout_add_seconds(
                AWAKE_INTERVAL, self._keep_awake)
        self._show_run()
        self._set_status(_("Homing and heating the bed..."))
        # The mesh active now comes back when the measurement is aborted
        self.previous_profile = ""

        def got(result, method, params, *args):
            status = (result.get("result", {}).get("status", {})
                      if isinstance(result, dict) else {})
            self.previous_profile = (status.get("bed_mesh", {})
                                     .get("profile_name") or "")
            logging.info("Bed mesh: active profile before: %r",
                         self.previous_profile)

        self._screen._ws.send_method(
            "printer.objects.query",
            {"objects": {"bed_mesh": ["profile_name"]}}, got)
        lines = [
            "SAVE_GCODE_STATE NAME=%s" % STATE_NAME,
            # The measurement must see the bed without any correction
            "BED_MESH_CLEAR",
            "_SNAPMAKER_RESET_MODE",
            "SET_GCODE_OFFSET X=0 Y=0 Z=0",
            "M140 S%d" % v["bed_temp"],
            "G28",
            "T%d" % v["tool"],
            # T1 applies its Y offset; the grid is in machine coordinates
            "SET_GCODE_OFFSET X=0 Y=0 Z=0",
            "G90",
            "G1 Z%g F%d" % (v["safe_z"], v["z_speed"] * 60),
            "M400",
        ]
        self._gcode("\n".join(lines), self._wait_heat)

    def _wait_heat(self):
        """Poll the bed temperature until it reached its target."""
        if not self.values["bed_temp"]:
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
        target = self.values["bed_temp"]
        self._set_status(_("Heating the bed: %.1f / %d°C") % (temp, target))
        if temp >= target - BED_READY_MARGIN:
            if self.heat_timer is not None:
                GLib.source_remove(self.heat_timer)
                self.heat_timer = None
            self._goto_reference("ref_start")
            return False
        return True

    def _move_script(self, point):
        """Bed down, nozzle so that the dial tip is over point, bed up."""
        v = self.values
        x, y = nozzle_position(point, (v["offset_x"], v["offset_y"]))
        approach = min(APPROACH_SPEED, v["z_speed"])
        return "\n".join([
            "G90",
            "G1 Z%g F%d" % (v["safe_z"], v["z_speed"] * 60),
            "G1 X%.2f Y%.2f F%d" % (x, y, v["xy_speed"] * 60),
            "G1 Z%g F%d" % (v["measure_z"], approach * 60),
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

        self._gcode(self._move_script(REFERENCE), arrived)

    def _goto_point(self):
        """Measure the grid point at self.pos."""
        ix, iy = self.order[self.pos]
        self.state = "moving"
        self._set_status(_("Moving to point %d of %d...") % (
            self.pos + 1, len(self.order)))

        def arrived():
            self.state = "point"
            self._show_prompt(self.readings.get((ix, iy)))

        self._gcode(self._move_script((self.xs[ix], self.ys[iy])), arrived)

    # Measuring page
    def _show_run(self):
        """Measuring page: text on the left, keypad on the right."""
        self.w = {}
        self.on_entry = None
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
        self.w["keypad"] = self._keypad()
        main.pack_start(self.w["keypad"], False, False, 0)
        box.pack_start(main, True, True, 0)
        bar = self._bar()
        for side in ("start", "end"):
            getattr(bar, "set_margin_" + side)(self._dp(12))
        # Abort works at any time, also while the printer moves or heats
        bar.pack_start(self._button(_("Abort"), "secondary", self._ask_abort),
                       False, False, 0)
        self.w["next"] = self._button(_("Next"), "primary", self._next)
        bar.pack_end(self.w["next"], False, False, 0)
        self.w["previous"] = self._button(_("Previous"), "secondary",
                                          self._previous)
        bar.pack_end(self.w["previous"], False, False, 0)
        box.pack_end(bar, False, False, 0)
        self._set_page("run", box)
        self._update_buttons()

    def _set_status(self, text):
        """Show a waiting message (no reading expected)."""
        if self.page != "run":
            return
        self.on_entry = None
        self.w["title"].set_label(_("Please wait"))
        self.w["status"].set_label(text)
        self.w["entry"].set_label("")
        self._update_buttons()

    def _show_prompt(self, value):
        """Ask for the dial reading at the current position.

        Parameters
        ----------
        value : float or None
            Reading typed before at this position (going back), shown for
            editing.
        """
        unit = unit_name(self.values["unit"])
        if self.state == "ref_start":
            self.w["title"].set_label(_("Reference point"))
            self.w["status"].set_label(
                _("The dial tip is over X%g Y%g with the bed at Z %g, where"
                  " the J1 calibration sets Z=0. Zero the dial, then enter"
                  " the reading (0 if zeroed).") % (
                    REFERENCE[0], REFERENCE[1], self.values["measure_z"]))
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
                _("Dial tip at X %g, Y %g (column %d, row %d from the"
                  " front). Enter the reading in %s.") % (
                    self.xs[ix], self.ys[iy], ix + 1, iy + 1, unit))
        # 0 by default (Next is active at once), or the reading typed before
        # at this position; either way selected, so typing replaces it
        self.entry = "0" if value is None else ("%g" % value)
        self.selected = True
        self.on_entry = self._reading_changed
        self._reading_changed()

    def _reading_changed(self):
        unit = self.values["unit"]
        text = GLib.markup_escape_text(_("Reading: %s %s")) % (
            self._entry_markup(), GLib.markup_escape_text(unit_name(unit)))
        value = self._entry_value()
        if unit == "thou" and value is not None:
            text += "  (%.4f in, %.3f mm)" % (value / 1000.,
                                               to_mm(value, unit))
        self.w["entry"].set_markup(text)
        self._update_buttons()

    def _update_buttons(self):
        """Next needs a valid reading; keys only while a reading is asked."""
        if self.page != "run":
            return
        asking = self.on_entry is not None and not self.busy
        self.w["next"].set_sensitive(
            asking and self._entry_value() is not None)
        self.w["previous"].set_sensitive(asking and self.state == "point"
                                         and self.pos > 0)
        self.w["keypad"].set_sensitive(asking)

    def _next(self, widget):
        value = self._entry_value()
        if value is None or self.busy or self.on_entry is None:
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
            unit = self.values["unit"]
            readings_mm = {k: to_mm(r, unit) for k, r in self.readings.items()}
            self.mesh = build_mesh(self.xs, self.ys, readings_mm,
                                   self.values["sign"])
            self._end_run()
            self._show_result()

    def _previous(self, widget):
        if self.state == "point" and self.pos > 0 and not self.busy:
            value = self._entry_value()
            if value is not None:
                self.readings[self.order[self.pos]] = value
            self.pos -= 1
            self._goto_point()

    def _end_run(self):
        """Lower the bed, park, heater off, restore state and the old mesh.

        The mesh active before the measurement is loaded again in every case
        (abort, error or complete run): it stays the one in use until Save
        writes the new one and restarts Klipper.
        """
        self.running = False
        self.on_entry = None
        if self.awake_timer is not None:
            GLib.source_remove(self.awake_timer)
            self.awake_timer = None
        if self.heat_timer is not None:
            GLib.source_remove(self.heat_timer)
            self.heat_timer = None
        homed = self._stat("toolhead", "homed_axes", "") or ""
        lines = []
        if "z" in homed:
            lines += ["G90", "G1 Z%g F%d" % (self.values["safe_z"],
                                             self.values["z_speed"] * 60)]
        if "x" in homed:
            lines.append("SNAPMAKER_NOZZLE_PARK")
        lines += ["M140 S0",
                  "RESTORE_GCODE_STATE NAME=%s MOVE=0" % STATE_NAME]
        if self.previous_profile:
            lines.append("BED_MESH_PROFILE LOAD=%s" % self.previous_profile)
        logging.info("Bed mesh: end (%s)", "; ".join(lines))
        # Queued after whatever runs now (homing, a move); not through
        # _gcode, so an error here does not start another end
        self._screen._ws.api.gcode_script("\n".join(lines))

    def _ask_abort(self, widget):
        buttons = [
            {"name": _("Abort"), "response": Gtk.ResponseType.OK,
             "style": "dialog-error"},
            {"name": _("Continue"), "response": Gtk.ResponseType.CANCEL,
             "style": "dialog-info"},
        ]
        label = Gtk.Label(
            label=_("Stop measuring? The readings are lost; the bed lowers,"
                    " the carriages park and the previous mesh stays."),
            wrap=True, hexpand=True, vexpand=True,
            justify=Gtk.Justification.CENTER)
        self._gtk.Dialog(_("Bed Mesh"), buttons, label, self._abort_response)

    def _abort_response(self, dialog, response_id):
        self._gtk.remove_dialog(dialog)
        if response_id == Gtk.ResponseType.OK and self.running:
            self._end_run()
            self._show_main()

    # Result page
    def _show_result(self):
        """Deviations relative to the reference point; Save or Discard."""
        self.w = {}
        unit = self.values["unit"]
        name = unit_name(unit)
        values = [v for row in self.mesh for v in row]
        low, high = min(values), max(values)
        drift = self.values["sign"] * (to_mm(self.ref_end, unit)
                                       - to_mm(self.ref_start, unit))
        box = self._page_box()
        box.pack_start(self._text(
            _("Bed deviation from the reference point (%s)") % name,
            "snap-title"), False, False, 0)
        box.pack_start(self._text(
            _("Lowest %s, highest %s, range %s %s (%.3f mm). Positive = bed"
              " higher, the nozzle is raised there.") % (
                format_value(low, unit), format_value(high, unit),
                format_value(high - low, unit, signed=False), name,
                high - low)), False, False, 0)
        warn = abs(drift) > DRIFT_WARNING
        drift_text = _("Reference drift: %s %s") % (
            format_value(drift, unit), name)
        if warn:
            drift_text += _(" - more than %.2f mm: check the dial mount and"
                            " measure again") % DRIFT_WARNING
        box.pack_start(self._text(drift_text, "snap-warning" if warn
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
                table.attach(self._text(format_value(self.mesh[iy][ix],
                                                     unit)),
                             ix + 1, row + 1, 1, 1)
        scroll = self._gtk.ScrolledWindow()  # touch drag scrolling
        # Large grids are wider than the screen: scroll both ways
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(table)
        box.pack_start(scroll, True, True, 0)
        bar = self._bar()
        bar.pack_start(self._button(_("Discard"), "secondary",
                                    self._discard), False, False, 0)
        bar.pack_end(self._button(_("Save and Restart"), "primary",
                                  self._save), False, False, 0)
        box.pack_end(bar, False, False, 0)
        self._set_page("result", box)

    def _discard(self, widget):
        self.mesh = None
        self._show_main()

    def _save(self, widget):
        """Write the profile (previous file kept as .bak), restart Klipper."""
        v = self.values
        info = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tool": "left" if v["tool"] == 0 else "right",
            "offset": (v["offset_x"], v["offset_y"]),
            "bed_temp": v["bed_temp"], "sign": v["sign"], "unit": v["unit"],
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
        self._show_main()
        self._screen._ws.api.gcode_script("RESTART")

    # KlipperScreen hooks
    def back(self):
        """Back button: abort a measurement, or go back one page."""
        if self.running:
            self._ask_abort(None)
            return True
        if self.page == "number":
            self._show_settings()
            return True
        if self.page in ("settings", "result"):
            self._show_main()
            return True
        return False

    def process_update(self, action, data):
        """Nothing to do: the bed temperature is polled while heating."""
        return
