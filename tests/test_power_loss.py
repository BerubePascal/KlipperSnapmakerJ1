# Tests of when klippy/extras/snapmaker_j1_power_loss.py writes the
# recovery state: python -m unittest discover tests
import importlib.util
import os
import types
import unittest

_spec = importlib.util.spec_from_file_location(
    "j1_power_loss", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "klippy", "extras",
                                  "snapmaker_j1_power_loss.py"))
pl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pl)

STEP = pl.CHECKPOINT_TIME


def make(save_interval=30.):
    p = object.__new__(pl.SnapmakerJ1PowerLoss)
    clock = types.SimpleNamespace(now=0.)
    p.reactor = types.SimpleNamespace(monotonic=lambda: clock.now)
    toolhead = types.SimpleNamespace(
        print_time=0., lookahead=types.SimpleNamespace(get_last=lambda: None))
    p.printer = types.SimpleNamespace(lookup_object=lambda name: toolhead,
                                      lookup_objects=lambda module: [],
                                      is_shutdown=lambda: False)
    p.save_interval = save_interval
    p.print_seen = False
    p.checkpoints = []
    p.next_save_time = p.last_save_time = 0.
    p.last_saved_z = None
    p.z = 0.
    p.writes = []
    p._is_printing = lambda eventtime: True
    p._snapshot = lambda eventtime: {"position": [0., 0., p.z, 0.]}
    # Every checkpoint counts as executed at once
    p._executed_state = lambda eventtime: (p.checkpoints[-1]
                                           if p.checkpoints else None)
    p._write = lambda state: p.writes.append(clock.now)
    return p, clock


def run(p, clock, seconds, z_of_time):
    end = clock.now + seconds
    while clock.now < end:
        p.z = z_of_time(clock.now)
        p._checkpoint_event(clock.now)
        clock.now += STEP


class SaveRate(unittest.TestCase):
    def test_z_hop_writes_at_most_every_gap(self):
        # Z changes at every checkpoint (vase mode, Z hop): writes at most
        # every MIN_SAVE_GAP seconds, not four times a second
        p, clock = make()
        run(p, clock, 20., lambda t: round(t / STEP) % 2 * 0.4)
        gaps = [b - a for a, b in zip(p.writes, p.writes[1:])]
        self.assertTrue(gaps)
        self.assertGreaterEqual(min(gaps), pl.MIN_SAVE_GAP - 1e-9)
        self.assertLessEqual(len(p.writes), 20. / pl.MIN_SAVE_GAP + 1)

    def test_layer_change_soon_after_a_save_is_written_later(self):
        # A layer change 1 s after a save is not lost: it is written once
        # the gap has passed, long before the next interval save
        p, clock = make()
        run(p, clock, 1., lambda t: 0.2)            # first save at Z 0.2
        run(p, clock, 10., lambda t: 0.4)           # layer change
        self.assertEqual(p.last_saved_z, 0.4)
        self.assertLessEqual(p.writes[1] - p.writes[0],
                             pl.MIN_SAVE_GAP + STEP + 1e-9)


if __name__ == "__main__":
    unittest.main()
