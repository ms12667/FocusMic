"""Per-process CPU / RAM / GPU sampling for the performance page.

Everything here describes the FocusMic process only. Global machine load is
deliberately not reported: the page answers "what is FocusMic using?".

GPU load comes from the Windows PDH ``GPU Engine`` counter and uses the busiest
engine for this PID, which is the same definition as Task Manager's GPU column.
NVML per-process SM utilization is kept only as a fallback.
"""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes

import psutil

PDH_FMT_DOUBLE = 0x00000200
# PdhGetFormattedCounterArrayW returns a signed LONG; 0x800007D2 is
# PDH_MORE_DATA but ctypes reports it as -0x7FFFF82E.
PDH_MORE_DATA = -0x7FFFF82E


class _PdhValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PdhItem(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PdhValue)]


class GpuEngineCounter:
    """Task-Manager-compatible per-process GPU load via PDH.

    Task Manager's process GPU column is the busiest GPU engine for that PID,
    not NVML's SM utilization and not a sum over engines. The Windows
    ``GPU Engine(*)\\Utilization Percentage`` counter gives exactly that.
    """

    def __init__(self):
        self.available = False
        self._pdh = None
        self._pid = psutil.Process().pid
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._size = wintypes.DWORD(0)
        self._count = wintypes.DWORD(0)
        self._buffer = None
        try:
            self._pdh = ctypes.WinDLL("pdh.dll")
            self._pdh.PdhOpenQueryW.argtypes = [
                wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
            self._pdh.PdhOpenQueryW.restype = wintypes.LONG
            self._pdh.PdhAddEnglishCounterW.argtypes = [
                ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_void_p)]
            self._pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
            self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            self._pdh.PdhCollectQueryData.restype = wintypes.LONG
            self._pdh.PdhGetFormattedCounterArrayW.argtypes = [
                ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p]
            self._pdh.PdhGetFormattedCounterArrayW.restype = wintypes.LONG
            self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
            if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
                return
            if self._pdh.PdhAddEnglishCounterW(
                    self._query, r"\GPU Engine(*)\Utilization Percentage",
                    0, ctypes.byref(self._counter)) != 0:
                self.close()
                return
            self.available = True
        except Exception:
            self.close()

    def sample(self) -> float | None:
        if not self.available:
            return None
        try:
            if self._pdh.PdhCollectQueryData(self._query) != 0:
                return None
            self._size = wintypes.DWORD(0)
            self._count = wintypes.DWORD(0)
            status = self._pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_DOUBLE,
                ctypes.byref(self._size), ctypes.byref(self._count), None)
            if status != PDH_MORE_DATA or self._size.value == 0:
                return None
            if self._buffer is None or len(self._buffer) < self._size.value:
                self._buffer = ctypes.create_string_buffer(self._size.value)
            status = self._pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_DOUBLE,
                ctypes.byref(self._size), ctypes.byref(self._count),
                self._buffer)
            if status != 0:
                return None
            pid = self._pid
            arr = ctypes.cast(self._buffer, ctypes.POINTER(_PdhItem))
            best = 0.0
            found = False
            for i in range(self._count.value):
                name = arr[i].szName or ""
                match = re.search(r"pid_(\d+)_", name)
                if not match or int(match.group(1)) != pid:
                    continue
                found = True
                best = max(best, float(arr[i].FmtValue.doubleValue))
            return best if found else 0.0
        except Exception:
            return None

    def close(self):
        self.available = False
        if self._pdh is not None and self._query:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._buffer = None


class MetricsSampler:
    def __init__(self):
        self.process = psutil.Process()
        self.pid = self.process.pid
        self.cpu_count = max(1, psutil.cpu_count(logical=True) or 1)
        self.gpu = None
        self.gpu_error = None
        self.gpu_supported = False
        self._gpu_engine = GpuEngineCounter()
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self.gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.gpu_supported = hasattr(pynvml, "nvmlDeviceGetProcessUtilization")
        except Exception as exc:
            self._nvml = None
            self.gpu_error = str(exc)
        self.gpu_supported = self.gpu_supported or self._gpu_engine.available
        self.process.cpu_percent(None)

    def _process_gpu_util(self) -> float:
        if self._nvml is None or self.gpu is None or not self.gpu_supported:
            return 0.0
        try:
            now = int(time.time() * 1_000_000)
            samples = self._nvml.nvmlDeviceGetProcessUtilization(
                self.gpu, now - 2_000_000)
            latest = None
            for sample in samples:
                if sample.pid != self.pid:
                    continue
                if latest is None or sample.timeStamp > latest.timeStamp:
                    latest = sample
            return float(latest.smUtil) if latest is not None else 0.0
        except Exception as exc:
            self.gpu_error = str(exc)
            self.gpu_supported = False
            return 0.0

    def sample(self) -> dict:
        try:
            # Task Manager's Memory column is the private working set, not RSS
            # (which also counts shared pages). USS is the closest psutil value.
            try:
                rss = self.process.memory_full_info().uss / (1024 * 1024)
            except Exception:
                rss = self.process.memory_info().rss / (1024 * 1024)
            raw_cpu = float(self.process.cpu_percent(None))
            # psutil can return >100% for multi-threaded processes; Task
            # Manager reports percentage of the whole machine.
            app_cpu = min(100.0, raw_cpu / self.cpu_count)
            threads = self.process.num_threads()
        except Exception:
            rss, app_cpu, threads = 0.0, 0.0, 0
        gpu_util = None
        if self._gpu_engine.available:
            gpu_util = self._gpu_engine.sample()
        if gpu_util is None:
            gpu_util = self._process_gpu_util()
        return {
            "app_cpu": app_cpu,
            "app_ram": rss,
            "app_gpu": gpu_util,
            "threads": threads,
            "pid": self.pid,
            "gpu_supported": self.gpu_supported,
            "gpu_error": self.gpu_error,
        }

    def close(self):
        if getattr(self, "_gpu_engine", None) is not None:
            self._gpu_engine.close()
        if getattr(self, "_nvml", None) is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
