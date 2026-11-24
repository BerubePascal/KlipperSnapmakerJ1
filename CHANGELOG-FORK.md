# Fork changelog

Changes made in this fork (BerubePascal/KlipperSnapmakerJ1) on top of the
original repo (Nimrasol/KlipperSnapmakerJ1). The original's own history is in
`CHANGELOG.md`, which this fork leaves untouched. Newest entries first.

## 2026-11-23 — branch `dial-bed-mesh`

- **New touch-screen screen: Calibration → Bed Mesh (Dial Indicator).** The
  J1 has no bed mesh probing, so the bed is measured by hand with a dial
  indicator mounted in place of a hotend.
  - Choose the toolhead, a grid (3×3, 5×5, 7×5, 9×7 or custom), the edge
    margin, the bed temperature (60 °C by default) and the sign of the dial.
  - The printer heats the bed and waits, homes, then goes to the reference
    point X162 Y187 at Z=0, where the J1 bed leveling sets Z=0. Zero the
    dial there.
  - At each grid point the bed drops to Z=10, the toolhead moves, and the bed
    comes back to Z=0. Type the reading, then Next.
  - At the end it checks the reference again for drift and shows the
    deviation table.
  - Save writes the Klipper profile `[bed_mesh dial]` to
    `~/printer_data/config/snapmaker_j1_bed_mesh.cfg` (made 0 at the
    reference point; raw readings kept as comments) and restarts Klipper.
- It doesn't run during a print, or in duplication or mirror mode.
- The printer side (in `printer.cfg`, not in this repo): `[bed_mesh]`, the
  include of the profile file, the `LOAD_DIAL_MESH` macro for the start
  G-code, a block on `BED_MESH_CALIBRATE` (the nozzle contact is a Klipper
  probe), and `BED_MESH_CLEAR` at print end, at cancel and before
  calibrations.
- Files: `klipperscreen/snapmaker_j1/bed_mesh.py` (new),
  `klipperscreen/snapmaker_j1/__init__.py`, `flows.py`, `calibration.py`
  (small hooks marked `! LOCAL CHANGE`), `tests/test_bed_mesh.py` (new),
  `CHANGELOG-FORK.md`.

## 2026-11-23 — branch `update-upstream-27b8e9d`

- **Updated to the original's latest code** (commit `27b8e9d`, 2026-11-23),
  not a release. The author made a "Release v1.7.0" commit, reverted it the
  same day, and kept working on top. There's no v1.7.0 tag yet. This
  brings the v1.7.0 content (case light settings during a print, Wi-Fi
  power saving off, calibration contact checks, PETG/ABS test prints) plus
  unreleased work: a new touch-screen home page that replaces the main menu
  and the service page, a left toolhead active at print start, and filament
  loading 5 °C below the target.
- **Removed the fork's own light change** in `light.py`: the original now
  has **More → Light → "Dim after during a print"** (set it to never), which
  does the same thing.
- Still different from the original: the Moonraker update entry (fork
  origin, `dev` channel) and this file.
- Checked against the printer.cfg macros (`printer-cfg-overrides.cfg`):
  `_SNAPMAKER_PRINT_DONE`, `CANCEL_PRINT`, `SNAPMAKER_NOZZLE_PARK`,
  `_SNAPMAKER_FILAMENT_MOVE`, `M2000`, `M106` and `T0`/`T1` are unchanged.
- Files: merge of the original (many files), `klipperscreen/snapmaker_j1/light.py`
  (back to the original), `CHANGELOG-FORK.md`.

## 2026-11-21 — branch `no-dim-while-printing`

- **Based on the v1.6.0 release** (the version the printer runs), not on the
  original's newer, unreleased commits. Those come with the next release,
  when the fork is synced.
- **Case light no longer dims during a print.** The touch screen's "Dim after"
  timer used to dim the light even while printing. It now skips dimming while
  a print is running or paused and checks again after the same delay, so
  dimming works normally once the print is over. The light can still be
  turned off by hand during a print (e.g. night prints).
- **Updates come from this fork.** The Moonraker update entry now points to
  the fork and uses the `dev` channel, because syncing the fork on GitHub
  doesn't copy the original's release tags. The version pins are unchanged.
- Files: `klipperscreen/snapmaker_j1/light.py`,
  `moonraker/KlipperSnapmakerJ1.conf`, `CHANGELOG-FORK.md` (new).
