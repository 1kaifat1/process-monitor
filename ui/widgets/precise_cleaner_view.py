"""Вкладка «Точечная очистка и Разблокировка»: профили в 1 клик, поиск по фильтрам и снятие блокировок."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.cleaner_engine import (
     delete_path_forced,
    is_safe_delete_path,
    scan_custom_filter,
    scan_precise_profile,
)
from core.i18n import tr
from core.utils import format_bytes, format_timestamp, open_in_explorer


class _PreciseScanWorker(QThread):
    progress = pyqtSignal(str)
    finished_scan = pyqtSignal(list)

    def __init__(
        self,
        *,
        mode: str,
        profile_id: str = "",
        custom_root: str = "",
        extensions: set[str] | None = None,
        min_size_bytes: int = 0,
        min_age_days: float = 0.0,
        name_query: str = "",
    ) -> None:
        super().__init__()
        self.mode = mode
        self.profile_id = profile_id
        self.custom_root = custom_root
        self.extensions = extensions
        self.min_size_bytes = min_size_bytes
        self.min_age_days = min_age_days
        self.name_query = name_query
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            if self.mode == "profile":
                items = scan_precise_profile(
                    self.profile_id,
                    custom_root=self.custom_root or None,
                    cancel_event=self.cancel_event,
                    progress_cb=lambda msg: self.progress.emit(msg),
                )
            else:
                items = scan_custom_filter(
                    root_paths=[self.custom_root] if self.custom_root else [str(Path.home())],
                    extensions=self.extensions,
                    min_size_bytes=self.min_size_bytes,
                    min_age_days=self.min_age_days,
                    name_query=self.name_query,
                    max_results=1200,
                    cancel_event=self.cancel_event,
                    progress_cb=lambda msg: self.progress.emit(msg),
                )
        except Exception:
            items = []
        self.finished_scan.emit(items)


class _PreciseDeleteWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished_delete = pyqtSignal(dict)

    def __init__(
        self,
        targets: list[dict[str, Any]],
        *,
        unlock_if_locked: bool = True,
        shred_passes: int = 0,
    ) -> None:
        super().__init__()
        self.targets = targets
        self.unlock_if_locked = unlock_if_locked
        self.shred_passes = shred_passes

    def run(self) -> None:
        freed_total = 0
        deleted_count = 0
        failed_count = 0
        unlocked_pids: list[int] = []
        last_error = ""
        total = max(1, len(self.targets))

        for idx, item in enumerate(self.targets, 1):
            p = item.get("path", "")
            self.progress.emit(Path(p).name or p, idx, total)
            res = delete_path_forced(
                p,
                keep_root_dir=bool(item.get("keep_root_dir", False)),
                shred_passes=self.shred_passes,
                unlock_if_locked=self.unlock_if_locked,
            )
            if res.get("ok"):
                freed_total += int(res.get("freed_bytes", 0))
                deleted_count += 1
            else:
                failed_count += 1
                last_error = str(res.get("error", ""))
            for pid in res.get("unlocked_pids", []):
                if pid not in unlocked_pids:
                    unlocked_pids.append(pid)

        self.finished_delete.emit(
            {
                "freed_bytes": freed_total,
                "deleted_count": deleted_count,
                "failed_count": failed_count,
                "unlocked_pids": unlocked_pids,
                "last_error": last_error,
            }
        )


class PreciseCleanerView(QWidget):
    """Точечная очистка: быстрые профили, конструктор фильтров и снятие блокировок с файлов/папок."""

    status_message = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._scan_worker: _PreciseScanWorker | None = None
        self._del_worker: _PreciseDeleteWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # 1. Быстрые профили точечной очистки (в 1 клик)
        profiles_card = QFrame()
        profiles_card.setObjectName("Card")
        p_layout = QVBoxLayout(profiles_card)
        p_layout.setContentsMargins(14, 12, 14, 12)
        p_layout.setSpacing(8)

        top_row = QHBoxLayout()
        p_title = QLabel(tr("🎯 Быстрые профили точечной очистки (в 1 клик)"))
        p_title.setObjectName("SectionTitle")
        top_row.addWidget(p_title)
        top_row.addStretch(1)

        # Кнопка прямой разблокировки и удаления любого заблокированного файла/папки
        self.unlocker_btn = QPushButton(tr("🔓 Разблокировать занятый файл / папку…"))
        self.unlocker_btn.setObjectName("PrimaryButton")
        self.unlocker_btn.setToolTip(
            tr("Выбрать любой файл или папку, посмотреть какие процессы её держат, завершить их и удалить")
        )
        top_row.addWidget(self.unlocker_btn)
        p_layout.addLayout(top_row)

        btn_grid = QGridLayout()
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(6)
        self.btn_downloads = QPushButton(tr("📥 Старые и крупные Загрузки"))
        self.btn_app_caches = QPushButton(tr("💬 Кэши Telegram / Discord / Steam / Epic"))
        self.btn_logs = QPushButton(tr("📄 Логи, дампы и временные (.tmp / .bak / .old)"))
        self.btn_dev_junk = QPushButton(tr("🛠️ Dev-мусор (node_modules, __pycache__, target)"))

        btn_grid.addWidget(self.btn_downloads, 0, 0)
        btn_grid.addWidget(self.btn_app_caches, 0, 1)
        btn_grid.addWidget(self.btn_logs, 1, 0)
        btn_grid.addWidget(self.btn_dev_junk, 1, 1)
        p_layout.addLayout(btn_grid)
        root.addWidget(profiles_card)

        # 2. Конструктор пользовательских фильтров
        filter_card = QFrame()
        filter_card.setObjectName("Card")
        f_grid = QGridLayout(filter_card)
        f_grid.setContentsMargins(14, 10, 14, 10)
        f_grid.setHorizontalSpacing(10)
        f_grid.setVerticalSpacing(8)

        f_grid.addWidget(QLabel(tr("Папка:")), 0, 0)
        self.path_edit = QLineEdit(str(Path.home()))
        self.path_edit.setPlaceholderText(tr("Путь к папке или диску для точечного поиска…"))
        f_grid.addWidget(self.path_edit, 0, 1, 1, 3)

        self.browse_btn = QPushButton(tr("Обзор…"))
        f_grid.addWidget(self.browse_btn, 0, 4)

        f_grid.addWidget(QLabel(tr("Расширения:")), 1, 0)
        self.ext_edit = QLineEdit(".tmp, .log, .bak, .dmp, .old, .chk")
        self.ext_edit.setPlaceholderText(tr("Например: .tmp, .log, .iso, .mp4 (пусто — любые файлы)"))
        f_grid.addWidget(self.ext_edit, 1, 1)

        f_grid.addWidget(QLabel(tr("Имя содержит:")), 1, 2)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("Часть имени файла (необязательно)…"))
        f_grid.addWidget(self.name_edit, 1, 3, 1, 2)

        f_grid.addWidget(QLabel(tr("Мин. размер:")), 2, 0)
        size_box = QHBoxLayout()
        self.min_size_spin = QDoubleSpinBox()
        self.min_size_spin.setRange(0.0, 100000.0)
        self.min_size_spin.setDecimals(1)
        self.min_size_spin.setValue(0.1)
        self.size_unit_combo = QComboBox()
        self.size_unit_combo.addItem("МБ", 1024 * 1024)
        self.size_unit_combo.addItem("КБ", 1024)
        self.size_unit_combo.addItem("ГБ", 1024 * 1024 * 1024)
        size_box.addWidget(self.min_size_spin)
        size_box.addWidget(self.size_unit_combo)
        f_grid.addLayout(size_box, 2, 1)

        f_grid.addWidget(QLabel(tr("Старше (дней):")), 2, 2)
        self.age_spin = QSpinBox()
        self.age_spin.setRange(0, 3650)
        self.age_spin.setValue(0)
        self.age_spin.setSuffix(tr(" дн."))
        f_grid.addWidget(self.age_spin, 2, 3)

        search_btns = QHBoxLayout()
        self.filter_search_btn = QPushButton(tr("🔎 Найти по фильтру"))
        self.stop_btn = QPushButton(tr("⏹ Стоп"))
        self.stop_btn.setEnabled(False)
        search_btns.addWidget(self.filter_search_btn)
        search_btns.addWidget(self.stop_btn)
        f_grid.addLayout(search_btns, 2, 4)

        root.addWidget(filter_card)

        # 3. Панель действий над результатами
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(6)
        self.sel_all_btn = QPushButton(tr("Все"))
        self.sel_all_btn.setToolTip(tr("Выбрать все строки в таблице"))
        self.sel_none_btn = QPushButton(tr("Снять"))
        self.sel_none_btn.setToolTip(tr("Снять галочки со всех строк"))
        self.open_loc_btn = QPushButton(tr("📂 Папка"))
        self.open_loc_btn.setToolTip(tr("Показать выбранный файл или папку в Проводнике Windows"))
        self.check_lock_btn = QPushButton(tr("🔑 Кто держит?"))
        self.check_lock_btn.setToolTip(tr("Проверить через Restart Manager, какие процессы блокируют выбранный файл"))
        self.force_unlock_chk = QCheckBox(tr("Авто-анлок"))
        self.force_unlock_chk.setToolTip(tr("Автоматически разблокировать занятые процессами файлы перед удалением"))
        self.force_unlock_chk.setChecked(True)
        self.shred_chk = QCheckBox(tr("Шредер"))
        self.shred_chk.setToolTip(tr("Затирать содержимое удаляемых файлов нулями (для HDD)"))
        self.delete_selected_btn = QPushButton(tr("🗑️ Удалить (0 Б)"))
        self.delete_selected_btn.setObjectName("DangerButton")
        self.delete_selected_btn.setMinimumWidth(160)

        actions_bar.addWidget(self.sel_all_btn)
        actions_bar.addWidget(self.sel_none_btn)
        actions_bar.addWidget(self.open_loc_btn)
        actions_bar.addWidget(self.check_lock_btn)
        actions_bar.addStretch(1)
        actions_bar.addWidget(self.force_unlock_chk)
        actions_bar.addWidget(self.shred_chk)
        actions_bar.addWidget(self.delete_selected_btn)
        root.addLayout(actions_bar)

        # 4. Таблица предпросмотра найденных файлов/папок
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                tr("Выбор"),
                tr("Имя файла / папки"),
                tr("Категория"),
                tr("Размер"),
                tr("Возраст"),
                tr("Полный путь"),
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 56)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 220)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemChanged.connect(lambda _item: self._update_selected_button())
        root.addWidget(self.table, 1)

        self.summary_label = QLabel(
            tr("Выберите быстрый профиль сверху или задайте параметры фильтра для точечного поиска мусора.")
        )
        self.summary_label.setObjectName("Muted")
        root.addWidget(self.summary_label)

        # Привязка сигналов
        self.btn_downloads.clicked.connect(lambda: self.run_profile("old_downloads"))
        self.btn_app_caches.clicked.connect(lambda: self.run_profile("app_caches"))
        self.btn_logs.clicked.connect(lambda: self.run_profile("logs_dumps"))
        self.btn_dev_junk.clicked.connect(lambda: self.run_profile("dev_junk"))
        self.browse_btn.clicked.connect(self._browse_folder)
        self.filter_search_btn.clicked.connect(self.run_custom_search)
        self.stop_btn.clicked.connect(self.stop_scan)
        self.sel_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.sel_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.open_loc_btn.clicked.connect(self.open_selected_in_explorer)
        self.check_lock_btn.clicked.connect(self.inspect_selected_locks)
        self.unlocker_btn.clicked.connect(self.open_unlocker_picker)
        self.delete_selected_btn.clicked.connect(self.delete_checked_items)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("Выберите папку или диск для поиска"), self.path_edit.text() or str(Path.home())
        )
        if folder:
            self.path_edit.setText(folder)

    def _set_busy(self, busy: bool) -> None:
        for w in (
            self.btn_downloads,
            self.btn_app_caches,
            self.btn_logs,
            self.btn_dev_junk,
            self.filter_search_btn,
            self.delete_selected_btn,
        ):
            w.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def stop_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self.status_message.emit(tr("Остановка поиска…"))

    def run_profile(self, profile_id: str) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        custom_root = self.path_edit.text().strip()
        if profile_id == "dev_junk" and (
            not custom_root or os.path.normcase(custom_root) == os.path.normcase(str(Path.home()))
        ):
            folder = QFileDialog.getExistingDirectory(
                self,
                tr("Выберите папку с проектами для поиска node_modules / __pycache__ / target"),
                str(Path(__file__).resolve().parents[3]),
            )
            if not folder:
                return
            self.path_edit.setText(folder)
            custom_root = folder

        self._set_busy(True)
        self.summary_label.setText(tr("Сканирование по профилю…"))
        self._scan_worker = _PreciseScanWorker(
            mode="profile",
            profile_id=profile_id,
            custom_root=custom_root if profile_id == "dev_junk" else "",
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    def run_custom_search(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        folder = self.path_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, tr("Точечный поиск"), tr("Укажите существующую папку для поиска."))
            return

        raw_exts = self.ext_edit.text().strip()
        exts = {
            part.strip()
            for part in raw_exts.replace(";", ",").split(",")
            if part.strip()
        }
        unit_mult = int(self.size_unit_combo.currentData() or (1024 * 1024))
        min_bytes = int(self.min_size_spin.value() * unit_mult)
        min_age = float(self.age_spin.value())
        query = self.name_edit.text().strip()

        self._set_busy(True)
        self.summary_label.setText(tr("Поиск файлов по фильтру в {folder}…", folder=folder))
        self._scan_worker = _PreciseScanWorker(
            mode="custom",
            custom_root=folder,
            extensions=exts if exts else None,
            min_size_bytes=min_bytes,
            min_age_days=min_age,
            name_query=query,
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_progress(self, text: str) -> None:
        self.summary_label.setText(text)

    def _on_scan_finished(self, items: list[dict[str, Any]]) -> None:
        self._set_busy(False)
        self._items = items
        self._render_table()
        total_sz = sum(int(i.get("size", 0)) for i in items)
        msg = tr(
            "Найдено объектов: {count} на общую сумму {size}",
            count=len(items),
            size=format_bytes(total_sz),
        )
        self.summary_label.setText(msg)
        self.status_message.emit(msg)

    def _render_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._items))
        for row_idx, item in enumerate(self._items):
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(
                Qt.CheckState.Checked if item.get("checked", True) else Qt.CheckState.Unchecked
            )
            self.table.setItem(row_idx, 0, chk)

            prefix = "📁 " if item.get("is_dir") else "📄 "
            name_item = QTableWidgetItem(prefix + str(item.get("name", "")))
            name_item.setToolTip(
                f"{item.get('path', '')}\nИзменён: {format_timestamp(item.get('mtime'))}"
            )
            self.table.setItem(row_idx, 1, name_item)

            cat_item = QTableWidgetItem(str(item.get("category", "")))
            cat_item.setForeground(QColor("#8b9bb4"))
            self.table.setItem(row_idx, 2, cat_item)

            sz = int(item.get("size", 0))
            sz_item = QTableWidgetItem(format_bytes(sz))
            sz_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if sz >= 100 * 1024 * 1024:
                sz_item.setForeground(QColor("#ff5470"))
            elif sz >= 10 * 1024 * 1024:
                sz_item.setForeground(QColor("#ffb020"))
            else:
                sz_item.setForeground(QColor("#42f59b"))
            self.table.setItem(row_idx, 3, sz_item)

            age = float(item.get("age_days", 0.0))
            age_item = QTableWidgetItem(f"{age:.0f} дн.")
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_idx, 4, age_item)

            path_item = QTableWidgetItem(str(item.get("path", "")))
            path_item.setForeground(QColor("#8b9bb4"))
            self.table.setItem(row_idx, 5, path_item)

        self.table.blockSignals(False)
        self._update_selected_button()

    def _set_all_checked(self, checked: bool) -> None:
        self.table.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(state)
        self.table.blockSignals(False)
        self._update_selected_button()

    def _checked_items(self) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for r in range(min(self.table.rowCount(), len(self._items))):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                selected.append(self._items[r])
        return selected

    def _update_selected_button(self) -> None:
        checked = self._checked_items()
        sz = sum(int(i.get("size", 0)) for i in checked)
        self.delete_selected_btn.setText(
            tr(
                "🗑️ Удалить ({count} · {size})",
                count=len(checked),
                size=format_bytes(sz),
            )
        )

    def _current_row_item(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def _on_double_click(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._items):
            open_in_explorer(self._items[row].get("path", ""))

    def open_selected_in_explorer(self) -> None:
        item = self._current_row_item()
        if not item:
            self.status_message.emit(tr("Выберите строку в таблице"))
            return
        open_in_explorer(item.get("path", ""))

    def inspect_selected_locks(self) -> None:
        item = self._current_row_item()
        if not item:
            QMessageBox.information(
                self,
                tr("Проверка блокировки"),
                tr("Выберите файл или папку в таблице, либо нажмите кнопку «Разблокировать / удалить занятый файл…» сверху."),
            )
            return
        self._open_unlock_dialog_for(item.get("path", ""))

    def open_unlocker_picker(self) -> None:
        """Позволяет выбрать любой заблокированный файл или папку на ПК, разблокировать и при желании сразу удалить."""
        choice = QMessageBox.question(
            self,
            tr("Разблокировка и удаление"),
            tr("Что вы хотите выбрать для проверки блокировки и удаления?\n\n"
               "• «Да» (Yes) — выбрать ФАЙЛ\n"
               "• «Нет» (No) — выбрать ПАПКУ"),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        if choice == QMessageBox.StandardButton.Yes:
            target, _ = QFileDialog.getOpenFileName(
                self, tr("Выберите заблокированный файл"), str(Path.home())
            )
        else:
            target = QFileDialog.getExistingDirectory(
                self, tr("Выберите заблокированную папку"), str(Path.home())
            )
        if not target:
            return
        self._open_unlock_dialog_for(target, offer_delete_after=True)

    def _open_unlock_dialog_for(self, path: str, offer_delete_after: bool = False) -> None:
        from .unlock_dialog import UnlockDialog

        dlg = UnlockDialog(path, self)
        dlg.exec()
        if offer_delete_after and os.path.exists(path):
            safe, reason = is_safe_delete_path(path)
            if not safe:
                QMessageBox.warning(self, tr("Защита системы"), reason)
                return
            ans = QMessageBox.question(
                self,
                tr("Удалить разблокированный объект?"),
                tr("Удалить «{path}» с диска прямо сейчас?", path=path),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                res = delete_path_forced(
                    path,
                    keep_root_dir=False,
                    shred_passes=1 if self.shred_chk.isChecked() else 0,
                    unlock_if_locked=True,
                )
                if res.get("ok"):
                    msg = tr(
                        "Успешно удалено: {path} (освобождено {size})",
                        path=path,
                        size=format_bytes(int(res.get("freed_bytes", 0))),
                    )
                    self.status_message.emit(msg)
                    QMessageBox.information(self, tr("Удаление завершено"), msg)
                else:
                    QMessageBox.warning(
                        self,
                        tr("Ошибка удаления"),
                        tr("Не удалось удалить: {err}", err=res.get("error")),
                    )

    def delete_checked_items(self) -> None:
        if self._del_worker and self._del_worker.isRunning():
            return
        targets = self._checked_items()
        if not targets:
            QMessageBox.information(
                self, tr("Точечная очистка"), tr("Отметьте галочками файлы или папки для удаления.")
            )
            return

        total_sz = sum(int(i.get("size", 0)) for i in targets)
        preview_names = "\n".join(f"• {i.get('name')} ({format_bytes(int(i.get('size', 0)))})" for i in targets[:6])
        if len(targets) > 6:
            preview_names += f"\n… и ещё {len(targets) - 6} шт."

        answer = QMessageBox.warning(
            self,
            tr("Подтверждение точечного удаления"),
            tr(
                "Безвозвратно удалить выбранные объекты ({count} шт., {size})?\n\n{preview}",
                count=len(targets),
                size=format_bytes(total_sz),
                preview=preview_names,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._del_worker = _PreciseDeleteWorker(
            targets,
            unlock_if_locked=self.force_unlock_chk.isChecked(),
            shred_passes=1 if self.shred_chk.isChecked() else 0,
        )
        self._del_worker.progress.connect(self._on_delete_progress)
        self._del_worker.finished_delete.connect(self._on_delete_finished)
        self._del_worker.start()

    def _on_delete_progress(self, name: str, idx: int, total: int) -> None:
        self.summary_label.setText(
            tr("Удаление ({idx}/{total}): {name}…", idx=idx, total=total, name=name)
        )

    def _on_delete_finished(self, res: dict) -> None:
        self._set_busy(False)
        freed = int(res.get("freed_bytes", 0))
        deleted = int(res.get("deleted_count", 0))
        failed = int(res.get("failed_count", 0))
        pids = res.get("unlocked_pids") or []

        # Убираем из таблицы уже удалённые пути
        self._items = [i for i in self._items if os.path.exists(i.get("path", ""))]
        self._render_table()

        extra_unlock = f" (разблокировано процессов: {len(pids)})" if pids else ""
        msg = tr(
            "Удалено объектов: {deleted}, освобождено: {freed}{extra}",
            deleted=deleted,
            freed=format_bytes(freed),
            extra=extra_unlock,
        )
        if failed:
            msg += f" | Ошибок: {failed} ({res.get('last_error', '')})"
        self.summary_label.setText(msg)
        self.status_message.emit(msg)
        QMessageBox.information(self, tr("Точечная очистка"), msg)
