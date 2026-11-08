"""Фоновый опрос GPU, изолированный от MainWindow."""

from __future__ import annotations

from core.config_manager import config
from core.gpu_monitor import GPUMonitor
from core.workers import CollectorThread


class GpuMonitorController:
    def __init__(self, window, dashboard) -> None:
        self._window = window
        self._monitor = GPUMonitor()
        self._thread = CollectorThread(
            "GPU",
            self._monitor.get_stats,
            lambda: int(config.get("intervals.gpu", 1500)),
            lambda: self._window._is_page_active(0),
        )
        self._thread.data_ready.connect(dashboard.set_gpu_snapshot)
        self._thread.start()

    def force_cycle(self) -> None:
        self._thread.force_cycle()

    def stop(self) -> None:
        self._thread.stop()
        self._monitor.shutdown()
