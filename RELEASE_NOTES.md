# FocusMic 0.1.0 — Windows release notes

## Artifacts

| Artifact | Size | Notes |
|---|---:|---|
| `dist\installer\FocusMic-Setup-0.1.0.exe` | 234.6 MB (234,587,126 B) | main app, per-user, no admin |
| `dist\installer\FocusMic-Runtime-2.9.1-cu128.exe` | 1.72 GiB (1,842,053,289 B) | PyTorch 2.9.1 + CUDA 12.8 runtime |
| `dist\FocusMic\FocusMic.exe` | 19 MB | launcher inside the 586 MB portable folder |

Both installers are below GitHub's 2 GiB per-release-asset limit.

SHA-256:

```text
744b59726e6bd087a29a3e6a6d03ffbfa1f3190029ab8e438fc12674c15c1e16  FocusMic-Setup-0.1.0.exe
4bc1c166e0caae9db4ced170b15e1614e9d813a0fa7d195eb1870d749a095ce9  FocusMic-Runtime-2.9.1-cu128.exe
```

## Fixes in this build

- Camera health monitoring no longer treats "tracker has not started yet" as a
  dead camera thread. Previously the first metrics tick during model loading
  stopped separation immediately.
- Microphone selection now persists both the device name and host API
  (MME/DirectSound/WASAPI/WDM-KS), so choosing a specific duplicate endpoint
  survives restarts.
- Closing the window now hides FocusMic to the tray by default. Settings has a
  "关闭窗口时最小化到托盘" switch; turning it off makes the × button quit.
- The stop button now uses a solid red danger style while separation is running.

## Why two installers

PyTorch + CUDA is ~4.3 GB on disk and cannot fit a single GitHub release
asset. The main app therefore excludes it; the runtime installer places it in
`%LOCALAPPDATA%\FocusMic\runtime` and the app loads it from there after
validating the Python ABI, PyTorch version, CUDA version and `_C` extension.

## Requirements

- Windows 10/11 x64
- NVIDIA GPU with a working driver
- Camera and microphone
- VB-CABLE or an equivalent virtual audio cable for routing into voice/meeting software

## Install

1. Run `FocusMic-Runtime-2.9.1-cu128.exe` once. It installs to
   `%LOCALAPPDATA%\FocusMic\runtime` and requires no administrator rights.
2. Run `FocusMic-Setup-0.1.0.exe`. It installs to
   `%LOCALAPPDATA%\Programs\FocusMic` and requires no administrator rights.
3. Start FocusMic. If the runtime is missing, the home page shows a banner and
   the start button opens an install dialog with a download link.
4. In the voice/meeting app, select `CABLE Output` as the microphone and disable
   its noise suppression / AGC / echo cancellation.

The order can be reversed: the main app starts without the runtime and shows
installation guidance.

The executables are unsigned, so Windows SmartScreen may show a warning.

## Offline verification

```bat
FocusMic.exe --selftest
```

Writes `%LOCALAPPDATA%\FocusMic\logs\selftest.log`. The release build passed
with the external runtime:

- runtime loaded from `%LOCALAPPDATA%\FocusMic\runtime`
- PyTorch 2.9.1+cu128, CUDA 12.8 available
- Falcon Small loaded on CUDA
- face/hand task files and both weights present
- one inference ≈ 70 ms

Without the runtime, `--selftest` exits with code 1 and a clear Chinese error
instead of crashing.

Set `FOCUSMIC_RUNTIME` to an alternative directory to test an uninstalled
runtime payload.

## Known limitations

- Installer UI is English; the application UI is Chinese.
- Installers and app are unsigned.
- The runtime installer must match the app's expected PyTorch/CUDA version.
- Full-chain latency is an estimate and excludes the receiving app's own buffer.
- Average suppression is an input/output RMS energy ratio, not a SIR/SI-SDR
  measurement.
- VB-CABLE is a separate driver and is not bundled.
- Long-session A/V clock drift, stereo microphones where the target is not on
  channel 0, and full camera-thread teardown during immediate app exit remain
  known edge cases.
