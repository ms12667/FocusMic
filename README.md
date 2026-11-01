# FocusMic (private backup)

Windows real-time audio-visual target speaker extraction for Discord / games,
built on [Falcon Studio](https://github.com/JusperLee/Falcon) (Apache-2.0).

This repository is a **private working backup**, not a public release yet.

## Current configuration

- Falcon **Small** by default (Big selectable in the UI)
- 2 s window, **0.2 s hop**, 80 ms right context
- **+30 ms A/V offset** default (adjustable -250…+250 ms)
- **+6 dB** output makeup gain
- Local inference only; microphone + camera -> VB-CABLE -> Discord/game
- Measured headphone-monitor latency: ~470 ms
- **Native CABLE output is on by default**: when separation starts, the server
  writes the separated stream directly to `CABLE Input` through WASAPI. There
  is no meeting/game device selector; the UI shows one CABLE output status.
  Loopback test: ~74 ms CABLE/stream latency, waveform correlation 0.99999.

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
Falcon/                     upstream Falcon source + local Windows changes
  studio/server.py          FastAPI/WebSocket service, 0.2 s hop, Small default
  studio/native_output.py   server-side WASAPI writer to VB-CABLE
  studio/web/app.js         capture, mouth tracking, playback, A/V offset, gain
  studio/web/index.html     UI
  studio/falcon_model/      inference-only model code
  studio/configs/           Falcon.yml / FalconBig.yml
weights/                    falcon.pt, falcon-big.pt (Apache-2.0)
run_studio_local.py         starts Studio with local weights
start_focusmic.bat          Windows one-click launcher
HANDOFF.md                  detailed project handoff / measurements
prep_recordings.py          extract 16 kHz audio + 25 fps mouth crops
eval_*.py                   offline Falcon / VoxLock evaluation
native_app.py               native CLI prototype (mic + camera -> Falcon -> CABLE)
native/                     audio/video capture, mouth tracking, scheduler
focusmic_icon_256.png       app icon (source)
focusmic_icon.svg           vector icon
focusmic_icon.ico           multi-size Windows icon
```

## Run (Windows)

1. Python 3.12 venv with `torch` (CUDA), `fastapi`, `uvicorn`, `websockets`,
   `numpy`, `Pillow`, `PyYAML`, `einops`, `soundfile`, `sounddevice`.
2. Double-click `start_focusmic.bat`.
3. In the page: enable devices, select the **physical/headset microphone**, then
   start separation. CABLE output starts automatically and writes to
   `CABLE Input (VB-Audio Virtual Cable)`.
4. In Discord/game select `CABLE Output (VB-Audio Virtual Cable)` as microphone.
   Disable Discord noise suppression, AGC, echo cancellation.

## Native CLI (M1 prototype, no browser)

```bat
.venv\Scripts\python.exe native_app.py --list --list-cameras
.venv\Scripts\python.exe native_app.py --simulate --duration 20 --no-output --save-wav sim_out.wav
.venv\Scripts\python.exe native_app.py --mic "麦克风" --camera 0 --duration 60
```

The live command uses the microphone and camera; the simulate command only
reads files under `testrecordings/` and does not touch devices.

## Not included / excluded

- `.venv/` (5+ GB)
- `demo/` (official demo media/outputs)
- `testrecordings/` (private user recordings and generated evaluations)
- logs and `__pycache__`

## License / credits

Falcon code and weights are Apache-2.0. VB-CABLE is a separate donationware
driver and is not bundled. This project is not affiliated with the Falcon
authors.
