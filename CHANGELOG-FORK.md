# Fork changelog

Changes made in this fork (BerubePascal/KlipperSnapmakerJ1) on top of the
original repo (Nimrasol/KlipperSnapmakerJ1). The original's own history is in
`CHANGELOG.md`, which this fork leaves untouched. Newest entries first.

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
