"""Locate and load the external PyTorch/CUDA runtime.

The main FocusMic installer deliberately does not bundle PyTorch: the CUDA
build is several gigabytes and does not fit GitHub's 2 GiB release-asset
limit.  Instead the separate ``FocusMic-Runtime`` installer places it in
``%LOCALAPPDATA%\\FocusMic\\runtime``.  This module locates that directory,
validates the Python ABI/version, and imports ``torch`` from it.

Everything here must stay importable without torch so the UI can start and
show installation guidance when the runtime is missing.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .i18n import t
from .paths import localappdata_dir

RUNTIME_DIR_NAME = "runtime"
EXPECTED_TORCH = "2.9.1"
EXPECTED_CUDA = "12.8"
RUNTIME_INFO = "RUNTIME_INFO.json"
RELEASES_URL = "https://github.com/ms12667/FocusMic/releases/latest"

# os.add_dll_directory() returns a handle that must stay open for the DLL
# search path to remain active.
_dll_handles: list[object] = []
_torch = None
_loaded_status: "RuntimeStatus | None" = None


@dataclass(frozen=True)
class RuntimeStatus:
    ok: bool
    root: Path
    torch_dir: Path | None = None
    torch_version: str = ""
    cuda_version: str = ""
    python_tag: str = ""
    cuda_available: bool | None = None
    reason: str = ""
    detail: str = ""

    def message(self) -> str:
        if self.ok:
            if self.cuda_version:
                return t("runtime.status.ready_cuda",
                         torch=self.torch_version, cuda=self.cuda_version)
            return t("runtime.status.ready", torch=self.torch_version)
        text = self.reason or t("runtime.status.unavailable")
        if self.root:
            text += t("runtime.status.root", root=self.root)
        if self.detail:
            text += f"\n{self.detail}"
        return text


def runtime_root() -> Path:
    """Directory containing ``torch/`` (override with FOCUSMIC_RUNTIME)."""
    override = os.environ.get("FOCUSMIC_RUNTIME")
    if override:
        return Path(override).expanduser().resolve()
    return localappdata_dir() / RUNTIME_DIR_NAME


def _python_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _dev_torch_dir() -> Path | None:
    """In a source checkout, use the active virtualenv's torch."""
    if getattr(sys, "frozen", False):
        return None
    try:
        spec = importlib.util.find_spec("torch")
    except Exception:
        return None
    if spec and spec.origin:
        return Path(spec.origin).resolve().parent
    return None


def _candidate() -> tuple[Path, Path | None]:
    root = runtime_root()
    if (root / "torch" / "version.py").is_file():
        return root, root / "torch"
    dev = _dev_torch_dir()
    if dev is not None:
        return dev.parent, dev
    return root, None


def _read_versions(torch_dir: Path) -> tuple[str, str]:
    try:
        text = (torch_dir / "version.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", ""
    version = re.search(r"__version__\s*=\s*'([^']+)'", text)
    cuda = re.search(r"(?m)^cuda[^\n=]*=\s*'([^']+)'", text)
    return (version.group(1) if version else "", cuda.group(1) if cuda else "")


def _extension_tag(torch_dir: Path) -> str:
    for pattern in ("_C*.pyd", "_C*.so"):
        for path in torch_dir.glob(pattern):
            match = re.search(r"_C\.(cp\d+)", path.name)
            if match:
                return match.group(1)
    return ""


def check_installed() -> RuntimeStatus:
    """Fast file-level check; does not import torch or touch the GPU."""
    root, torch_dir = _candidate()
    if torch_dir is None:
        return RuntimeStatus(
            ok=False, root=root, reason=t("runtime.status.missing"),
            detail=t("runtime.status.missing_detail"),
        )
    version, cuda = _read_versions(torch_dir)
    tag = _extension_tag(torch_dir)
    expected_tag = _python_tag()
    if not version or not tag:
        return RuntimeStatus(
            ok=False, root=root, torch_dir=torch_dir,
            torch_version=version, cuda_version=cuda,
            reason=t("runtime.status.incomplete"),
            detail=t("runtime.status.incomplete_detail"),
        )
    if tag != expected_tag:
        return RuntimeStatus(
            ok=False, root=root, torch_dir=torch_dir,
            torch_version=version, cuda_version=cuda, python_tag=tag,
            reason=t("runtime.status.abi"),
            detail=t("runtime.status.abi_detail", actual=tag, expected=expected_tag),
        )
    if not version.startswith(EXPECTED_TORCH):
        return RuntimeStatus(
            ok=False, root=root, torch_dir=torch_dir,
            torch_version=version, cuda_version=cuda, python_tag=tag,
            reason=t("runtime.status.torch", expected=EXPECTED_TORCH),
            detail=t("runtime.status.torch_detail", actual=version),
        )
    if cuda != EXPECTED_CUDA:
        return RuntimeStatus(
            ok=False, root=root, torch_dir=torch_dir,
            torch_version=version, cuda_version=cuda, python_tag=tag,
            reason=t("runtime.status.cuda", expected=EXPECTED_CUDA),
            detail=t("runtime.status.cuda_detail",
                     actual=cuda or t("common.unknown")),
        )
    return RuntimeStatus(
        ok=True, root=root, torch_dir=torch_dir,
        torch_version=version, cuda_version=cuda, python_tag=tag,
    )


def _add_dll_dir(path: Path) -> None:
    if os.name != "nt" or not path.is_dir():
        return
    try:
        _dll_handles.append(os.add_dll_directory(str(path)))
    except (AttributeError, OSError):
        pass


def _prepare_import(root: Path, torch_dir: Path) -> None:
    if str(root) not in sys.path:
        # Append rather than prepend so bundled numpy/PySide6 keep precedence.
        sys.path.append(str(root))
    _add_dll_dir(torch_dir / "lib")
    _add_dll_dir(root)
    # PyInstaller's onedir root (and PySide6's MSVC runtime) may be needed by
    # torch's DLLs even though torch itself lives outside the bundle.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundle = Path(meipass)
        _add_dll_dir(bundle)
        _add_dll_dir(bundle / "PySide6")


def ensure_runtime(check_cuda: bool = False) -> RuntimeStatus:
    """Import torch from the external runtime, or return why it is unavailable."""
    global _torch, _loaded_status
    status = check_installed()
    if not status.ok:
        _loaded_status = status
        return status

    if _torch is None:
        assert status.torch_dir is not None
        _prepare_import(status.root, status.torch_dir)
        try:
            import torch  # noqa: F401
        except Exception as exc:  # ImportError, OSError, DLL load failures
            detail = f"{type(exc).__name__}: {exc}"
            failed = RuntimeStatus(
                ok=False, root=status.root, torch_dir=status.torch_dir,
                torch_version=status.torch_version,
                cuda_version=status.cuda_version,
                python_tag=status.python_tag,
                reason=t("runtime.status.load_failed"),
                detail=detail,
            )
            _loaded_status = failed
            return failed
        _torch = torch
        status = RuntimeStatus(
            ok=True, root=status.root, torch_dir=status.torch_dir,
            torch_version=str(torch.__version__),
            cuda_version=str(torch.version.cuda or ""),
            python_tag=status.python_tag,
        )

    if check_cuda:
        available = False
        detail = ""
        try:
            available = bool(_torch.cuda.is_available())
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
        if not available:
            failed = RuntimeStatus(
                ok=False, root=status.root, torch_dir=status.torch_dir,
                torch_version=status.torch_version,
                cuda_version=status.cuda_version,
                python_tag=status.python_tag, cuda_available=False,
                reason=t("runtime.status.cuda_unavailable"),
                detail=detail or t("runtime.status.cuda_unavailable_detail"),
            )
            _loaded_status = failed
            return failed
        status = RuntimeStatus(
            ok=True, root=status.root, torch_dir=status.torch_dir,
            torch_version=status.torch_version,
            cuda_version=status.cuda_version,
            python_tag=status.python_tag, cuda_available=True,
        )

    _loaded_status = status
    return status


def loaded_status() -> RuntimeStatus | None:
    return _loaded_status
