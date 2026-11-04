"""Stage the external PyTorch/CUDA runtime for FocusMic-Runtime.iss.

The runtime is copied (hard-linked when possible) from the build virtualenv so
the packaged files match exactly the ABI/versions used by FocusMic.exe.
Run with the project's .venv Python:

    .venv\\Scripts\\python.exe packaging\\build_runtime.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / ".venv" / "Lib" / "site-packages"
OUT = ROOT / "build-tools" / "runtime" / "payload"

PACKAGES = [
    "torch",
    "torchgen",
    "functorch",
    "filelock",
    "typing_extensions.py",
    "sympy",
    "networkx",
    "jinja2",
    "markupsafe",
    "fsspec",
    "setuptools",
    "mpmath",
]
EXTRA = [
    "torch-2.9.1+cu128.dist-info",
    "_distutils_hack",
]


def _link_or_copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            _link_or_copy(child, dst / child.name)
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _read_torch_version() -> tuple[str, str]:
    text = (SITE / "torch" / "version.py").read_text(encoding="utf-8")
    version = re.search(r"__version__\s*=\s*'([^']+)'", text)
    cuda = re.search(r"(?m)^cuda[^\n=]*=\s*'([^']+)'", text)
    return (version.group(1) if version else "", cuda.group(1) if cuda else "")


def main() -> int:
    if not (SITE / "torch").is_dir():
        raise SystemExit(f"torch not found in {SITE}")
    version, cuda = _read_torch_version()
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    if not version.startswith("2.9.1") or cuda != "12.8":
        raise SystemExit(f"unexpected torch {version} / CUDA {cuda}")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    missing = []
    for name in PACKAGES + EXTRA:
        src = SITE / name
        if not src.exists():
            missing.append(name)
            continue
        _link_or_copy(src, OUT / name)
    if missing:
        raise SystemExit("missing runtime packages: " + ", ".join(missing))

    # Headers and import libraries are only needed to build C++ extensions,
    # not to run Falcon inference.  Dropping them keeps the installer safely
    # below GitHub's 2 GiB limit.
    for rel in ("torch/include",):
        shutil.rmtree(OUT / rel, ignore_errors=True)
    for pattern in ("torch/lib/*.lib", "torch/lib/*.exp", "torch/lib/*.pdb"):
        for path in OUT.glob(pattern):
            path.unlink(missing_ok=True)
    for cache in (OUT / "torch").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    info = {
        "name": "FocusMic AI Runtime",
        "torch": version,
        "cuda": cuda,
        "python": sys.version.split()[0],
        "python_tag": tag,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "packages": PACKAGES + EXTRA,
    }
    (OUT / "RUNTIME_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"[FocusMic] Runtime staged: torch {version} / CUDA {cuda} / {tag}")
    print(f"[FocusMic] Payload: {OUT} ({total / 1e9:.2f} GB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
