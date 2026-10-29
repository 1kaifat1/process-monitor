"""Вкладка автозагрузки: реестр, папки и автоматические службы."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.utils import is_admin, open_in_explorer, open_path, relaunch_as_admin


class AutorunView(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._entries: list[dict] = []
        self._active = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        admin_row = QHBoxLayout()
        admin_row.setSpacing(8)
        self.admin_label = QLabel()
        self.admin_label.setObjectName("Muted")
        self.elevate_button = QPushButton(tr("Перезапустить от администратора"))
        self.elevate_button.clicked.connect(self._elevate)
        admin_row.addWidget(self.admin_label, 1)
        admin_row.addWidget(self.elevate_button)
        root.addLayout(admin_row)
        self._update_admin_label()

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            tr("Поиск: название, команда, расположение…")
        )
        self.search.setClearButtonEnabled(True)
        self.type_combo = QComboBox()
        self.type_combo.addItem(tr("Все типы"), "all")
        self.type_combo.addItem(tr("Реестр"), "Реестр")
        self.type_combo.addItem(tr("Папка"), "Папка")
        self.type_combo.addItem(tr("Служба"), "Служба")
        self.type_combo.setMinimumWidth(130)
        self.refresh_button = QPushButton(tr("Обновить"))
        self.toggle_button = QPushButton(tr("Включить / Отключить"))
        self.toggle_button.setObjectName("PrimaryButton")
        self.open_button = QPushButton(tr("Открыть файл"))
        toolbar.addWidget(self.search, 2)
        toolbar.addWidget(self.type_combo)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.toggle_button)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                tr("Состояние"),
                tr("Тип"),
                tr("Название"),
                tr("Команда"),
                tr("Расположение"),
                tr("Примечание"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(27)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        widths = [100, 80, 230, 380, 260, 150]
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.stats_label = QLabel(tr("Ожидание данных…"))
        self.stats_label.setObjectName("Muted")
        footer.addWidget(self.stats_label, 1)
        root.addLayout(footer)

        self.search.textChanged.connect(self._apply_filter)
        self.type_combo.currentIndexChanged.connect(self._apply_filter)
        self.refresh_button.clicked.connect(self.refresh_now)
        self.toggle_button.clicked.connect(self.toggle_selected)
        self.open_button.clicked.connect(self.open_selected)
        self.table.itemDoubleClicked.connect(lambda _item: self.toggle_selected())

    def _update_admin_label(self) -> None:
        if is_admin():
            self.admin_label.setText(
                tr("Права администратора получены — доступны все элементы автозагрузки.")
            )
            self.elevate_button.hide()
        else:
            self.admin_label.setText(
                tr(
                    "Без прав администратора нельзя менять системные ключи реестра и службы. "
                    "Запись пользователя и папка «Автозагрузка» доступны."
                )
            )
            self.elevate_button.show()

    def _elevate(self) -> None:
        if relaunch_as_admin():
            QApplication.quit()
        else:
            QMessageBox.warning(
                self,
                tr("Права администратора"),
                tr("Не удалось перезапустить приложение."),
            )

    def set_active(self, active: bool) -> None:
        self._active = active

    # ------------------------------------------------------------------
    def refresh_now(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            entries = self.manager.list_entries()
        except Exception as exc:
            entries = []
            self.status_message.emit(
                tr("Ошибка чтения автозагрузки: {error}", error=exc)
            )
        finally:
            QApplication.restoreOverrideCursor()
        self._entries = entries
        self._populate()

    def _populate(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for entry in self._entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            state_item = QTableWidgetItem(
                tr("Включено") if entry["enabled"] else tr("Отключено")
            )
            state_item.setForeground(
                QColor("#2ee6a8") if entry["enabled"] else QColor("#ffb020")
            )
            state_item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.table.setItem(row, 0, state_item)
            self.table.setItem(row, 1, QTableWidgetItem(tr(entry["type"])))
            self.table.setItem(row, 2, QTableWidgetItem(entry["name"]))
            self.table.setItem(row, 3, QTableWidgetItem(entry["command"]))
            self.table.setItem(row, 4, QTableWidgetItem(entry["location"]))
            self.table.setItem(
                row, 5, QTableWidgetItem(tr(entry.get("note", "")))
            )
        self.table.setSortingEnabled(True)
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search.text().strip().lower()
        entry_type = self.type_combo.currentData()
        visible = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            entry = self._entry_by_id(item.data(Qt.ItemDataRole.UserRole) if item else "")
            if entry is None:
                self.table.setRowHidden(row, True)
                continue
            matches = True
            if entry_type != "all" and entry["type"] != entry_type:
                matches = False
            if query:
                haystack = " ".join(
                    str(entry.get(key, ""))
                    for key in ("name", "command", "location", "type")
                ).lower()
                if query not in haystack:
                    matches = False
            self.table.setRowHidden(row, not matches)
            if matches:
                visible += 1
        disabled = sum(1 for entry in self._entries if not entry["enabled"])
        self.stats_label.setText(
            tr(
                "Элементов: {total} · включено: {enabled} · отключено: {disabled}",
                total=len(self._entries),
                enabled=len(self._entries) - disabled,
                disabled=disabled,
            )
            + " "
            + tr("· показано: {shown}", shown=visible)
        )

    def _entry_by_id(self, entry_id: str) -> dict | None:
        for entry in self._entries:
            if entry.get("id") == entry_id:
                return entry
        return None

    def _selected_entry(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return self._entry_by_id(item.data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------
    def toggle_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.status_message.emit(tr("Выберите элемент автозагрузки"))
            return
        ok, message = self.manager.toggle(entry)
        if not ok:
            QMessageBox.warning(self, tr("Автозагрузка"), message)
        else:
            self.status_message.emit(message)
        self.refresh_now()

    def open_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.status_message.emit(tr("Выберите элемент автозагрузки"))
            return
        target = entry.get("target") or ""
        if target and open_in_explorer(target):
            return
        if target and open_path(target):
            return
        QMessageBox.information(
            self,
            tr("Расположение"),
            tr(
                "Не удалось открыть файл.\n\n{error}",
                error=entry.get("command") or tr("Команда отсутствует"),
            ),
        )

