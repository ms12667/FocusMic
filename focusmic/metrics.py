"""Lightweight CPU / RAM / GPU sampling for the performance page."""
from __future__ import annotations

import psutil


class MetricsSampler:
    def __init__(self):
        self.process = psutil.Process()
        self.gpu = None
        self.gpu_error = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self.gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception as exc:
            self._nvml = None
            self.gpu_error = str(exc)
        psutil.cpu_percent(None)

    def sample(self) -> dict:
        cpu = float(psutil.cpu_percent(None))
        vm = psutil.virtual_memory()
        try:
            rss = self.process.memory_info().rss / (1024 * 1024)
            proc_cpu = float(self.process.cpu_percent(None))
        except Exception:
            rss, proc_cpu = 0.0, 0.0
        gpu_util = gpu_mem = gpu_total = 0.0
        if self._nvml is not None:
            try:
                util = self._nvml.nvmlDeviceGetUtilizationRates(self.gpu)
                mem = self._nvml.nvmlDeviceGetMemoryInfo(self.gpu)
                gpu_util = float(util.gpu)
                gpu_mem = mem.used / (1024 * 1024)
                gpu_total = mem.total / (1024 * 1024)
            except Exception as exc:
                self.gpu_error = str(exc)
        return {
            "cpu": cpu,
            "ram": float(vm.percent),
            "ram_used": vm.used / (1024 * 1024),
            "app_ram": rss,
            "app_cpu": proc_cpu,
            "gpu": gpu_util,
            "vram": gpu_mem,
            "vram_total": gpu_total,
            "gpu_error": self.gpu_error,
        }

    def close(self):
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
