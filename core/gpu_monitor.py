"""Мониторинг NVIDIA GPU через NVML (без блокирующих WMI-запросов).

Модуль рассчитан на опрос из фонового потока: ``GPUMonitor.__init__`` один раз
инициализирует NVML, а ``get_stats`` только читает счётчики. Если библиотека
или драйвер недоступны, ``get_stats`` сразу возвращает ``None``.

Автономная проверка::

    python core/gpu_monitor.py
"""

from __future__ import annotations

import json
import time
from typing import Any

try:
    import pynvml
except ImportError:  # драйвер/библиотека NVIDIA не установлены
    pynvml = None


class GPUMonitor:
    """Первичный NVIDIA GPU: загрузка, температура, VRAM, частота, вентилятор."""

    def __init__(self) -> None:
        self._initialized = False
        self._handle: Any = None
        self._name = "GPU"
        if pynvml is None:
            return
        try:
            pynvml.nvmlInit()
            if pynvml.nvmlDeviceGetCount() <= 0:
                pynvml.nvmlShutdown()
                return
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self._handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            self._name = str(name).strip() or "GPU"
            self._initialized = True
        except Exception:
            self._handle = None
            self._initialized = False
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return self._initialized

    def _safe(self, callback) -> Any:
        try:
            return callback()
        except Exception:
            return None

    def get_stats(self) -> dict[str, Any] | None:
        """Снять метрики. ``None`` — GPU/NVML недоступны (без задержек)."""
        if not self._initialized or self._handle is None or pynvml is None:
            return None

        utilization = self._safe(
            lambda: pynvml.nvmlDeviceGetUtilizationRates(self._handle)
        )
        memory = self._safe(lambda: pynvml.nvmlDeviceGetMemoryInfo(self._handle))
        if utilization is None and memory is None:
            return None

        memory_total = int(memory.total) if memory is not None else None
        memory_used = int(memory.used) if memory is not None else None
        memory_percent = None
        if memory_total and memory_used is not None:
            memory_percent = round(memory_used * 100.0 / memory_total, 1)

        return {
            "available": True,
            "name": self._name,
            "temperature_c": self._safe(
                lambda: pynvml.nvmlDeviceGetTemperature(
                    self._handle, pynvml.NVML_TEMPERATURE_GPU
                )
            ),
            "gpu_percent": int(utilization.gpu) if utilization is not None else None,
            "memory_percent": (
                int(utilization.memory) if utilization is not None else None
            ),
            "vram_used_mb": (
                memory_used // (1024 * 1024) if memory_used is not None else None
            ),
            "vram_total_mb": (
                memory_total // (1024 * 1024) if memory_total is not None else None
            ),
            "vram_percent": memory_percent,
            "clock_mhz": self._safe(
                lambda: pynvml.nvmlDeviceGetClockInfo(
                    self._handle, pynvml.NVML_CLOCK_GRAPHICS
                )
            ),
            "fan_percent": self._safe(
                lambda: pynvml.nvmlDeviceGetFanSpeed(self._handle)
            ),
            "timestamp": time.time(),
        }

    def shutdown(self) -> None:
        if self._initialized and pynvml is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
        self._initialized = False
        self._handle = None


if __name__ == "__main__":
    monitor = GPUMonitor()
    stats = monitor.get_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2) if stats else "GPU: N/A")
    monitor.shutdown()
