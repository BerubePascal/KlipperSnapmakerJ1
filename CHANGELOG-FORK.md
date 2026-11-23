# Fork changelog

Changes made in this fork (BerubePascal/KlipperSnapmakerJ1) on top of the
original repo (Nimrasol/KlipperSnapmakerJ1). The original's own history is in
`CHANGELOG.md`, which this fork leaves untouched. Newest entries first.

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
