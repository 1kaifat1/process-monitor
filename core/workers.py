"""Фоновые потоки опроса: не блокируют интерфейс и экономят ресурсы."""

from __future__ import annotations

import threading
import time
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal


class CollectorThread(QThread):
    """Периодически вызывает функцию сбора данных в отдельном потоке.

    Интервал читается заново после каждого цикла, поэтому настройки
    применяются «на лету». Если вкладка неактивна, опрос замедляется.
    """

    data_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        collector: Callable[[], dict],
        interval_getter: Callable[[], int],
        active_getter: Callable[[], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self._collector = collector
        self._interval_getter = interval_getter
        self._active_getter = active_getter
        self._stop_event = threading.Event()
        self._paused = threading.Event()

    def run(self) -> None:  # noqa: D401 - переопределение QThread.run
        while not self._stop_event.is_set():
            if not self._paused.is_set():
                try:
                    payload = self._collector()
                    if payload is not None:
                        self.data_ready.emit(payload)
                except Exception as exc:  # защита от падения потока
                    self.failed.emit(f"{self.name}: {exc}")
            try:
                interval = max(0.2, float(self._interval_getter()) / 1000.0)
            except Exception:
                interval = 2.0
            if self._active_getter is not None:
                try:
                    if not self._active_getter():
                        interval *= 3
                except Exception:
                    pass
            self._stop_event.wait(interval)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def force_cycle(self) -> None:
        """Разбудить поток для немедленного опроса."""
        # Простое решение: поток проснётся по таймауту; для мгновенного
        # обновления интерфейс использует отдельный разовый вызов.
        pass

    def stop(self) -> None:
        self._stop_event.set()
        self.wait(3000)


def stop_all(threads: list[CollectorThread]) -> None:
    for thread in threads:
        try:
            thread.stop()
        except Exception:
            pass
