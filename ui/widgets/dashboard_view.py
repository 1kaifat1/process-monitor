"""Панель обзора: системные метрики, графики и топ процессов."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.system_stats import system_info

TOP_LIMIT = 6


class DashboardView(QWidget):
    status_message = pyqtSignal(str)
    focus_process_requested = pyqtSignal(int)

    def __init__(self, process_collector, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.process_collector = process_collector
        self._rows: list[dict] = []
        self._network_stats: dict = {}
        self._active = False
        self._build_ui()

    def _build_ui(self) -> None:
        from .cards import StatCard
        from .chart import HistoryChart

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self.cpu_card = StatCard(tr("Загрузка CPU"), "—", "—", accent="#00f0ff")
        self.ram_card = StatCard(tr("Оперативная память"), "—", "—")
        self.disk_card = StatCard(tr("Системный диск"), "—", "—")
        self.net_card = StatCard(tr("Сеть"), "—", "—")
        self.uptime_card = StatCard(tr("Время работы"), "—", tr("с момента загрузки"))
        self.process_card = StatCard(tr("Процессов"), "—", tr("скрытых: 0"))
        cards_widgets = [
            self.cpu_card,
            self.ram_card,
            self.disk_card,
            self.net_card,
            self.uptime_card,
            self.process_card,
        ]
        for index, card in enumerate(cards_widgets):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        root.addLayout(cards)

        charts = QHBoxLayout()
        charts.setSpacing(10)
        self.cpu_chart = HistoryChart("CPU", "#00f0ff", lambda value: f"{value:.0f}%")
        self.ram_chart = HistoryChart(
            tr("Память"), "#2ee6a8", lambda value: f"{value:.0f}%"
        )
        self.net_chart = HistoryChart(
            tr("Сеть (приём)"),
            "#7c5cff",
            lambda value: f"{value:,.0f} {tr('Б')}{tr('/с')}".replace(",", " "),
        )
        for chart in (self.cpu_chart, self.ram_chart, self.net_chart):
            charts.addWidget(chart, 1)
        root.addLayout(charts)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        top_cpu_panel, self.top_cpu_table = self._top_panel(tr("Топ по CPU"))
        top_mem_panel, self.top_mem_table = self._top_panel(tr("Топ по памяти"))
        bottom.addWidget(top_cpu_panel, 1)
        bottom.addWidget(top_mem_panel, 1)

        system_panel = QFrame()
        system_panel.setObjectName("Card")
        system_layout = QVBoxLayout(system_panel)
        system_layout.setContentsMargins(16, 12, 16, 12)
        system_layout.setSpacing(8)
        title = QLabel(tr("Система"))
        title.setObjectName("SectionTitle")
        system_layout.addWidget(title)
        self.system_form = QFormLayout()
        self.system_form.setSpacing(6)
        self.system_labels: dict[str, QLabel] = {}
        fields = [
            ("hostname", tr("Компьютер")),
            ("os", tr("ОС")),
            ("cpu", tr("Процессор")),
            ("cores", tr("Ядра")),
            ("total_ram", tr("Память")),
            ("boot_time", tr("Время загрузки")),
            ("user", tr("Пользователь")),
        ]
        for key, caption in fields:
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setObjectName("Muted")
            self.system_labels[key] = value
            caption_label = QLabel(caption)
            caption_label.setObjectName("Muted")
            self.system_form.addRow(caption_label, value)
        system_layout.addLayout(self.system_form)
        system_layout.addStretch(1)
        bottom.addWidget(system_panel, 1)
        root.addLayout(bottom, 1)

        info = system_info()
        self.system_labels["hostname"].setText(info["hostname"])
        self.system_labels["os"].setText(info["os"])
        self.system_labels["cpu"].setText(info["cpu"])
        self.system_labels["cores"].setText(
            tr(
                "{physical} физ. / {logical} лог.",
                physical=info["physical_cores"],
                logical=info["logical_cores"],
            )
        )
        self.system_labels["total_ram"].setText(info["total_ram"])
        self.system_labels["boot_time"].setText(info["boot_time"])
        self.system_labels["user"].setText(info["user"])

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.details_button = QPushButton(tr("Подробности процесса"))
        self.kill_button = QPushButton(tr("Завершить процесс"))
        self.kill_button.setObjectName("DangerButton")
        actions.addWidget(self.details_button)
        actions.addWidget(self.kill_button)
        root.addLayout(actions)

        self.details_button.clicked.connect(self.show_details)
        self.kill_button.clicked.connect(self.kill_selected)

    def _top_panel(self, title: str) -> tuple[QFrame, QTableWidget]:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels([tr("Процесс"), tr("PID"), tr("Значение")])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setMinimumHeight(190)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 190)
        table.setColumnWidth(1, 60)
        table.setColumnWidth(2, 100)
        table.doubleClicked.connect(lambda _index: self.show_details())
        layout.addWidget(table)
        return panel, table

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._update_top_tables()

    def set_system_snapshot(self, stats: dict) -> None:
        self.cpu_card.set_value(
            f"{stats.get('cpu', 0):.1f}%",
            tr("своп: {value}", value=f"{stats.get('swap_percent', 0):.1f}%"),
        )
        self.ram_card.set_value(
            f"{stats.get('ram_percent', 0):.1f}%", stats.get("ram_text", "—")
        )
        self.disk_card.set_value(
            f"{stats.get('disk_percent', 0):.1f}%", stats.get("disk_text", "—")
        )
        self.uptime_card.set_value(stats.get("uptime_text", "—"))
        self.cpu_chart.push(float(stats.get("cpu", 0) or 0))
        self.ram_chart.push(float(stats.get("ram_percent", 0) or 0))

    def set_network_snapshot(self, payload: dict) -> None:
        stats = payload.get("stats", {}) or {}
        self._network_stats = stats
        self.net_card.set_value(
            f"↓ {stats.get('down_text', '—')}   ↑ {stats.get('up_text', '—')}",
            tr("соединений: {count}", count=stats.get("count", 0)),
        )
        self.net_chart.push(float(stats.get("down_rate", 0) or 0))

    def set_process_snapshot(self, payload: dict) -> None:
        self._rows = payload.get("rows", [])
        stats = payload.get("stats", {}) or {}
        self.process_card.set_value(
            str(stats.get("total", 0)),
            tr(
                "скрытых: {hidden} · подозрительных: {suspicious}",
                hidden=stats.get("hidden", 0),
                suspicious=stats.get("suspicious", 0),
            ),
        )
        if self._active:
            self._update_top_tables()

    def _update_top_tables(self) -> None:
        rows = [row for row in self._rows if int(row.get("pid", 0)) not in (0, 4)]
        by_cpu = sorted(rows, key=lambda row: row.get("cpu", 0), reverse=True)
        by_mem = sorted(rows, key=lambda row: row.get("mem", 0), reverse=True)
        self._fill_top(self.top_cpu_table, by_cpu, "cpu_text")
        self._fill_top(self.top_mem_table, by_mem, "mem_text")

    def _fill_top(self, table: QTableWidget, rows: list[dict], value_key: str) -> None:
        table.setRowCount(0)
        for row in rows[:TOP_LIMIT]:
            index = table.rowCount()
            table.insertRow(index)
            name_item = QTableWidgetItem(str(row.get("name", "—")))
            name_item.setData(Qt.ItemDataRole.UserRole, int(row.get("pid", 0)))
            table.setItem(index, 0, name_item)
            table.setItem(index, 1, QTableWidgetItem(str(row.get("pid", ""))))
            table.setItem(index, 2, QTableWidgetItem(str(row.get(value_key, "—"))))

    def _selected_pid(self) -> int | None:
        tables = [self.top_cpu_table, self.top_mem_table]
        for table in tables:
            row = table.currentRow()
            if row >= 0 and table.selectedItems():
                item = table.item(row, 0)
                if item is not None:
                    pid = item.data(Qt.ItemDataRole.UserRole)
                    if pid is not None:
                        return int(pid)
        return None

    def _selected_name(self, pid: int) -> str:
        for row in self._rows:
            if int(row.get("pid", 0)) == pid:
                return str(row.get("name", f"PID {pid}"))
        return f"PID {pid}"

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------
    def show_details(self) -> None:
        pid = self._selected_pid()
        if pid is None:
            self.status_message.emit(tr("Выберите процесс в списке топ-процессов"))
            return
        from .process_details import ProcessDetailsDialog

        ProcessDetailsDialog(self.process_collector, pid, self).exec()

    def kill_selected(self) -> None:
        pid = self._selected_pid()
        if pid is None:
            self.status_message.emit(tr("Выберите процесс в списке топ-процессов"))
            return
        if pid <= 4:
            QMessageBox.warning(
                self, tr("Завершение"), tr("Системный процесс защищён")
            )
            return
        answer = QMessageBox.question(
            self,
            tr("Завершение процесса"),
            tr(
                "Завершить {name} (PID {pid})?",
                name=self._selected_name(pid),
                pid=pid,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok, message = self.process_collector.terminate(pid)
        if ok:
            self.status_message.emit(message)
        else:
            QMessageBox.warning(self, tr("Завершение"), message)

    def apply_settings(self, accent: str = "#00f0ff") -> None:
        self.cpu_chart.set_color(accent)
        self.cpu_card.set_accent(accent)


