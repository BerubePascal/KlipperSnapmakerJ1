"""Tests of the dial indicator bed mesh (klipperscreen/snapmaker_j1/bed_mesh.py).

LOCAL CHANGE of the fork BerubePascal/KlipperSnapmakerJ1.

Run from the repository root: ``python -m unittest tests.test_bed_mesh -v``
(or ``python -m unittest discover tests``). Only the calculations are tested
(grid, order, interpolation, mesh, profile file); the screen needs
KlipperScreen and GTK, which are replaced by empty stand-ins here.
"""
import configparser
import importlib.util
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "klipperscreen", "snapmaker_j1")


def _load_bed_mesh():
    """Import bed_mesh.py with stand-ins for gi, ks_includes and style.

    Returns
    -------
    module
        The bed_mesh module.
    """
    gi = types.ModuleType("gi")
    gi.require_version = lambda *args: None
    repository = types.ModuleType("gi.repository")
    for name in ("Gdk", "GLib", "Gtk", "Pango"):
        setattr(repository, name, types.SimpleNamespace())
    gi.repository = repository
    panel = types.ModuleType("ks_includes.screen_panel")
    panel.ScreenPanel = object
    sys.modules.update({
        "gi": gi, "gi.repository": repository,
        "ks_includes": types.ModuleType("ks_includes"),
        "ks_includes.screen_panel": panel,
    })
    package = types.ModuleType("snapmaker_j1_test")
    package.__path__ = [ADDON]
    package.style = types.ModuleType("snapmaker_j1_test.style")
    sys.modules["snapmaker_j1_test"] = package
    sys.modules["snapmaker_j1_test.style"] = package.style
    spec = importlib.util.spec_from_file_location(
        "snapmaker_j1_test.bed_mesh", os.path.join(ADDON, "bed_mesh.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BM = _load_bed_mesh()


class GridTest(unittest.TestCase):
    def test_grid_inside_print_area(self):
        xs, ys = BM.grid_points(7, 5, 15.)
        self.assertEqual(xs[0], 15.)
        self.assertEqual(xs[-1], 309.)
        self.assertEqual(len(xs), 7)
        self.assertEqual(ys, [15., 57.5, 100., 142.5, 185.])

    def test_serpentine_visits_every_point_once(self):
        order = BM.serpentine(3, 2)
        self.assertEqual(order, [(0, 0), (1, 0), (2, 0),
                                 (2, 1), (1, 1), (0, 1)])


class InterpolationTest(unittest.TestCase):
    def test_bilinear_corners_center_and_clamp(self):
        xs, ys = [0., 10.], [0., 10.]
        values = [[0., 1.], [2., 3.]]   # front row, back row
        self.assertAlmostEqual(BM.bilinear(xs, ys, values, 0, 0), 0.)
        self.assertAlmostEqual(BM.bilinear(xs, ys, values, 10, 10), 3.)
        self.assertAlmostEqual(BM.bilinear(xs, ys, values, 5, 5), 1.5)
        # Outside the grid: clamped to the edge, as Klipper
        self.assertAlmostEqual(BM.bilinear(xs, ys, values, 20, 20), 3.)

    def test_mesh_is_zero_at_reference(self):
        xs, ys = BM.grid_points(5, 5, 15.)
        readings = {(ix, iy): 0.01 * ix + 0.02 * iy + 0.5
                    for ix in range(5) for iy in range(5)}
        mesh = BM.build_mesh(xs, ys, readings, 1.)
        self.assertAlmostEqual(
            BM.bilinear(xs, ys, mesh, *BM.REFERENCE), 0., places=9)
        # Reversed sign: same shape, opposite direction
        reverse = BM.build_mesh(xs, ys, readings, -1.)
        self.assertAlmostEqual(reverse[0][0], -mesh[0][0], places=9)


class ProfileFileTest(unittest.TestCase):
    def test_file_has_klipper_profile_options(self):
        xs, ys = BM.grid_points(3, 2, 20.)
        readings = {(ix, iy): 0.1 * ix for ix in range(3) for iy in range(2)}
        mesh = BM.build_mesh(xs, ys, readings, 1.)
        info = {"date": "2026-11-23 12:00", "tool": "left", "bed_temp": 60,
                "sign": 1., "unit": "thou", "offset": (12., -30.),
                "ref_start": 0., "ref_end": 1.}
        text = BM.mesh_file_text(xs, ys, mesh, readings, info)
        parser = configparser.ConfigParser()
        parser.read_string(text)
        section = parser["bed_mesh dial"]
        self.assertEqual(section["version"], "1")
        self.assertEqual(section["x_count"], "3")
        self.assertEqual(section["y_count"], "2")
        self.assertEqual(float(section["min_x"]), 20.)
        self.assertEqual(float(section["max_y"]), 180.)
        rows = [r for r in section["points"].strip().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0].split(",")), 3)


class UnitsAndReachTest(unittest.TestCase):
    def test_thou_to_mm(self):
        self.assertAlmostEqual(BM.to_mm(20, "thou"), 0.508)
        self.assertAlmostEqual(BM.to_mm(0.5, "mm"), 0.5)
        self.assertEqual(BM.format_value(0.508, "thou"), "+20.0")
        self.assertEqual(BM.format_value(-0.1, "mm"), "-0.100")

    def test_dial_offset_moves_the_nozzle(self):
        self.assertEqual(BM.nozzle_position((100., 100.), (12., -30.)),
                         (88., 130.))

    def test_unreachable_points(self):
        # Left carriage: nozzle X at most 312 while the right one is parked
        points = [(300., 100.), (320., 100.)]
        self.assertEqual(BM.unreachable(points, (0., 0.), 0), [(320., 100.)])
        # A dial 20 mm right of the nozzle brings X320 back in reach
        self.assertEqual(BM.unreachable(points, (20., 0.), 0), [])
        # Dial 30 mm in front of the nozzle: the rear reference needs
        # nozzle Y217, beyond the Y travel
        self.assertEqual(BM.unreachable([BM.REFERENCE], (0., -30.), 0),
                         [BM.REFERENCE])


class FileTest(unittest.TestCase):
    def test_write_keeps_backup_and_restore_swaps(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "mesh.cfg")
            BM.write_mesh_file("first", path)
            BM.write_mesh_file("second", path)
            with open(path + ".bak") as f:
                self.assertEqual(f.read(), "first")
            BM.restore_previous_file(path)
            with open(path) as f:
                self.assertEqual(f.read(), "first")
            with open(path + ".bak") as f:
                self.assertEqual(f.read(), "second")
            # Restoring again swaps back
            BM.restore_previous_file(path)
            with open(path) as f:
                self.assertEqual(f.read(), "second")

    def test_saved_mesh_info(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "mesh.cfg")
            self.assertIsNone(BM.saved_mesh_info(path))
            BM.write_mesh_file("# Measured: 2026-11-23 12:00\n"
                               "# Toolhead: left, dial offset X+0 Y+0 mm\n",
                               path)
            self.assertEqual(BM.saved_mesh_info(path),
                             "2026-11-23 12:00, left, dial offset X+0 Y+0 mm")


if __name__ == "__main__":
    unittest.main()
