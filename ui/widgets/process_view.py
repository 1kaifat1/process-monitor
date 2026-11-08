"""Вкладка процессов: модель, фильтрация, кнопка «⚠️ Подозрительные (N)», база знаний и управление."""

from __future__ import annotations

from pathlib import Path

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
    QFrame,
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
from core.i18n import tr
from core.utils import export_csv, format_bytes, open_in_explorer

NUMERIC_KEYS = {"pid", "ppid", "cpu", "mem", "mem_pct", "threads", "handles", "session"}


def _display(row: dict, key: str) -> str:
    if key == "mem":
        return row.get("mem_text") or format_bytes(row.get("mem", 0))
    if key == "cpu":
        return row.get("cpu_text") or f"{row.get('cpu', 0):.1f}%"
    if key == "mem_pct":
        return row.get("mem_pct_text") or f"{row.get('mem_pct', 0):.1f}%"
    if key == "flags":
        return ", ".join(tr(flag) for flag in row.get("flags_list", []))
    if key == "status":
        return tr(str(row.get("status", "")))
    if key == "description":
        safety = row.get("kb_safety", "safe")
        prefix = {
            "critical": "⛔ ",
            "caution": "⚠️ ",
            "bloatware": "🧹 ",
            "safe": "",
        }.get(safety, "")
        base = prefix + str(row.get("description") or "")
        if row.get("suspicious") and row.get("suspicious_reasons"):
            reasons_str = ", ".join(row["suspicious_reasons"])
            return f"🚨 [ПОДОЗРИТЕЛЬНЫЙ: {reasons_str}] · {base}"
        return base
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
                self._headers.append(tr(title))
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
                f"🔹 {row.get('name', '')} (PID {row.get('pid', '')}) — {row.get('kb_category', 'Процесс')}",
                f"📌 Назначение: {row.get('description') or '—'}",
            ]
            if row.get("suspicious_reasons"):
                lines.append(
                    "🚨 Почему помечен как подозрительный: "
                    + ", ".join(str(r) for r in row["suspicious_reasons"])
                )
            if row.get("kb_details") and row.get("kb_details") != row.get("description"):
                lines.append(f"ℹ️ Подробнее: {row.get('kb_details')}")
            if row.get("kb_safety_text"):
                lines.append(row["kb_safety_text"])
            if row.get("kb_services"):
                lines.append("⚙️ Службы внутри: " + ", ".join(row["kb_services"][:8]))
            lines.extend(
                [
                    tr("Путь: {path}", path=row.get("exe") or "—"),
                    tr("Командная строка: {cmd}", cmd=row.get("cmdline") or "—"),
                    tr("Пользователь: {user}", user=row.get("user") or "—"),
                ]
            )
            if row.get("window"):
                lines.append(tr("Окно: {title}", title=row.get("window")))
            return "\n".join(lines)
        if role == Qt.ItemDataRole.BackgroundRole:
            if row.get("suspicious"):
                return QColor(255, 84, 112, 34)
            if row.get("kb_safety") == "bloatware":
                return QColor(255, 176, 32, 16)
            if "скрыт" in row.get("flags_list", []):
                return QColor(255, 255, 255, 6)
        if role == Qt.ItemDataRole.ForegroundRole:
            if key in ("name", "flags", "description") and row.get("suspicious"):
                return QColor("#ff6b86")
            if key == "description":
                safety = row.get("kb_safety", "safe")
                if safety == "critical":
                    return QColor("#ff7b93")
                if safety == "bloatware":
                    return QColor("#ffd166")
                if safety == "caution":
                    return QColor("#b8c7e0")
                return QColor("#b2f2bb")
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
    """Поиск + режимы «все / скрытые / подозрительные / фоновый мусор»."""

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
        # В режиме просмотра подозрительных никогда не скрываем их из-за галочки «Системные»!
        if self._mode == "suspicious":
            if not row.get("suspicious"):
                return False
        else:
            if not self._show_system and "системный" in flags:
                return False
            if self._mode == "hidden" and "скрыт" not in flags:
                return False
            if self._mode == "bloatware" and row.get("kb_safety") != "bloatware":
                return False
        if self._search:
            haystack = " ".join(
                str(row.get(key, ""))
                for key in (
                    "name",
                    "pid",
                    "description",
                    "suspicious_text",
                    "kb_category",
                    "exe",
                    "cmdline",
                    "user",
                    "flags",
                    "window",
                )
            )
            haystack += " " + " ".join(tr(flag) for flag in flags)
            if self._search not in haystack.lower():
                return False
        return True


class ProcessView(QWidget):
    """Таблица процессов с кнопкой «⚠️ Подозрительные (N)», базой знаний, открытием папки и удалением."""

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
        toolbar.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            tr("Поиск: имя, назначение, PID, путь…")
        )
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(140)

        self.mode = QComboBox()
        self.mode.addItem(tr("Все процессы"), "all")
        self.mode.addItem(tr("Подозрительные"), "suspicious")
        self.mode.addItem(tr("Телеметрия / фон"), "bloatware")
        self.mode.addItem(tr("Только скрытые"), "hidden")
        self.mode.setMinimumWidth(145)
        current_mode = config.get("processes.mode", "all")
        index = self.mode.findData(current_mode)
        self.mode.setCurrentIndex(max(0, index))

        # Отдельная заметная кнопка-переключатель для мгновенного показа подозрительных процессов
        self.suspicious_btn = QPushButton(tr("⚠️ Угрозы (0)"))
        self.suspicious_btn.setCheckable(True)
        self.suspicious_btn.setMinimumWidth(120)
        self.suspicious_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.suspicious_btn.setToolTip(
            tr("Нажмите, чтобы отфильтровать таблицу и показать только подозрительные процессы и причины их пометки")
        )

        self.system_check = QCheckBox(tr("Системные"))
        self.system_check.setChecked(bool(config.get("processes.show_system", True)))

        self.info_button = QPushButton(tr("Что это?"))
        self.info_button.setToolTip(tr("Показать подробное описание процесса и безопасность завершения"))
        self.folder_button = QPushButton(tr("Папка"))
        self.folder_button.setToolTip(tr("Открыть расположение EXE-файла процесса в Проводнике"))
        self.refresh_button = QPushButton(tr("Обновить"))
        self.refresh_button.hide()
        self.kill_button = QPushButton(tr("Завершить"))
        self.kill_button.setObjectName("DangerButton")
        self.more_button = QPushButton(tr("Ещё"))

        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.suspicious_btn)
        toolbar.addWidget(self.mode)
        toolbar.addWidget(self.system_check)
        toolbar.addSpacing(4)
        toolbar.addWidget(self.info_button)
        toolbar.addWidget(self.folder_button)
        toolbar.addWidget(self.kill_button)
        toolbar.addWidget(self.more_button)
        root.addLayout(toolbar)

        # Информационная плашка, которая появляется при включении фильтра «Подозрительные»
        self.suspicious_banner = QFrame()
        self.suspicious_banner.setObjectName("Card")
        self.suspicious_banner.setVisible(False)
        banner_layout = QHBoxLayout(self.suspicious_banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(10)
        self.suspicious_banner_label = QLabel("")
        self.suspicious_banner_label.setWordWrap(True)
        self.suspicious_banner_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.reset_filter_btn = QPushButton(tr("Показать все процессы"))
        banner_layout.addWidget(self.suspicious_banner_label, 1)
        banner_layout.addWidget(self.reset_filter_btn)
        root.addWidget(self.suspicious_banner)

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
        self.stats_label = QLabel(tr("Ожидание данных…"))
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
        self.suspicious_btn.clicked.connect(self._on_suspicious_btn_clicked)
        self.reset_filter_btn.clicked.connect(self.show_all_processes)
        self.system_check.toggled.connect(self._on_system_toggled)
        self.info_button.clicked.connect(self.show_details)
        self.folder_button.clicked.connect(self.open_folder)
        self.refresh_button.clicked.connect(self.refresh_now)
        self.kill_button.clicked.connect(self.kill_selected)
        self.table.doubleClicked.connect(lambda _index: self.show_details())
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        self.proxy.set_mode(current_mode)
        self.suspicious_btn.setChecked(current_mode == "suspicious")

    def _build_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(tr("Что это за процесс? (Подробности)"), self.show_details)
        menu.addAction(tr("Открыть расположение файла в Проводнике"), self.open_folder)
        menu.addSeparator()
        menu.addAction(tr("Приостановить процесс"), self.suspend_selected)
        menu.addAction(tr("Продолжить процесс"), self.resume_selected)
        menu.addAction(tr("Приоритет…"), self.change_priority)
        menu.addSeparator()
        menu.addAction(tr("Скопировать сведения"), self.copy_info)
        menu.addAction(tr("Экспорт в CSV…"), self.export_csv_dialog)
        menu.addSeparator()
        menu.addAction(tr("Завершить принудительно"), self.kill_selected_force)
        menu.addAction(
            tr("🗑️ Завершить и удалить EXE-файл процесса…"),
            self.kill_and_delete_file,
        )
        menu.addAction(
            tr("🧨 Завершить и удалить всю папку программы…"),
            self.kill_and_delete_folder,
        )
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
        self.suspicious_btn.blockSignals(True)
        self.suspicious_btn.setChecked(mode == "suspicious")
        self.suspicious_btn.blockSignals(False)
        config.set("processes.mode", mode)
        self._update_suspicious_banner()
        self._update_stats()

    def _on_suspicious_btn_clicked(self, checked: bool) -> None:
        if checked:
            self.show_suspicious_only()
        else:
            self.show_all_processes()

    def show_suspicious_only(self) -> None:
        """Переключает фильтр таблицы в режим показа только подозрительных процессов."""
        self.search.clear()
        idx = self.mode.findData("suspicious")
        if idx >= 0:
            self.mode.setCurrentIndex(idx)
        self.suspicious_btn.blockSignals(True)
        self.suspicious_btn.setChecked(True)
        self.suspicious_btn.blockSignals(False)
        self._update_suspicious_banner()
        self._update_stats()

    def show_all_processes(self) -> None:
        idx = self.mode.findData("all")
        if idx >= 0:
            self.mode.setCurrentIndex(idx)
        self.suspicious_btn.blockSignals(True)
        self.suspicious_btn.setChecked(False)
        self.suspicious_btn.blockSignals(False)
        self._update_suspicious_banner()
        self._update_stats()

    def _update_suspicious_banner(self) -> None:
        mode = self.mode.currentData() or "all"
        if mode != "suspicious":
            self.suspicious_banner.setVisible(False)
            return
        rows = [r for r in self.model.rows() if r.get("suspicious")]
        if not rows:
            self.suspicious_banner_label.setText(
                tr("✅ Подозрительных процессов сейчас не обнаружено.")
            )
        else:
            details_lines = [
                tr("🚨 Найдено подозрительных процессов: {count}. Причины пометки:", count=len(rows))
            ]
            for r in rows[:8]:
                reasons = ", ".join(r.get("suspicious_reasons") or ["неизвестно"])
                path_info = r.get("exe") or "путь скрыт системой"
                details_lines.append(
                    f"• {r.get('name')} (PID {r.get('pid')}) — {reasons}  [{path_info}]"
                )
            self.suspicious_banner_label.setText("\n".join(details_lines))
        self.suspicious_banner.setVisible(True)

    def _on_system_toggled(self, checked: bool) -> None:
        self.proxy.set_show_system(checked)
        config.set("processes.show_system", checked)
        self._update_stats()

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        was_active = self._active
        self._active = active
        if active and not was_active and self._latest_payload:
            self.set_snapshot(self._latest_payload)

    def is_active(self) -> bool:
        return self._active

    def refresh_now(self) -> None:
        try:
            payload = self.collector.snapshot()
        except Exception as exc:
            self.status_message.emit(
                tr("Ошибка опроса процессов: {error}", error=exc)
            )
            return
        self.set_snapshot(payload)

    def set_snapshot(self, payload: dict) -> None:
        self._latest_payload = payload
        rows = payload.get("rows", [])
        stats = payload.get("stats", {})
        susp_count = int(stats.get("suspicious", 0) or 0)
        self.suspicious_btn.setText(
            tr("⚠️ Угрозы ({count})", count=susp_count)
        )
        if susp_count > 0:
            self.suspicious_btn.setStyleSheet(
                "QPushButton { background: rgba(255, 84, 112, 0.20); "
                "border: 1px solid #ff5470; color: #ff8fa3; font-weight: 600; }"
                "QPushButton:checked { background: #ff5470; color: #0b0f17; }"
            )
        else:
            self.suspicious_btn.setStyleSheet("")

        if not self._active and self.model.rowCount() > 0:
            return
        selected = self.selected_pids()
        top_pid = self._top_pid()
        self.model.set_rows(rows)
        self._restore_selection(selected, top_pid)
        self._update_suspicious_banner()
        self._update_stats()

    def _update_stats(self) -> None:
        stats = self._latest_payload.get("stats", {})
        total = stats.get("total", 0)
        hidden = stats.get("hidden", 0)
        suspicious = stats.get("suspicious", 0)
        shown = self.proxy.rowCount()
        self.stats_label.setText(
            tr(
                "Показано {shown} из {total} · скрытых {hidden} · подозрительных {suspicious}",
                shown=shown,
                total=total,
                hidden=hidden,
                suspicious=suspicious,
            )
        )
        self.sampling_label.setText(
            tr("опрос {ms:.0f} мс", ms=stats.get("elapsed_ms", 0))
        )

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
        mode = self.mode.currentData() or "all"
        self.proxy.set_mode(mode)
        self.suspicious_btn.blockSignals(True)
        self.suspicious_btn.setChecked(mode == "suspicious")
        self.suspicious_btn.blockSignals(False)
        show_system = bool(config.get("processes.show_system", True))
        self.system_check.blockSignals(True)
        self.system_check.setChecked(show_system)
        self.system_check.blockSignals(False)
        self.proxy.set_show_system(show_system)
        self._update_suspicious_banner()
        self._apply_sort()

    def focus_pid(self, pid: int) -> None:
        # Если процесс был скрыт фильтром — переключаемся на показ всех процессов
        for proxy_row in range(self.proxy.rowCount()):
            index = self.proxy.index(proxy_row, 0)
            row = self.model.row(self.proxy.mapToSource(index).row())
            if row and row.get("pid") == pid:
                self.table.selectRow(proxy_row)
                self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
                return
        self.show_all_processes()
        self.system_check.setChecked(True)
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
            self.status_message.emit(tr("Сначала выберите процесс в таблице"))
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
                names += " " + tr("и ещё {count}", count=len(rows) - 5)
            critical_rows = [r for r in rows if r.get("kb_safety") == "critical"]
            warn_extra = ""
            if critical_rows:
                warn_extra = (
                    "\n\n⛔ ВНИМАНИЕ: Среди выбранных есть критический системный процесс Windows! "
                    "Его завершение может привести к синему экрану (BSOD)."
                )
            answer = QMessageBox.question(
                self,
                tr("Завершение процессов"),
                tr("Завершить: {names}?", names=names) + warn_extra,
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
                errors.append(
                    f"{row['name']}: {tr('системный процесс защищён')}"
                )
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
                tr("Результат завершения"),
                tr(
                    "Завершено процессов: {count}\n\n{errors}",
                    count=done,
                    errors="\n".join(errors[:10]),
                ),
            )
        else:
            self.status_message.emit(
                tr("Завершено процессов: {count}", count=done)
            )

    def kill_and_delete_file(self) -> None:
        self._kill_and_delete(delete_folder=False)

    def kill_and_delete_folder(self) -> None:
        self._kill_and_delete(delete_folder=True)

    def _kill_and_delete(self, *, delete_folder: bool) -> None:
        rows = self._require_selection()
        if not rows:
            return
        row = rows[0]
        pid = int(row["pid"])
        exe = row.get("exe") or ""
        if not exe:
            QMessageBox.warning(
                self,
                tr("Удаление процесса"),
                tr("У выбранного процесса не определён путь к файлу EXE."),
            )
            return

        target_str = str(Path(exe).parent) if delete_folder else exe
        mode_title = (
            tr("Завершить процесс и удалить ПАПКУ программы")
            if delete_folder
            else tr("Завершить процесс и удалить EXE-файл")
        )
        msg = (
            f"Вы собираетесь принудительно завершить процесс:\n"
            f"• {row.get('name')} (PID {pid})\n"
            f"• Назначение: {row.get('description')}\n\n"
            f"И БЕЗВОЗВРАТНО удалить с диска:\n"
            f"👉 {target_str}\n\n"
            f"Продолжить?"
        )
        answer = QMessageBox.warning(
            self,
            mode_title,
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        ok, result_msg = self.collector.terminate_and_delete(
            pid, delete_folder=delete_folder, shred_passes=0
        )
        self.refresh_now()
        if ok:
            self.status_message.emit(result_msg)
            QMessageBox.information(self, mode_title, result_msg)
        else:
            QMessageBox.warning(self, mode_title, result_msg)

    def suspend_selected(self) -> None:
        self._apply_to_selected("suspend", tr("приостановлено"))

    def resume_selected(self) -> None:
        self._apply_to_selected("resume", tr("продолжено"))

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
            QMessageBox.warning(
                self, tr("Результат"), "\n".join(errors[:10])
            )
        else:
            self.status_message.emit(
                tr("Процессов {action}: {count}", action=action_label, count=done)
            )

    def change_priority(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        from core.process_collector import PRIORITIES

        row = rows[0]
        priority_labels = [tr(name) for name in PRIORITIES]
        priority, accepted = QInputDialog.getItem(
            self,
            tr("Приоритет процесса"),
            tr(
                "Новый приоритет для {name} ({pid}):",
                name=row["name"],
                pid=row["pid"],
            ),
            priority_labels,
            2,
            False,
        )
        if not accepted:
            return
        priority_name = list(PRIORITIES.keys())[priority_labels.index(priority)]
        ok, message = self.collector.set_priority(
            int(row["pid"]), priority_name
        )
        if ok:
            self.status_message.emit(message)
        else:
            QMessageBox.warning(self, tr("Приоритет"), message)

    def open_folder(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        row = rows[0]
        if not row.get("exe"):
            QMessageBox.information(
                self,
                tr("Расположение файла"),
                tr(
                    "Путь к файлу процесса недоступен. "
                    "Попробуйте запустить монитор от имени администратора."
                ),
            )
            return
        if not open_in_explorer(row["exe"]):
            QMessageBox.warning(
                self, tr("Проводник"), tr("Не удалось открыть папку процесса")
            )

    def copy_info(self) -> None:
        rows = self._require_selection()
        if not rows:
            return
        lines = []
        for row in rows:
            lines.append(
                f"{row['name']} | PID {row['pid']} | {row.get('description', '')} | "
                f"CPU {row['cpu_text']} | RAM {row['mem_text']} | {row['user']} | {row['exe']}"
            )
            if row.get("cmdline"):
                lines.append(f"    {row['cmdline']}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.status_message.emit(tr("Скопировано строк: {count}", count=len(rows)))

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
            QMessageBox.information(
                self, tr("Экспорт"), tr("Нет данных для экспорта")
            )
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("Экспорт процессов"), "processes.csv", "CSV (*.csv)"
        )
        if not path:
            return
        headers = [tr(title) for _key, title, _width, _default in PROCESS_COLUMNS]
        data = [
            [_display(row, key) for key, _title, _width, _default in PROCESS_COLUMNS]
            for row in rows
        ]
        if export_csv(path, headers, data):
            self.status_message.emit(
                tr(
                    "Экспортировано строк: {count} → {path}",
                    count=len(rows),
                    path=path,
                )
            )
        else:
            QMessageBox.warning(
                self, tr("Экспорт"), tr("Не удалось сохранить файл")
            )
