"""Компактный диалог принудительной разблокировки файла или папки.

Открывается из контекстного меню Проводника (``--unlock <путь>``) и не
запускает основное окно монитора. Список удерживающих процессов берётся из
Restart Manager, завершение — принудительное (``TerminateProcess``).

Если процесс защищён (запущен от администратора или системы), диалог
показывает понятное сообщение и кнопку перезапуска с UAC-повышением.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.file_unlocker import (
    LockingProcess,
    RestartManagerError,
    UnlockResult,
    find_locking_processes,
    force_unlock,
)
from core.i18n import tr
from core.utils import relaunch_elevated

_COLUMNS = ("Имя", "PID", "Тип", "Путь")


class UnlockDialog(QDialog):
    """Список процессов, мешающих удалить/переместить файл, и их завершение."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = str(path or "").strip().strip('"')
        self.processes: list[LockingProcess] = []

        self.setWindowTitle(tr("Разблокировка файла"))
        self.setMinimumSize(700, 430)
        self.resize(800, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel(tr("Разблокировка файла или папки"))
        title.setObjectName("PageTitle")
        root.addWidget(title)

        info = QLabel(tr("Файл или папка: {path}", path=self.path))
        info.setObjectName("Muted")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(info)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.warning = QLabel("")
        self.warning.setObjectName("BadgeWarning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        root.addWidget(self.warning)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(text) for text in _COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.refresh_button = QPushButton(tr("Обновить"))
        self.admin_button = QPushButton(tr("Перезапустить от имени Администратора"))
        self.admin_button.hide()
        self.close_button = QPushButton(tr("Закрыть"))
        self.unlock_button = QPushButton(
            tr("Завершить принудительно и удалить блокировку")
        )
        self.unlock_button.setObjectName("PrimaryButton")
        self.unlock_button.setEnabled(False)

        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.admin_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.unlock_button)
        root.addLayout(buttons)

        self.refresh_button.clicked.connect(self.refresh)
        self.admin_button.clicked.connect(self._relaunch_as_admin)
        self.close_button.clicked.connect(self.reject)
        self.unlock_button.clicked.connect(self._unlock)

        # Сначала даём диалогу отрисоваться, затем опрашиваем Restart Manager.
        QTimer.singleShot(0, self.refresh)

    # ------------------------------------------------------------------
    # Поиск процессов
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Обновить список процессов, удерживающих файл или папку."""
        self.warning.hide()
        self.admin_button.hide()
        self.table.setRowCount(0)
        self.status.setText(tr("Ищу процессы, удерживающие файл…"))
        self.unlock_button.setEnabled(False)

        if not self.path:
            self.status.setText(tr("Не указан путь к файлу или папке."))
            return
        if not Path(self.path).exists():
            self.status.setText(tr("Файл или папка не найдены."))
            return

        try:
            self.processes = find_locking_processes(self.path)
        except RestartManagerError as exc:
            self.processes = []
            self.status.setText(
                tr("Не удалось опросить Restart Manager: {error}", error=str(exc))
            )
            return
        except Exception as exc:  # pragma: no cover - редкие системные ошибки
            self.processes = []
            self.status.setText(tr("Ошибка: {error}", error=str(exc)))
            return

        self._fill_table(self.processes)
        self.unlock_button.setEnabled(bool(self.processes))
        if not self.processes:
            self.status.setText(
                tr("Файл не заблокирован — удерживающих процессов не найдено.")
            )
        else:
            self.status.setText(
                tr("Найдено процессов: {count}", count=len(self.processes))
            )

    def _fill_table(self, processes: list[LockingProcess]) -> None:
        self.table.setRowCount(len(processes))
        for row, process in enumerate(processes):
            name = QTableWidgetItem(process.name or process.app_name)
            name.setToolTip(process.app_name or process.name)
            pid = QTableWidgetItem(str(process.pid))
            pid.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            app_type = QTableWidgetItem(tr(process.app_type_key))
            location = QTableWidgetItem(process.exe or process.app_name or "—")
            location.setToolTip(process.exe or process.app_name)
            for column, item in enumerate((name, pid, app_type, location)):
                self.table.setItem(row, column, item)

    # ------------------------------------------------------------------
    # Завершение и повышение прав
    # ------------------------------------------------------------------
    def _unlock(self) -> None:
        if not self.processes:
            return
        answer = QMessageBox.question(
            self,
            tr("Завершение процессов"),
            tr(
                "Завершить принудительно {count} процесс(ов)? "
                "Несохранённые данные этих приложений могут быть потеряны.",
                count=len(self.processes),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.setEnabled(False)
        try:
            result = force_unlock(self.path, self.processes)
        finally:
            self.setEnabled(True)

        self.refresh()
        self._apply_result(result)

    def _apply_result(self, result: UnlockResult) -> None:
        """Показать итог завершения поверх обновлённого списка."""
        if result.error == "not_found":
            self.status.setText(tr("Файл или папка не найдены."))
            return
        if result.error == "empty_path":
            self.status.setText(tr("Не указан путь к файлу или папке."))
            return
        if result.error:
            self.status.setText(tr("Ошибка: {error}", error=result.error))
            return

        if result.success:
            if result.terminated:
                self.status.setText(
                    tr(
                        "Блокировка снята: завершено процессов — {count}, "
                        "дескрипторы освобождены.",
                        count=len(result.terminated),
                    )
                )
            else:
                self.status.setText(tr("Файл не был заблокирован."))
            return

        # Процесс, завершившийся самостоятельно, — не ошибка разблокировки.
        real_failures = [
            item for item in result.failed if item[1] != "already_exited"
        ]
        if not result.remaining and not real_failures:
            if result.terminated:
                self.status.setText(
                    tr(
                        "Блокировка снята: завершено процессов — {count}, "
                        "дескрипторы освобождены.",
                        count=len(result.terminated),
                    )
                )
            else:
                self.status.setText(tr("Файл не был заблокирован."))
            return

        details: list[str] = []
        for process, reason in real_failures:
            details.append(
                f"{process.name} (PID {process.pid}): {self._reason_text(reason)}"
            )
        if result.remaining:
            for process in result.remaining:
                text = f"{process.name} (PID {process.pid})"
                if text not in details:
                    details.append(text)
        self.status.setText(
            tr(
                "Не удалось снять блокировку. Остались процессы: {details}",
                details="; ".join(details) or tr("неизвестно"),
            )
        )

        if result.access_denied or any(
            reason == "access_denied" for _proc, reason in result.failed
        ):
            self.warning.setText(
                tr(
                    "Недостаточно прав: часть процессов запущена от имени "
                    "администратора или системы. Перезапустите Pulse Monitor "
                    "с повышенными правами, чтобы завершить их."
                )
            )
            self.warning.show()
            self.admin_button.show()

    @staticmethod
    def _reason_text(reason: str) -> str:
        return {
            "access_denied": tr("доступ запрещён (нужны права администратора)"),
            "system": tr("системный процесс защищён"),
            "already_exited": tr("процесс уже завершён"),
        }.get(reason, reason)

    def _relaunch_as_admin(self) -> None:
        """Перезапустить приложение от администратора для того же пути."""
        if relaunch_elevated(["--unlock", self.path]):
            self.accept()
            return
        QMessageBox.warning(
            self,
            tr("Повышение прав"),
            tr("Не удалось запустить приложение от имени администратора."),
        )
