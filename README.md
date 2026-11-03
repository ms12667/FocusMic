# FocusMic

Windows real-time audio-visual target speaker extraction for Discord / games,
built on [Falcon Studio](https://github.com/JusperLee/Falcon) (Apache-2.0).

This repository is a **private beta**, not a public release yet.

## Current configuration

- Falcon **Small** by default (Big selectable in the UI)
- 2 s window, **0.2 s hop**, 80 ms right context
- **+30 ms A/V offset** default (adjustable -250…+250 ms)
- **+6 dB** output makeup gain
- Local inference only; microphone + camera -> VB-CABLE -> Discord/game
- Measured headphone-monitor latency: ~470 ms
- **Native CABLE output is on by default**: FocusMic writes the separated
  stream directly to `CABLE Input` through WASAPI. There is no meeting/game
  device selector; the UI shows one CABLE output status. Loopback test: ~74 ms
  CABLE/stream latency, waveform correlation 0.99999.
- Native config: `%APPDATA%\FocusMic\config.json`; logs:
  `%LOCALAPPDATA%\FocusMic\logs\focusmic.log`.

## VB-CABLE naming (important)

Windows classifies the two endpoints as follows (verified from the MMDevices
registry on this machine):

| Windows class | Device | Used by |
|---|---|---|
| Render / playback / 扬声器 | **CABLE Input** | FocusMic output |
| Capture / recording / 麦克风 | **CABLE Output** | Discord / game microphone |

So FocusMic writes to `CABLE Input`, and Discord/game selects `CABLE Output`
as its microphone. `CABLE Input` is not a recording endpoint and cannot be
selected as a microphone; if it appears in a device list, that is the output
list. This is VB-CABLE's standard naming, not a bug.

## Layout

```
focusmic/                   native app package
  __main__.py / app.py      single-instance UI entry
  ui.py                     PySide6 window
  audio.py                  WASAPI capture / file simulation
  video.py                  camera + MediaPipe mouth/hand tracking
  pipeline.py               window scheduler + Falcon + safe bypass
  monitor.py / output.py    headphone and CABLE outputs
  config.py / paths.py      settings, assets, logs, weights lookup
  ui.py                     sidebar tabs, Home / Performance / About
  charts.py / metrics.py    QPainter line charts + CPU/GPU/RAM sampling
  icons.py / theme.py       SVG icons, morphing controls, light/dark tokens
  settings_dialog.py        startup, theme, hotkey and gain settings
  pagehost.py               slide-and-fade page transitions
  vendor/falcon/            vendored Falcon inference (Apache-2.0)
  assets/                   app icon + MediaPipe face/hand models
weights/                    falcon.pt, falcon-big.pt (Apache-2.0)
FocusMic.bat                one-click native launcher (pythonw)
start_focusmic_native.bat   alias for the same launcher
HANDOFF.md                  detailed project handoff / measurements
requirements-focusmic.txt   pinned native dependency versions
pyproject.toml              package metadata and console entry points
Falcon/                     upstream reference + legacy browser studio
testrecordings/             private test material (not committed)
```

## Run (Windows)

1. Python 3.12 with the packages in `requirements-focusmic.txt`
   (`torch==2.9.1+cu128` from the PyTorch CUDA 12.8 wheel index).
2. Double-click **`FocusMic.bat`**.
3. Click **开始**, select the physical/headset microphone. CABLE output starts
   automatically and writes to `CABLE Input (VB-Audio Virtual Cable)`.
4. In Discord/game select `CABLE Output (VB-Audio Virtual Cable)` as microphone.
   Disable Discord noise suppression, AGC, echo cancellation.

Settings persist in `%APPDATA%\FocusMic\config.json`; logs are written to
`%LOCALAPPDATA%\FocusMic\logs\focusmic.log`.

## Native CLI

```bat
.venv\Scripts\python.exe -m focusmic.cli --list --list-cameras
.venv\Scripts\python.exe -m focusmic.cli --simulate --duration 20 --no-output --save-wav sim_out.wav
.venv\Scripts\python.exe -m focusmic.cli --mic "麦克风" --camera 0 --duration 60
```

The live command uses the microphone and camera; the simulate command only
reads files under `testrecordings/` and does not touch devices. The UI entry is
`python -m focusmic` (or `FocusMic.bat`).

## Native UI

The window is designed around a 4:3 workspace (1080×810) with a slim sidebar:

- **主页** — camera preview with mouth ROI, one-click start/stop, microphone,
  camera, model, headphone monitoring, A/V offset, reacquire, manual bypass and
  CABLE Input status.
- **性能信息** — task-manager-style live charts for inference latency, system
  CPU, GPU utilization and VRAM, plus current/avg/peak values.
- **关于 FocusMic** — icon, version, developer, GitHub link, license credits
  and build information.
- **外观** — one-click dark/light toggle in the sidebar; Settings can follow
  the system appearance. The icon set is Lucide (ISC); the sun/moon and page
  transitions borrow the Morphicons interaction idea (MIT, not bundled).
- **设置** — startup with Windows, follow-system theme, global bypass hotkey
  enable/edit, output gain. Settings live in
  `%APPDATA%\FocusMic\config.json`.

Safe behavior: MediaPipe Hand Landmarker also runs on each camera frame; if a
hand covers the mouth or the mouth cue is lost for ~0.6 s (tracked < 40%), the
pipeline bypasses to the raw microphone and logs `直通`. It returns to Falcon
after two tracked windows. `Ctrl+Alt+M` toggles manual bypass; the tray menu has
show/hide, start/stop, bypass and quit. `重新锁定` clears the target face.

## Not included / excluded

- `.venv/` (5+ GB)
- `demo/` (official demo media/outputs)
- `testrecordings/` (private user recordings and generated evaluations)
- logs and `__pycache__`

## License / credits

FocusMic is Apache-2.0 (see `LICENSE` and `NOTICE`). Falcon code and weights
are Apache-2.0. MediaPipe is Apache-2.0; Lucide is ISC; Simple Icons is CC0;
PySide6 is LGPL-3.0. VB-CABLE is a separate donationware driver and is not
bundled. This project is not affiliated with the Falcon authors.
