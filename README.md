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

## Layout

```
Falcon/                     upstream Falcon source + local Windows changes
  studio/server.py          FastAPI/WebSocket service, 0.2 s hop, Small default
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
```

## Run (Windows)

1. Python 3.12 venv with `torch` (CUDA), `fastapi`, `uvicorn`, `websockets`,
   `numpy`, `Pillow`, `PyYAML`, `einops`, `soundfile`, `sounddevice`.
2. Double-click `start_focusmic.bat`.
3. In the page: enable devices, select the **physical/headset microphone**, set
   meeting output to `CABLE Input (VB-Audio Virtual Cable)`, enable it, start.
4. In Discord/game select `CABLE Output (VB-Audio Virtual Cable)` as microphone.
   Disable Discord noise suppression, AGC, echo cancellation.

## Not included / excluded

- `.venv/` (5+ GB)
- `demo/` (official demo media/outputs)
- `testrecordings/` (private user recordings and generated evaluations)
- logs and `__pycache__`

## License / credits

Falcon code and weights are Apache-2.0. VB-CABLE is a separate donationware
driver and is not bundled. This project is not affiliated with the Falcon
authors.
