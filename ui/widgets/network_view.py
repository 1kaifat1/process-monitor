"""Вкладка сети: скорость, интерфейсы и соединения процессов."""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import config
from core.i18n import tr
from core.utils import export_csv

HEADERS = [
    ("process", "Процесс"),
    ("pid", "PID"),
    ("kind", "Тип"),
    ("local", "Локальный адрес"),
    ("remote", "Удалённый адрес"),
    ("status", "Состояние"),
    ("family", "Семейство"),
]


class ConnectionsModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        key = HEADERS[index.column()][0]
        if role == Qt.ItemDataRole.DisplayRole:
            value = row.get(key, "")
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            status = row.get("status")
            if status == "ESTABLISHED":
                return QColor("#2ee6a8")
            if status == "LISTEN":
                return QColor("#8b9bb4")
            if status in ("CLOSE_WAIT", "TIME_WAIT"):
                return QColor("#ffb020")
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"{row.get('process')} (PID {row.get('pid')})\n"
                f"{row.get('local')} → {row.get('remote')}\n{row.get('status')}"
            )
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(HEADERS):
                return tr(HEADERS[section][1])
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rows(self) -> list[dict]:
        return self._rows

    def row(self, index: int) -> dict | None:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None


class NetworkView(QWidget):
    status_message = pyqtSignal(str)

    def __init__(
        self, collector, process_collector=None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.collector = collector
        self.process_collector = process_collector
        self._all_rows: list[dict] = []
        self._latest_payload: dict = {}
        self._latest_stats: dict = {}
        self._active = False
        self._build_ui()

    def _build_ui(self) -> None:
        from .cards import StatCard
        from .chart import HistoryChart

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.down_card = StatCard(tr("Приём"), "—", tr("ожидание"), accent="#00f0ff")
        self.up_card = StatCard(tr("Отдача"), "—", tr("ожидание"), accent="#7c5cff")
        self.connections_card = StatCard(
            tr("Соединений"), "—", tr("из них установлено: 0")
        )
        self.processes_card = StatCard(
            tr("Процессов в сети"), "—", tr("слушающих портов: 0")
        )
        for card in (self.down_card, self.up_card, self.connections_card, self.processes_card):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        charts = QHBoxLayout()
        charts.setSpacing(10)
        self.down_chart = HistoryChart(
            tr("Входящий трафик"),
            "#00f0ff",
            lambda value: f"{value:,.0f} {tr('Б')}{tr('/с')}".replace(",", " "),
        )
        self.up_chart = HistoryChart(
            tr("Исходящий трафик"),
            "#7c5cff",
            lambda value: f"{value:,.0f} {tr('Б')}{tr('/с')}".replace(",", " "),
        )
        charts.addWidget(self.down_chart, 1)
        charts.addWidget(self.up_chart, 1)
        root.addLayout(charts)

        interfaces_title = QLabel(tr("Сетевые интерфейсы"))
        interfaces_title.setObjectName("SectionTitle")
        root.addWidget(interfaces_title)

        self.interfaces_table = QTableWidget(0, 6)
        self.interfaces_table.setHorizontalHeaderLabels(
            [
                tr("Интерфейс"),
                tr("IP-адрес"),
                tr("Статус"),
                tr("Скорость"),
                tr("Приём"),
                tr("Отдача"),
            ]
        )
        self.interfaces_table.verticalHeader().setVisible(False)
        self.interfaces_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.interfaces_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.interfaces_table.setShowGrid(False)
        self.interfaces_table.setMinimumHeight(84)
        self.interfaces_table.setMaximumHeight(150)
        header = self.interfaces_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.interfaces_table)

        connections_title = QLabel(tr("Активные соединения"))
        connections_title.setObjectName("SectionTitle")
        root.addWidget(connections_title)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            tr("Поиск: процесс, PID, адрес, порт…")
        )
        self.search.setClearButtonEnabled(True)
        self.established_check = QCheckBox(tr("Только установленные"))
        self.established_check.setChecked(
            bool(config.get("network.only_established", False))
        )
        self.loopback_check = QCheckBox(tr("Скрыть локальные"))
        self.loopback_check.setChecked(bool(config.get("network.hide_loopback", True)))
        self.refresh_button = QPushButton(tr("Обновить"))
        self.kill_button = QPushButton(tr("Завершить процесс"))
        self.kill_button.setObjectName("DangerButton")
        self.copy_button = QPushButton(tr("Копировать"))
        self.export_button = QPushButton("CSV…")

        toolbar.addWidget(self.search, 2)
        toolbar.addWidget(self.established_check)
        toolbar.addWidget(self.loopback_check)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.kill_button)
        root.addLayout(toolbar)

        self.model = ConnectionsModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        widths = [170, 70, 60, 200, 210, 120, 90]
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.stats_label = QLabel(tr("Ожидание данных…"))
        self.stats_label.setObjectName("Muted")
        self.sampling_label = QLabel("")
        self.sampling_label.setObjectName("Muted")
        footer.addWidget(self.stats_label, 1)
        footer.addWidget(self.sampling_label)
        root.addLayout(footer)

        self.search.textChanged.connect(self._apply_filter)
        self.established_check.toggled.connect(self._on_filter_toggled)
        self.loopback_check.toggled.connect(self._on_filter_toggled)
        self.refresh_button.clicked.connect(self.refresh_now)
        self.kill_button.clicked.connect(self.kill_process)
        self.copy_button.clicked.connect(self.copy_endpoint)
        self.export_button.clicked.connect(self.export_csv_dialog)

        self._apply_filter()

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._apply_filter()

    def refresh_now(self) -> None:
        try:
            payload = self.collector.snapshot()
        except Exception as exc:
            self.status_message.emit(tr("Ошибка опроса сети: {error}", error=exc))
            return
        self.set_snapshot(payload)

    def set_snapshot(self, payload: dict) -> None:
        self._latest_payload = payload
        stats = payload.get("stats", {})
        self.down_card.set_value(
            stats.get("down_text", "—"),
            tr("всего принято {value}", value=stats.get("total_recv", "—")),
        )
        self.up_card.set_value(
            stats.get("up_text", "—"),
            tr("всего отправлено {value}", value=stats.get("total_sent", "—")),
        )
        self.connections_card.set_value(
            str(stats.get("count", 0)),
            tr("установлено: {count}", count=stats.get("established", 0)),
        )
        self.processes_card.set_value(
            str(stats.get("processes", 0)),
            tr("слушающих портов: {count}", count=stats.get("listening", 0)),
        )
        self.down_chart.push(float(stats.get("down_rate", 0) or 0))
        self.up_chart.push(float(stats.get("up_rate", 0) or 0))
        self._update_interfaces(payload.get("interfaces", []))

        self._all_rows = payload.get("connections", [])
        if self._active or self.model.rowCount() == 0:
            self._apply_filter()
        self.sampling_label.setText(
            tr("обновлено: {count} соединений", count=len(self._all_rows))
        )

    def _update_interfaces(self, interfaces: list[dict]) -> None:
        self.interfaces_table.setRowCount(len(interfaces))
        for row_index, item in enumerate(interfaces):
            values = [
                item.get("name", "—"),
                item.get("ip", "—"),
                tr("Подключён") if item.get("up") else tr("Отключён"),
                item.get("speed", "—"),
                item.get("down", "—"),
                item.get("up_rate", "—"),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 2:
                    cell.setForeground(
                        QColor("#2ee6a8") if item.get("up") else QColor("#8b9bb4")
                    )
                self.interfaces_table.setItem(row_index, column, cell)

    def _on_filter_toggled(self) -> None:
        config.set("network.only_established", self.established_check.isChecked())
        config.set("network.hide_loopback", self.loopback_check.isChecked())
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search.text().strip().lower()
        only_established = self.established_check.isChecked()
        hide_loopback = self.loopback_check.isChecked()
        rows: list[dict] = []
        for row in self._all_rows:
            if only_established and row.get("status") != "ESTABLISHED":
                continue
            if hide_loopback and row.get("loopback"):
                continue
            if query:
                haystack = " ".join(
                    str(row.get(key, ""))
                    for key in ("process", "pid", "local", "remote", "status")
                ).lower()
                if query not in haystack:
                    continue
            rows.append(row)
        self.model.set_rows(rows)
        error = (self._latest_payload.get("stats", {}) or {}).get("error", "")
        text = tr(
            "Показано {shown} из {total} соединений",
            shown=len(rows),
            total=len(self._all_rows),
        )
        if error:
            text += f" · {error}"
        self.stats_label.setText(text)

    def selected_rows(self) -> list[dict]:
        rows: list[dict] = []
        selection = self.table.selectionModel()
        if selection is None:
            return rows
        for index in selection.selectedRows(0):
            row = self.model.row(index.row())
            if row:
                rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------
    def kill_process(self) -> None:
        rows = self.selected_rows()
        if not rows:
            self.status_message.emit(tr("Выберите соединение в таблице"))
            return
        pids = sorted({int(row["pid"]) for row in rows if row.get("pid")})
        if not pids:
            self.status_message.emit(tr("У выбранных соединений нет PID"))
            return
        names = ", ".join(f"{row['process']} ({row['pid']})" for row in rows[:5])
        answer = QMessageBox.question(
            self,
            tr("Завершение процесса"),
            tr("Завершить процесс(ы): {names}?", names=names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for pid in pids:
            if self.process_collector is not None:
                ok, message = self.process_collector.terminate(pid)
            else:
                import psutil

                try:
                    psutil.Process(pid).terminate()
                    ok, message = True, tr("Завершён")
                except Exception as exc:
                    ok, message = False, str(exc)
            if not ok:
                errors.append(f"PID {pid}: {message}")
        self.refresh_now()
        if errors:
            QMessageBox.warning(
                self, tr("Результат"), "\n".join(errors[:10])
            )

    def copy_endpoint(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        text = "\n".join(
            f"{row['process']} ({row['pid']}) {row['local']} → {row['remote']} [{row['status']}]"
            for row in rows
        )
        QGuiApplication.clipboard().setText(text)
        self.status_message.emit(tr("Скопировано строк: {count}", count=len(rows)))

    def export_csv_dialog(self) -> None:
        rows = self.selected_rows() or self.model.rows()
        if not rows:
            QMessageBox.information(
                self, tr("Экспорт"), tr("Нет соединений для экспорта")
            )
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("Экспорт соединений"), "connections.csv", "CSV (*.csv)"
        )
        if not path:
            return
        headers = [tr(title) for _key, title in HEADERS]
        data = [[str(row.get(key, "")) for key, _title in HEADERS] for row in rows]
        if export_csv(path, headers, data):
            self.status_message.emit(
                tr("Экспортировано соединений: {count}", count=len(rows))
            )
        else:
            QMessageBox.warning(
                self, tr("Экспорт"), tr("Не удалось сохранить файл")
            )

    def apply_settings(self, accent: str = "#00f0ff") -> None:
        self.down_chart.set_color(accent)
        self.down_card.set_accent(accent)
        self.established_check.blockSignals(True)
        self.established_check.setChecked(
            bool(config.get("network.only_established", False))
        )
        self.established_check.blockSignals(False)
        self.loopback_check.blockSignals(True)
        self.loopback_check.setChecked(bool(config.get("network.hide_loopback", True)))
        self.loopback_check.blockSignals(False)
        self._apply_filter()



