# Third-party licenses

FocusMic itself is Apache-2.0 (see `LICENSE`). The packaged build includes the
following third-party components. Their licenses apply to those components.

| Component | Version | License | Project |
|---|---|---|---|
| Falcon / Falcon Studio | vendored | Apache-2.0 | https://github.com/JusperLee/Falcon |
| Falcon model weights | small/big | Apache-2.0 | https://github.com/JusperLee/Falcon |
| MediaPipe | 1.2.0 | Apache-2.0 | https://github.com/google-ai-edge/mediapipe |
| PyTorch | 2.9.1+cu128 | BSD-3-Clause | https://pytorch.org |
| torchgen / functorch (PyTorch) | 2.9.1 | BSD-3-Clause | https://pytorch.org |
| NVIDIA CUDA runtime libraries (bundled with the PyTorch wheel) | 12.8 | NVIDIA CUDA Toolkit License | https://www.nvidia.com/en-us/drivers/cuda/ |
| SymPy | 1.14.0 | BSD-3-Clause | https://www.sympy.org |
| mpmath | 1.3.0 | BSD-3-Clause | https://mpmath.org |
| NetworkX | 3.7 | BSD-3-Clause | https://networkx.org |
| Jinja2 | 3.1.6 | BSD-3-Clause | https://jinja.palletsprojects.com |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://markupsafe.palletsprojects.com |
| filelock | 4.2.4 | Unlicense | https://github.com/tox-dev/filelock |
| fsspec | 2026.9.0 | BSD-3-Clause | https://filesystem-spec.readthedocs.io |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| setuptools | 78.1.0 | MIT | https://github.com/pypa/setuptools |
| PySide6 / Qt | 6.12.0 | LGPL-3.0 (dynamic linking) | https://www.qt.io/qt-for-python |
| OpenCV | 5.0.0 | Apache-2.0 | https://opencv.org |
| NumPy | 2.5.4 | BSD-3-Clause | https://numpy.org |
| SoundDevice | 0.5.6 | MIT | https://python-sounddevice.readthedocs.io |
| PortAudio (bundled with SoundDevice) | — | MIT | https://www.portaudio.com |
| python-soxr | 1.1.0 | LGPL-2.1+ | https://github.com/dofuuz/python-soxr |
| soundfile | 0.14.0 | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| nvidia-ml-py | 13.615.71 | BSD-3-Clause | https://github.com/gpustat/nvidia-ml-py |
| keyboard | 0.13.5 | MIT | https://github.com/boppreh/keyboard |
| Lucide icons | 1.66 | ISC | https://lucide.dev |
| Simple Icons | — | CC0-1.0 | https://simpleicons.org |
| PyInstaller (build tool) | 6.22.3 | GPL-2.0-or-later with bootloader exception | https://pyinstaller.org |

## Qt / PySide6

PySide6 and Qt are dynamically linked as separate DLLs. Source and license
information: https://www.qt.io/qt-for-python and https://www.qt.io/licensing.

## Virtual audio cable

FocusMic does not bundle VB-CABLE or any other virtual audio driver. Users
install the driver separately from its vendor; its license is between the user
and that vendor.

## Model weights

The Falcon checkpoints are distributed under Apache-2.0 and are included in
`weights/`. They are not part of FocusMic's own source code.
