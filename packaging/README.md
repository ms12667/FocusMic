# FocusMic Windows packaging

## Prerequisites

- Python 3.12 virtual environment with `requirements-focusmic.txt` installed.
- PyInstaller (build-only): `uv pip install --python .venv/Scripts/python.exe -r requirements-build.txt`
- Inno Setup 6.3+ for the installer:
  `winget install --id JRSoftware.InnoSetup --exact`

The Inno Setup compiler is expected at:
`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` (per-user install) or the standard
Program Files location.

## Build

From the project root:

```bat
build-windows.bat
build-runtime.bat
```

Outputs:

- `dist\FocusMic\FocusMic.exe` — portable one-folder app (~586 MB, no torch)
- `dist\installer\FocusMic-Setup-0.1.0.exe` — main per-user installer (~235 MB)
- `dist\installer\FocusMic-Runtime-2.9.1-cu128.exe` — PyTorch 2.9.1 + CUDA 12.8
  runtime installer, installed to `%LOCALAPPDATA%\FocusMic\runtime`

PyTorch is intentionally not bundled in the main app: it is ~4.3 GB on disk and
would push a single installer past GitHub's 2 GiB release-asset limit. The main
installer and the runtime installer are separate downloads; FocusMic detects
the runtime and shows guidance if it is missing. `build-runtime.bat` stages the
runtime from `.venv` with hard links and then compiles it with Inno Setup.

To test the packaged app against an uninstalled runtime payload, set
`FOCUSMIC_RUNTIME` to the payload directory:

```bat
set FOCUSMIC_RUNTIME=%CD%\build-tools\runtime\payload
dist\FocusMic\FocusMic.exe --selftest
```

`FocusMic.spec` bundles:

- `focusmic/assets/` (icons, MediaPipe task files)
- `weights/falcon.pt` and `falcon-big.pt`
- vendored Falcon configs and license
- MediaPipe, PySide6, OpenCV, PortAudio/soxr binaries via PyInstaller hooks
- `README.md`, `LICENSE`, `NOTICE`

PyTorch and its CUDA DLLs are excluded from the main build. The runtime
installer payload is staged by `build_runtime.py` and contains `torch`,
`torchgen`, `functorch`, `sympy`, `networkx`, `jinja2`, `markupsafe`,
`filelock`, `fsspec`, `typing_extensions`, `setuptools`, `mpmath`, and the
`torch-2.9.1+cu128.dist-info` metadata.

Both installers are per-user (`PrivilegesRequired=lowest`); the main app
installs to `%LOCALAPPDATA%\Programs\FocusMic`, the runtime to
`%LOCALAPPDATA%\FocusMic\runtime`, and neither requires administrator rights.

## Notes

- No code signing certificate is configured; Windows SmartScreen may warn on
  an unsigned installer. Sign `FocusMic.exe` and the setup executable before
  public distribution if you have a certificate.
- The distributed app still needs the VB-CABLE virtual audio driver for routing
  audio into voice/meeting software. It is not bundled.
- Model weights are Apache-2.0; keep them with the `NOTICE` file.
- The main installer excludes `api-ms-win-*.dll`; Windows 10/11 provides these
  API set DLLs, and bundling them made Inno Setup fail with `MoveFile` error 5
  on the test machine.
