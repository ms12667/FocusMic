# FocusMic

Windows real-time audio-visual target speaker extraction for voice and meeting apps,
built on [Falcon Studio](https://github.com/JusperLee/Falcon) (Apache-2.0).

This repository is a **private beta**, not a public release yet.

## Current configuration

- Falcon **Small** by default (Big selectable in the UI)
- 2 s window, **0.2 s hop**, 80 ms right context
- **+30 ms A/V offset** default (adjustable -250…+250 ms)
- **+6 dB** output makeup gain
- Local inference only; microphone + camera -> virtual audio cable -> voice app
- Measured headphone-monitor latency: ~470 ms
- **Native CABLE output is on by default**: FocusMic writes the separated
  stream directly to `CABLE Input` through WASAPI. There is no target-app
  device selector; the UI shows one virtual-output status. Loopback test: ~74 ms
  CABLE/stream latency, waveform correlation 0.99999.
- Native config: `%APPDATA%\FocusMic\config.json`; logs:
  `%LOCALAPPDATA%\FocusMic\logs\focusmic.log`.

## VB-CABLE naming (important)

Windows classifies the two endpoints as follows (verified from the MMDevices
registry on this machine):

| Windows class | Device | Used by |
|---|---|---|
| Render / playback / 扬声器 | **CABLE Input** | FocusMic output |
| Capture / recording / 麦克风 | **CABLE Output** | voice / meeting app microphone |

So FocusMic writes to `CABLE Input`, and your voice/meeting app selects
`CABLE Output` as its microphone. `CABLE Input` is not a recording endpoint and cannot be
selected as a microphone; if it appears in a device list, that is the output
list. This is VB-CABLE's standard naming, not a bug.

## Layout

```
focusmic/                   native app package
  __main__.py / app.py      single-instance UI entry
  ui.py                     sidebar: Home / Tutorial / Performance / Report / Settings / About
  audio.py                  WASAPI capture / file simulation
  video.py                  camera + MediaPipe mouth/hand tracking
  pipeline.py               window scheduler + Falcon + safe bypass
  monitor.py / output.py    headphone and CABLE outputs
  config.py / paths.py      settings, assets, logs, weights lookup
  charts.py / metrics.py    QPainter line charts + per-process CPU/RAM/GPU sampling
  report.py                 waveform and spectrum comparison widgets
  icons.py / controls.py    SVG icons, morphing controls, themed labels/switches
  theme.py                  light/dark tokens and Qt stylesheet
  tray.py                   native Win32 notification-area context menu
  pagehost.py               slide-and-fade page transitions
  onboarding.py             four-step first-run setup wizard
  runtime.py                external PyTorch/CUDA locator and ABI/version check
  runtime_dialog.py         install guidance when the runtime is missing
  vendor/falcon/            vendored Falcon inference (Apache-2.0)
  assets/                   app icon + MediaPipe face/hand models
weights/                    falcon.pt, falcon-big.pt (Apache-2.0)
FocusMic.bat                one-click native launcher (pythonw)
packaging/                  PyInstaller/Inno Setup scripts
build-windows.bat           build the app + main installer
build-runtime.bat           build the PyTorch/CUDA runtime installer
dist/                       release artifacts (gitignored)
HANDOFF.md                  detailed project handoff / measurements
requirements-focusmic.txt   pinned native dependency versions
pyproject.toml              package metadata and console entry points
testrecordings/             private test material (not committed)
```

## Run (Windows)

1. Python 3.12 with the packages in `requirements-focusmic.txt`
   (`torch==2.9.1+cu128` from the PyTorch CUDA 12.8 wheel index).
2. Double-click **`FocusMic.bat`**.
3. Click **开始**, select the physical/headset microphone. CABLE output starts
   automatically and writes to `CABLE Input (VB-Audio Virtual Cable)`.
4. In your voice/meeting app select `CABLE Output (VB-Audio Virtual Cable)` as
   microphone. Disable that app's noise suppression, AGC and echo cancellation.
5. Closing the window hides FocusMic to the tray by default. Turn off
   "关闭窗口时最小化到托盘" in Settings if you want × to quit directly.

Settings persist in `%APPDATA%\FocusMic\config.json`; logs are written to
`%LOCALAPPDATA%\FocusMic\logs\focusmic.log`.

## Install (release)

- **Runtime (required once)**: `dist\installer\FocusMic-Runtime-2.9.1-cu128.exe`
  installs PyTorch 2.9.1 + CUDA 12.8 into `%LOCALAPPDATA%\FocusMic\runtime`.
  The main app deliberately does not bundle it, so each GitHub release asset
  stays below the 2 GiB limit. FocusMic shows an install banner/dialog when
  the runtime is missing.
- **Installer**: `dist\installer\FocusMic-Setup-0.1.0.exe` — per-user install to
  `%LOCALAPPDATA%\Programs\FocusMic`, no administrator rights.
- **Portable**: run `dist\FocusMic\FocusMic.exe` from the one-folder build
  (the runtime package is still required).
- Packaged self-test (no microphone/camera): `FocusMic.exe --selftest`, then read
  `%LOCALAPPDATA%\FocusMic\logs\selftest.log`. Set `FOCUSMIC_RUNTIME` to point at
  an alternative runtime directory.

The installers are unsigned, so Windows SmartScreen may warn. VB-CABLE is not
bundled; install it separately for routing audio into voice/meeting software.

## Build Windows installer

Build-only prerequisites (the runtime venv already has the app dependencies):

```bat
uv pip install --python .venv\Scripts\python.exe -r requirements-build.txt
winget install --id JRSoftware.InnoSetup --exact
build-windows.bat
build-runtime.bat
```

Outputs `dist\FocusMic\FocusMic.exe` (portable folder),
`dist\installer\FocusMic-Setup-0.1.0.exe` (main installer, ~235 MB) and
`dist\installer\FocusMic-Runtime-2.9.1-cu128.exe` (PyTorch/CUDA runtime,
~2 GB). See `packaging\README.md` for details.

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

- **主页** — portrait camera preview with a subtle mouth ROI, one-click
  start/stop, microphone, camera, model, headphone monitoring, A/V offset,
  output gain, reacquire, **manual target box (“框选目标”)**, manual bypass and
  CABLE Input status. The run log is a full-width console at the bottom of the
  tab and follows the light/dark theme.
- **使用教程** — a plain-language walkthrough: preparation, first run, status/bypass,
  accuracy tips, troubleshooting and privacy.
- **性能信息** — task-manager-style live charts scoped to the FocusMic process
  (not whole-machine load): inference latency, estimated full-chain latency,
  CPU, memory (USS, matching Task Manager's private working set) and per-process
  GPU utilization from Windows GPU Engine counters (busiest engine, the same
  definition Task Manager uses).
- **运行报告** — the last 8 s of raw microphone vs. separated output as stacked
  waveforms and an averaged 0–4 kHz spectrum, plus average suppression, automatic
  bypass count, maximum inference latency, full-chain latency, session time,
  processed/skipped windows, CABLE state and a larger console.
- **设置** — startup with Windows, follow-system appearance, manual dark/light,
  global bypass hotkey enable/edit, config/log paths and a “首次向导” button.
  Settings live in `%APPDATA%\FocusMic\config.json`.
- **关于 FocusMic** — icon, version, developer, GitHub link, license credits
  and build information, with theme-aware text and row spacing.
- **外观** — one-click dark/light toggle in the sidebar. The icon set is Lucide
  (ISC); the sun/moon and page transitions borrow the Morphicons interaction
  idea (MIT, not bundled). Combo boxes show a chevron guide.
- **托盘** — the notification-area context menu is a native Win32 popup
  (`focusmic/tray.py`), not a Qt-drawn menu.

A four-page first-run wizard (welcome, devices, virtual output check, ready)
appears only for a brand-new install; existing configs skip it. Microphone
hot-plug is polled every 2 s; unplugging the active mic or losing camera frames
stops the pipeline safely.

Stopping is asynchronous: the GUI detaches immediately and PortAudio/MediaPipe
teardown runs on a cleanup thread, so a blocked camera read or model unload can
never freeze the window. MediaPipe objects are only closed by the camera thread
that owns them.

Safe behavior: MediaPipe Hand Landmarker also runs on each camera frame; if a
hand covers the mouth or the mouth cue is lost for ~0.6 s (tracked < 40%), the
pipeline bypasses to the raw microphone and logs `直通`. It returns to Falcon
after two tracked windows. `Ctrl+Alt+M` toggles manual bypass; the tray menu has
show/hide, start/stop, bypass and quit. `重新锁定` clears the target face.

## Not included / excluded

- `.venv/` (5+ GB)
- `dist/`, `build/`, `build-tools/` (release/build artifacts)
- `testrecordings/` (private user recordings and generated evaluations)
- logs and `__pycache__`

## License / credits

FocusMic is Apache-2.0 (see `LICENSE` and `NOTICE`). Falcon code and weights
are Apache-2.0. MediaPipe is Apache-2.0; Lucide is ISC; Simple Icons is CC0;
PySide6 is LGPL-3.0. VB-CABLE is a separate donationware driver and is not
bundled. This project is not affiliated with the Falcon authors.
