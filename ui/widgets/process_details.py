"""Диалог подробной информации о процессе."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.utils import open_in_explorer


def _label(text: str, muted: bool = False) -> QLabel:
    widget = QLabel(text or "—")
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    widget.setWordWrap(True)
    if muted:
        widget.setObjectName("Muted")
    return widget


class ProcessDetailsDialog(QDialog):
    def __init__(self, collector, pid: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.collector = collector
        self.pid = pid
        self.info = collector.describe(pid)

        self.setWindowTitle(tr("Процесс {pid} — подробности", pid=pid))
        self.setMinimumSize(680, 560)
        self.resize(760, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel(self.info.get("name") or f"PID {pid}")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        if self.info.get("error"):
            error = QLabel(tr(str(self.info["error"])))
            error.setObjectName("BadgeWarning")
            error.setWordWrap(True)
            root.addWidget(error)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        form = QFormLayout(container)
        form.setContentsMargins(4, 4, 10, 4)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        rows = [
            ("PID", self.info.get("pid")),
            (tr("Родительский PID"), self.info.get("ppid")),
            (tr("Пользователь"), self.info.get("user")),
            (tr("Статус"), tr(str(self.info.get("status") or ""))),
            (tr("Запущен"), self.info.get("created")),
            (tr("Время работы"), self.info.get("uptime")),
            (tr("Файл"), self.info.get("exe")),
            (tr("Компания"), self.info.get("file_company")),
            (tr("Описание"), self.info.get("file_description")),
            (tr("Версия файла"), self.info.get("file_version")),
            (tr("Рабочая папка"), self.info.get("cwd")),
            (tr("Командная строка"), self.info.get("cmdline")),
            ("CPU", self.info.get("cpu")),
            (tr("Память (RSS)"), self.info.get("rss")),
            (tr("Виртуальная память"), self.info.get("vms")),
            (tr("Доля памяти"), self.info.get("mem_pct")),
            (tr("Потоков"), self.info.get("threads")),
            (tr("Дескрипторов"), self.info.get("handles")),
            (tr("Открытых файлов"), self.info.get("open_files")),
            (tr("Приоритет"), tr(str(self.info.get("nice") or ""))),
        ]
        for caption, value in rows:
            form.addRow(_label(caption, muted=True), _label(str(value) if value is not None else "—"))

        connections = self.info.get("connections") or []
        connections_text = (
            "\n".join(connections) if connections else tr("Нет активных соединений")
        )
        form.addRow(_label(tr("Соединения"), muted=True), _label(connections_text))

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        if self.info.get("exe"):
            open_button = QPushButton(tr("Открыть папку"))
            open_button.clicked.connect(self._open_folder)
            buttons.addWidget(open_button)
        buttons.addStretch(1)
        close_button = QPushButton(tr("Закрыть"))
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def _open_folder(self) -> None:
        open_in_explorer(self.info.get("exe", ""))
