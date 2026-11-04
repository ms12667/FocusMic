# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for FocusMic.

Run from the project root:
    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean FocusMic.spec
"""
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()
VENDOR = ROOT / "focusmic" / "vendor" / "falcon"
# Falcon's runtime imports its model package as a top-level module.
sys.path.insert(0, str(VENDOR))

mediapipe_datas, mediapipe_binaries, mediapipe_hidden = collect_all("mediapipe")
falcon_hidden = collect_submodules("falcon_model")

datas = [
    (str(ROOT / "focusmic" / "assets"), "focusmic/assets"),
    (str(ROOT / "weights"), "weights"),
    (str(VENDOR / "configs"), "focusmic/vendor/falcon/configs"),
    (str(VENDOR / "LICENSE"), "focusmic/vendor/falcon"),
    (str(VENDOR / "falcon_model" / "PROVENANCE.md"),
     "focusmic/vendor/falcon/falcon_model"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE"), "."),
]
datas += mediapipe_datas

# torch is loaded from the external runtime, so PyInstaller cannot see its
# dynamic stdlib imports.  Include the ones its import/serialization paths use.
torch_stdlib = [
    "pickletools", "copyreg", "optparse", "argparse", "uuid", "zipfile",
    "tarfile", "gzip", "bz2", "lzma", "hashlib", "hmac", "ssl",
    "http.client", "urllib.request", "urllib.parse", "email.parser",
    "multiprocessing", "multiprocessing.spawn", "concurrent.futures",
    "subprocess", "tempfile", "shutil", "glob", "fnmatch", "ctypes.util",
    "platform", "sysconfig", "importlib.metadata", "importlib.resources",
    "pkgutil", "zipimport", "difflib", "doctest", "pydoc", "tokenize",
    "ast", "dis", "opcode", "inspect", "dataclasses", "enum", "pprint",
    "textwrap", "string", "base64", "binascii", "struct", "array", "cmath",
    "random", "statistics", "decimal", "fractions", "datetime", "calendar",
    "locale", "gettext", "logging.handlers", "signal", "threading", "queue",
    "socket", "select", "selectors", "asyncio", "mmap",
]

hiddenimports = list(mediapipe_hidden) + list(falcon_hidden) + torch_stdlib + [
    "falcon_model",
    "focusmic.selftest",
    "focusmic.runtime",
    "focusmic.vendor.falcon.falcon_runtime",
    "falcon_model.models.Falcon",
    "falcon_model.models.Falcon_Contrastive",
    "falcon_model.models.Speaker_Contrastive_v2",
    "falcon_model.models.SISNRRepel",
    "falcon_model.models.base_model",
    "falcon_model.videomodels.frcnn_videomodel",
    "falcon_model.videomodels.resnet",
    "falcon_model.videomodels.shufflenetv2",
    "PySide6.QtSvg",
    "PySide6.QtNetwork",
    "pynvml",
    "keyboard",
    "sounddevice",
    "soxr",
    "_sounddevice_data",
]

a = Analysis(
    [str(ROOT / "packaging" / "focusmic_entry.py")],
    pathex=[str(ROOT), str(VENDOR)],
    binaries=mediapipe_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyTorch/CUDA is installed separately by FocusMic-Runtime.
        "torch",
        "torchgen",
        "functorch",
        "sympy",
        "networkx",
        "jinja2",
        "fsspec",
        "filelock",
        "typing_extensions",
        "mpmath",
        "tkinter",
        "tensorboard",
        "torchvision",
        "torchaudio",
        "pytest",
        "IPython",
        "notebook",
        "jupyter",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FocusMic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "focusmic" / "assets" / "icons" / "focusmic_icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FocusMic",
)
