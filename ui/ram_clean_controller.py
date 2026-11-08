"""Кнопка и фоновая очистка RAM без раздувания MainWindow."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QPushButton

from core.i18n import tr
from core.ram_cleaner import RamCleanResult, clean_ram


class RamCleanWorker(QThread):
    result_ready = pyqtSignal(object)

    def run(self) -> None:  # noqa: D401 - переопределение QThread.run
        try:
            result = clean_ram()
        except Exception as exc:
            result = RamCleanResult(status="error", detail=str(exc))
        self.result_ready.emit(result)


class RamCleanController:
    def __init__(self, button: QPushButton, window: QMainWindow) -> None:
        self._button = button
        self._window = window
        self._worker: RamCleanWorker | None = None
        self._closed = False
        button.clicked.connect(self.clean)

    def clean(self) -> None:
        if self._closed:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._button.setEnabled(False)
        self._button.setText(tr("Очистка…"))
        self._window.statusBar().showMessage(tr("Очистка памяти…"), 6000)

        worker = RamCleanWorker(self._window)
        self._worker = worker
        worker.result_ready.connect(self._on_result)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_result(self, result: RamCleanResult) -> None:
        if result.status == "permission_denied":
            self._window.statusBar().showMessage(
                tr("Требуются права администратора для глубокой очистки."), 6000
            )
            QMessageBox.warning(
                self._window,
                tr("Очистка памяти"),
                tr(
                    "Требуются права администратора для глубокой очистки. "
                    "Перезапустите Pulse Monitor с повышенными правами."
                ),
            )
            return
        if result.status == "unsupported":
            QMessageBox.information(
                self._window,
                tr("Очистка памяти"),
                tr("Очистка памяти недоступна на этой платформе."),
            )
            return
        if result.status == "error":
            QMessageBox.warning(
                self._window,
                tr("Очистка памяти"),
                tr(
                    "Не удалось очистить память: {error}",
                    error=result.detail or tr("неизвестно"),
                ),
            )
            return

        message = tr(
            "Очистка завершена: освобождено {mb} МБ",
            mb=f"{result.freed_mb:.1f}",
        )
        if result.status == "partial":
            message += " · " + tr(
                "часть процессов недоступна без прав администратора"
            )
        self._window.statusBar().showMessage(message, 6000)

    def _on_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._button.setEnabled(True)
        self._button.setText(tr("Очистить память"))

    def stop(self) -> None:
        self._closed = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(10000)
