"""Вкладка процессов: модель, фильтрация и действия."""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import PROCESS_COLUMNS, config
from core.utils import export_csv, format_bytes, open_in_explorer

NUMERIC_KEYS = {"pid", "ppid", "cpu", "mem", "mem_pct", "threads", "handles", "session"}


def _display(row: dict, key: str) -> str:
    if key == "mem":
        return row.get("mem_text") or format_bytes(row.get("mem", 0))
    if key == "cpu":
        return row.get("cpu_text") or f"{row.get('cpu', 0):.1f}%"
    if key == "mem_pct":
        return row.get("mem_pct_text") or f"{row.get('mem_pct', 0):.1f}%"
    value = row.get(key, "")
    return "" if value is None else str(value)


def _sort_value(row: dict, key: str):
    if key in NUMERIC_KEYS:
        try:
            return float(row.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return _display(row, key).lower()


class ProcessTableModel(QAbstractTableModel):
    """Таблица процессов без пересоздания виджетов — быстро и экономно."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []
        self._keys: list[str] = []
        self._headers: list[str] = []
        self._widths: list[int] = []
        self.configure_columns()

    def configure_columns(self) -> None:
        self.beginResetModel()
        self._keys = []
        self._headers = []
        self._widths = []
        for key, title, width, _default in PROCESS_COLUMNS:
            if config.get(f"processes.columns.{key}", True):
                self._keys.append(key)
                self._headers.append(title)
                self._widths.append(width)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._keys)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        key = self._keys[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return _display(row, key)
        if role == Qt.ItemDataRole.UserRole:
            return _sort_value(row, key)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key in NUMERIC_KEYS:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [
                f"{row.get('name', '')} (PID {row.get('pid', '')})",
                f"Путь: {row.get('exe') or '—'}",
                f"Командная строка: {row.get('cmdline') or '—'}",
                f"Пользователь: {row.get('user') or '—'}",
                f"Окно: {row.get('window') or '—'}",
            ]
            if row.get("suspicious_reasons"):
                lines.append("Признаки: " + ", ".join(row["suspicious_reasons"]))
            if row.get("flags"):
                lines.append("Флаги: " + row["flags"])
            return "\n".join(lines)
        if role == Qt.ItemDataRole.BackgroundRole:
            if row.get("suspicious"):
                return QColor(255, 84, 112, 26)
            if "скрыт" in row.get("flags_list", []):
                return QColor(255, 255, 255, 6)
        if role == Qt.ItemDataRole.ForegroundRole:
            if key in ("name", "flags") and row.get("suspicious"):
                return QColor("#ff5470")
            if key == "flags":
                return QColor("#ffb020" if row.get("flags") else "#8b9bb4")
            if key in ("exe", "cmdline", "user") and not row.get(key):
                return QColor("#8b9bb4")
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rows(self) -> list[dict]:
        return self._rows

    def row(self, source_row: int) -> dict | None:
        if 0 <= source_row < len(self._rows):
            return self._rows[source_row]
        return None

    def key_at(self, column: int) -> str:
        if 0 <= column < len(self._keys):
            return self._keys[column]
        return ""

    def column_width(self, column: int) -> int:
        if 0 <= column < len(self._widths):
            return self._widths[column]
        return 120

class ProcessFilterProxy(QSortFilterProxyModel):
    """Поиск + режимы «все / скрытые / подозрительные»."""

    def __init__(self) -> None:
        super().__init__()
        self._search = ""
        self._mode = "all"
        self._show_system = True
        self.setDynamicSortFilter(True)

    def set_search(self, text: str) -> None:
        self._search = (text or "").strip().lower()
        self.invalidateFilter()

    def set_mode(self, mode: str) -> None:
        self._mode = mode or "all"
        self.invalidateFilter()

    def set_show_system(self, show: bool) -> None:
        self._show_system = bool(show)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: N802
        model: ProcessTableModel = self.sourceModel()
        row = model.row(source_row)
        if row is None:
            return False
        flags = row.get("flags_list", [])
        if not self._show_system and "системный" in flags:
            return False
        if self._mode == "hidden" and "скрыт" not in flags:
            return False
        if self._mode == "suspicious" and not row.get("suspicious"):
            return False
        if self._search:
            haystack = " ".join(
                str(row.get(key, ""))
                for key in ("name", "pid", "exe", "cmdline", "user", "flags", "window")
            ).lower()
            if self._search not in haystack:
                return False
        return True

class ProcessView(QWidget):
    """Таблица процессов с поиском, фильтрами и управлением."""

    status_message = pyqtSignal(str)

    def __init__(self, collector, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.collector = collector
        self._latest_payload: dict = {}
        self._active = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Интерфейс
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: имя, PID, путь, пользователь, окно…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(220)

        self.mode = QComboBox()
        self.mode.addItem("Все процессы", "all")
        self.mode.addItem("Только скрытые", "hidden")
        self.mode.addItem("Только подозрительные", "suspicious")
        self.mode.setMinimumWidth(170)
        current_mode = config.get("processes.mode", "all")
        index = self.mode.findData(current_mode)
        self.mode.setCurrentIndex(max(0, index))

        self.system_check = QCheckBox("Системные")
        self.system_check.setChecked(bool(config.get("processes.show_system", True)))

        self.refresh_button = QPushButton("Обновить")
        self.kill_button = QPushButton("Завершить")
        self.kill_button.setObjectName("DangerButton")
        self.more_button = QPushButton("Ещё")

        toolbar.addWidget(self.search, 2)
        toolbar.addWidget(self.mode)
        toolbar.addWidget(self.system_check)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.kill_button)
        toolbar.addWidget(self.more_button)
        root.addLayout(toolbar)

        self.model = ProcessTableModel()
        self.proxy = ProcessFilterProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsMovable(True)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSortIndicatorShown(True)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        for column in range(self.model.columnCount()):
            self.table.setColumnWidth(column, self.model.column_width(column))
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.stats_label = QLabel("Ожидание данных…")
        self.stats_label.setObjectName("Muted")
        self.sampling_label = QLabel("")
        self.sampling_label.setObjectName("Muted")
        footer.addWidget(self.stats_label, 1)
        footer.addWidget(self.sampling_label)
        root.addLayout(footer)

        self._build_menu()
        self._apply_sort()

        self.search.textChanged.connect(self.proxy.set_search)
        self.mode.currentIndexChanged.connect(self._on_mode_changed)
        self.system_check.toggled.connect(self._on_system_toggled)
        self.refresh_button.clicked.connect(self.refresh_now)
        self.kill_button.clicked.connect(self.kill_selected)
        self.table.doubleClicked.connect(lambda _index: self.show_details())
        self.table.customContextMenuRequested.connect(self._show_context_menu)

    def _build_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Подробная информация", self.show_details)
        menu.addAction("Приостановить процесс", self.suspend_selected)
        menu.addAction("Продолжить процесс", self.resume_selected)
        menu.addAction("Приоритет…", self.change_priority)
        menu.addSeparator()
        menu.addAction("Открыть расположение файла", self.open_folder)
        menu.addAction("Скопировать сведения", self.copy_info)
        menu.addAction("Экспорт в CSV…", self.export_csv_dialog)
        menu.addSeparator()
        menu.addAction("Завершить принудительно", self.kill_selected_force)
        self.more_button.setMenu(menu)
        self.context_menu = menu

    def _show_context_menu(self, position: QPoint) -> None:
        self.context_menu.exec(self.table.viewport().mapToGlobal(position))

    def _apply_sort(self) -> None:
        key = config.get("processes.sort_column", "cpu")
        order = config.get("processes.sort_order", "desc")
        column = -1
        for index in range(self.model.columnCount()):
            if self.model.key_at(index) == key:
                column = index
                break
        if column >= 0:
            self.table.sortByColumn(
                column,
                Qt.SortOrder.DescendingOrder
                if order == "desc"
                else Qt.SortOrder.AscendingOrder,
            )

    def _on_sort_changed(self, column: int, order) -> None:
        key = self.model.key_at(column)
        if key:
            config.set("processes.sort_column", key, save=False)
            config.set(
                "processes.sort_order",
                "desc" if order == Qt.SortOrder.DescendingOrder else "asc",
            )

    def _on_mode_changed(self) -> None:
        mode = self.mode.currentData() or "all"
        self.proxy.set_mode(mode)
        config.set("processes.mode", mode)
        self._update_stats()

    def _on_system_toggled(self, checked: bool) -> None:
        self.proxy.set_show_system(checked)
        config.set("processes.show_system", checked)
        self._update_stats()

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        self._active = active

    def is_active(self) -> bool:
        return self._active

    def refresh_now(self) -> None:
        try:
            payload = self.collector.snapshot()
        except Exception as exc:
            self.status_message.emit(f"Ошибка опроса процессов: {exc}")
            return
        self.set_snapshot(payload)

    def set_snapshot(self, payload: dict) -> None:
        self._latest_payload = payload
        rows = payload.get("rows", [])
        if not self._active and self.model.rowCount() > 0:
            # Пока вкладка скрыта, не тратим время на перерисовку таблицы.
            return
        selected = self.selected_pids()
        top_pid = self._top_pid()
        self.model.set_rows(rows)
        self._restore_selection(selected, top_pid)
        self._update_stats()

    def _update_stats(self) -> None:
        stats = self._latest_payload.get("stats", {})
        total = stats.get("total", 0)
        hidden = stats.get("hidden", 0)
        suspicious = stats.get("suspicious", 0)
        shown = self.proxy.rowCount()
        self.stats_label.setText(
            f"Показано {shown} из {total} · скрытых {hidden} · подозрительных {suspicious}"
        )
        self.sampling_label.setText(f"опрос {stats.get('elapsed_ms', 0):.0f} мс")

    def _top_pid(self):
        index = self.table.indexAt(QPoint(5, 5))
        if not index.isValid():
            return None
        row = self.model.row(self.proxy.mapToSource(index).row())
        return row.get("pid") if row else None

    def selected_rows(self) -> list[dict]:
        rows: list[dict] = []
        selection = self.table.selectionModel()
        if selection is None:
            return rows
        for index in selection.selectedRows(0):
            row = self.model.row(self.proxy.mapToSource(index).row())
            if row:
                rows.append(row)
        return rows

    def selected_pids(self) -> list[int]:
        return [int(row["pid"]) for row in self.selected_rows()]

    def _restore_selection(self, pids: list[int], top_pid) -> None:
        selection = self.table.selectionModel()
        if selection is None:
            return
        selection.clearSelection()
        if pids:
            wanted = set(pids)
            selected = QItemSelection()
            last_column = max(0, self.proxy.columnCount() - 1)
            for proxy_row in range(self.proxy.rowCount()):
                index = self.proxy.index(proxy_row, 0)
                row = self.model.row(self.proxy.mapToSource(index).row())
                if row and row.get("pid") in wanted:
                    selected.select(index, self.proxy.index(proxy_row, last_column))
            if not selected.isEmpty():
                selection.select(
                    selected,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        if top_pid is not None:
            for proxy_row in range(self.proxy.rowCount()):
                index = self.proxy.index(proxy_row, 0)
                row = self.model.row(self.proxy.mapToSource(index).row())
                if row and row.get("pid") == top_pid:
                    self.table.scrollTo(
                        index, QAbstractItemView.ScrollHint.PositionAtTop
                    )
                    break

    def apply_settings(self) -> None:
        self.model.configure_columns()
        for column in range(self.model.columnCount()):
            self.table.setColumnWidth(column, self.model.column_width(column))
        index = self.mode.findData(config.get("processes.mode", "all"))
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0, index))
        self.mode.blockSignals(False)
        self.proxy.set_mode(self.mode.currentData() or "all")
        show_system = bool(config.get("processes.show_system", True))
        self.system_check.blockSignals(True)
        self.system_check.setChecked(show_system)
        self.system_check.blockSignals(False)
        self.proxy.set_show_system(show_system)
        self._apply_sort()

    def focus_pid(self, pid: int) -> None:
        for proxy_row in range(self.proxy.rowCount()):
            index = self.proxy.index(proxy_row, 0)
            row = self.model.row(self.proxy.mapToSource(index).row())
            if row and row.get("pid") == pid:
                self.table.selectRow(proxy_row)
                self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
                break

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------
    def visible_rows(self) -> list[dict]:
        rows: list[dict] = []
        for proxy_row in range(self.proxy.rowCount()):
            index = self.proxy.index(proxy_row, 0)
            row = self.model.row(self.proxy.mapToSource(index).row())
            if row:
                rows.append(row)
        return rows

    def _require_selection(self) -> list[dict]:
        rows = self.selected_rows()
        if not rows:
            self.status_message.emit("Сначала выберите процесс в таблице")
        return rows

    def kill_selected(self) -> None:
        self._kill_rows(self._require_selection(), force=False)

    def kill_selected_force(self) -> None:
        self._kill_rows(self._require_selection(), force=True)

    def _kill_rows(self, rows: list[dict], force: bool) -> None:
        if not rows:
            return
        if config.get("processes.confirm_kill", True):
            names = ", ".join(f"{row['name']} ({row['pid']})" for row in rows[:5])
            if len(rows) > 5:
                names += f" и ещё {len(rows) - 5}"
            answer = QMessageBox.question(
                self,
                "Завершение процессов",
                f"Завершить: {names}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        errors: list[str] = []
        done = 0
        for row in rows:
            pid = int(row["pid"])
            if pid <= 4:
                errors.append(f"{row['name']}: системный процесс защищён")
                continue
            ok, message = self.collector.terminate(pid, force=force)
            if ok:
                done += 1
            else:
                errors.append(f"{row['name']} ({pid}): {message}")

        self.refresh_now()
        if errors:
            QMessageBox.warning(
                self,
                "Результат завершения",
                f"Завершено процессов: {done}\n\n" + "\n".join(errors[:10]),
            )
        else:
            self.status_message.emit(f"Завершено процессов: {done}")

    def suspend_selected(self) -> None:
        self._apply_to_selected("suspend", "приостановлен")

    def resume_selected(self) -> None:
        self._apply_to_selected("resume", "продолжен")

    def _apply_to_selected(self, action: str, action_label: str) -> None:
        rows = self._require_selection()
        if not rows:
            return
        errors = []
        done = 0
        for row in rows:
            method = getattr(self.collector, action)
            ok, message = method(int(row["pid"]))
            if ok:
                done += 1
            else:
                errors.append(f"{row['name']}: {message}")
        self.refresh_now()
        if errors:
            QMessageBox.warning(self, "Результат", "\n".join(errors[:10]))
        else:
            self.status_message.emit(f"Процессов {action_label}: {done}")

    def change_priority(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        from core.process_collector import PRIORITIES

        row = rows[0]
        priority, accepted = QInputDialog.getItem(
            self,
            "Приоритет процесса",
            f"Новый приоритет для {row['name']} ({row['pid']}):",
            list(PRIORITIES.keys()),
            2,
            False,
        )
        if not accepted:
            return
        ok, message = self.collector.set_priority(int(row["pid"]), priority)
        if ok:
            self.status_message.emit(message)
        else:
            QMessageBox.warning(self, "Приоритет", message)

    def open_folder(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        row = rows[0]
        if not row.get("exe"):
            QMessageBox.information(
                self,
                "Расположение файла",
                "Путь к файлу процесса недоступен. "
                "Попробуйте запустить монитор от имени администратора.",
            )
            return
        if not open_in_explorer(row["exe"]):
            QMessageBox.warning(self, "Проводник", "Не удалось открыть папку процесса")

    def copy_info(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        lines = []
        for row in rows:
            lines.append(
                f"{row['name']} | PID {row['pid']} | CPU {row['cpu_text']} | "
                f"RAM {row['mem_text']} | {row['user']} | {row['exe']}"
            )
            if row.get("cmdline"):
                lines.append(f"    {row['cmdline']}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.status_message.emit(f"Скопировано строк: {len(rows)}")

    def show_details(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        from .process_details import ProcessDetailsDialog

        dialog = ProcessDetailsDialog(self.collector, int(rows[0]["pid"]), self)
        dialog.exec()

    def export_csv_dialog(self) -> None:
        rows = self.selected_rows() or self.visible_rows()
        if not rows:
            QMessageBox.information(self, "Экспорт", "Нет данных для экспорта")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Экспорт процессов", "processes.csv", "CSV (*.csv)"
        )
        if not path:
            return
        headers = [title for _key, title, _width, _default in PROCESS_COLUMNS]
        data = [
            [_display(row, key) for key, _title, _width, _default in PROCESS_COLUMNS]
            for row in rows
        ]
        if export_csv(path, headers, data):
            self.status_message.emit(f"Экспортировано строк: {len(rows)} → {path}")
        else:
            QMessageBox.warning(self, "Экспорт", "Не удалось сохранить файл")






