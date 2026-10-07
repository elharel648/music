# FLOW — AI Producer Layer

Reference track in. Your sounds in. An editable arrangement out, inside your DAW.

FLOW measures a reference (tempo, key, sections, where the kick leaves and returns, energy per bar),
scans a folder of your samples, renders pattern loops from your one-shots, and places everything on the
reference's structure, scaled to the length you ask for.

- **Ableton Live**: writes a real Set in front of you (tracks, clips at the right bars, locators, your own
  synth as MIDI for bass/lead, your sidechain plug-in on every track) through the AbletonMCP Remote Script.
- **Any other DAW** (Logic, FL Studio, Cubase, Studio One, Bitwig, Reaper): exports full-length stems that
  all start at bar 1, a Standard MIDI File with section markers and the bass/synth/drum patterns, a
  Blueprint report (HTML) and `blueprint.json`.

Copyright © 2026 Harel Eliyahu. All rights reserved. Proprietary; see `LICENSE` (EULA). 14-day trial, then a license key.

## Run from source (macOS / Windows / Linux)

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python numpy scipy soundfile pywebview cryptography pytest pyinstaller
.venv/bin/python run_flow.py                 # desktop app
.venv/bin/python run_flow.py analyze "ref.mp3"
.venv/bin/python run_flow.py build --ref "ref.mp3" --pack "/path/to/samples" --length 6:30 --target stems --out "/path/out"
.venv/bin/python run_flow.py build --ref "ref.mp3" --pack "/path/to/samples" --target ableton --synth Serum --sidechain "Kickstart 2"
.venv/bin/python -m pytest -q
```

Ableton target requirements: Live 12.0.5+, the AbletonMCP Remote Script installed and enabled
(Settings › Link, Tempo & MIDI › Control Surface › AbletonMCP), and an **empty Live Set in front**
(File › New Live Set). FLOW refuses to write into a set that is not empty. Press Cmd+S right after a build:
what the bridge writes lives in memory until you save.

## Build the installers

- macOS: `./packaging/build_mac.sh` → `dist/FLOW.app` + `dist/FLOW-0.1.0-mac.dmg`.
  Unsigned until you have an Apple Developer ID; users then right-click › Open the first time.
  With `DEVELOPER_ID`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` set, the script signs and notarizes.
- Windows: push a `v*` tag (or run the workflow manually) → GitHub Actions builds `FLOW-windows.zip`
  (`.github/workflows/build.yml`). Needs a Windows machine or CI; cannot be cross-built from a Mac.
  SmartScreen will warn until the exe is signed with a code-signing certificate.

## License keys (owner only)

```bash
.venv/bin/python tools/keygen.py init            # once. Creates keys/private.pem — BACK IT UP, never commit it
.venv/bin/python tools/keygen.py issue dj@example.com            # perpetual key
.venv/bin/python tools/keygen.py issue dj@example.com --days 365 # one-year key
.venv/bin/python tools/keygen.py verify FLOW-...
```

Keys are Ed25519-signed and verified offline; the public key lives in `flow/license.py`. The 14-day trial
clock is stored per machine in the app-data folder with an integrity check. This is the standard indie-plugin
level of protection: it stops casual sharing, not a determined cracker. For stronger protection later:
online activation with a server (Lemon Squeezy / Paddle license APIs) and per-machine seat counting.

## What is measured vs. what is a default

Measured from the reference: BPM (or from the filename), key, bar grid, section boundaries (4-bar phrases),
section labels (Intro / Groove / Drop / Breakdown / Build / Outro, from kick presence and energy), the
"kick leaves one bar before a break" habit. Defaults: the rhythm patterns per role (4/4 kick, clap on 2+4,
offbeat open hat, offbeat bass, a small synth motif in the key) and which layers live in which section
(`flow/arrange.py` STYLE_TEMPLATES). Bass and synth are always marked as placeholders to replace by ear.

## Layout

```
flow/analysis.py   reference measurement        flow/pack.py       sample scanning + kit choice
flow/patterns.py   pattern loops, MIDI notes     flow/arrange.py    structure scaling + track plan
flow/ableton_bridge.py  Live writer (TCP 9877)   flow/export.py     stems + MIDI + report (any DAW)
flow/plugins.py    installed plug-in scan        flow/license.py    trial + Ed25519 keys
flow/app.py + flow/ui/index.html  desktop app    flow/cli.py        command line
```
