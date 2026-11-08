"""Вкладка «Быстрая очистка и SSD TRIM»: очистка кэшей, временных папок, Корзины и оптимизация дисков."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.cleaner_engine import (
    get_quick_clean_definitions,
    list_volumes,
    run_quick_clean,
    run_ssd_trim,
    scan_quick_clean,
)
from core.i18n import tr
from core.utils import format_bytes, open_in_explorer


class _QuickScanWorker(QThread):
    finished_scan = pyqtSignal(dict)

    def run(self) -> None:
        try:
            res = scan_quick_clean()
        except Exception as exc:
            res = {"categories": [], "total_bytes": 0, "total_files": 0, "error": str(exc)}
        self.finished_scan.emit(res)


class _QuickCleanWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished_clean = pyqtSignal(dict)

    def __init__(
        self,
        selected_ids: list[str],
        shred_passes: int = 0,
        unlock_locked: bool = False,
    ) -> None:
        super().__init__()
        self.selected_ids = selected_ids
        self.shred_passes = shred_passes
        self.unlock_locked = unlock_locked

    def run(self) -> None:
        try:
            res = run_quick_clean(
                self.selected_ids,
                shred_passes=self.shred_passes,
                unlock_locked=self.unlock_locked,
                progress_cb=lambda title, idx, total: self.progress.emit(title, idx, total),
            )
        except Exception as exc:
            res = {"freed_bytes": 0, "deleted_files": 0, "skipped_files": 0, "error": str(exc)}
        self.finished_clean.emit(res)


class _TrimWorker(QThread):
    finished_trim = pyqtSignal(bool, str)

    def __init__(self, letter: str) -> None:
        super().__init__()
        self.letter = letter

    def run(self) -> None:
        ok, msg = run_ssd_trim(self.letter)
        self.finished_trim.emit(ok, msg)


class CleanerView(QWidget):
    """Быстрая очистка временных файлов, кэшей браузеров, шейдеров, Корзины и SSD TRIM."""

    status_message = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._categories: list[dict] = []
        self._scan_worker: _QuickScanWorker | None = None
        self._clean_worker: _QuickCleanWorker | None = None
        self._trim_worker: _TrimWorker | None = None
        self._has_initial_scan = False
        self._build_ui()
        self._populate_initial_definitions()
        self.refresh_volumes()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Верхняя карточка сводки и управления
        summary_card = QFrame()
        summary_card.setObjectName("Card")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setSpacing(10)

        top_row = QHBoxLayout()
        title_col = QVBoxLayout()
        self.headline_label = QLabel(tr("Быстрая очистка временных файлов и кэшей"))
        self.headline_label.setObjectName("SectionTitle")
        self.sub_label = QLabel(
            tr(
                "Безопасное удаление временных файлов Windows, кэша браузеров (без потери паролей и сессий), "
                "кэша шейдеров видеокарты, отчётов об ошибках и Корзины."
            )
        )
        self.sub_label.setObjectName("Muted")
        self.sub_label.setWordWrap(True)
        title_col.addWidget(self.headline_label)
        title_col.addWidget(self.sub_label)
        top_row.addLayout(title_col, 1)

        self.total_badge = QLabel("0 Б")
        self.total_badge.setObjectName("PageTitle")
        self.total_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self.total_badge)
        summary_layout.addLayout(top_row)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(6)

        self.scan_button = QPushButton(tr("🔍 Сканировать"))
        self.clean_button = QPushButton(tr("🧹 Очистить выбранное"))
        self.clean_button.setObjectName("PrimaryButton")
        self.select_all_btn = QPushButton(tr("Все"))
        self.select_all_btn.setToolTip(tr("Выбрать все категории"))
        self.select_none_btn = QPushButton(tr("Снять"))
        self.select_none_btn.setToolTip(tr("Снять выбор со всех категорий"))

        self.unlock_check = QCheckBox(tr("Авто-разблокировка"))
        self.unlock_check.setToolTip(
            tr("Автоматически завершать фоновые процессы, удерживающие временные файлы (через Restart Manager)")
        )
        self.shred_check = QCheckBox(tr("Шредер (HDD)"))
        self.shred_check.setToolTip(
            tr("Затирать содержимое удаляемых файлов нулями перед удалением (на SSD не рекомендуется)")
        )

        controls_row.addWidget(self.scan_button)
        controls_row.addWidget(self.clean_button)
        controls_row.addWidget(self.select_all_btn)
        controls_row.addWidget(self.select_none_btn)
        controls_row.addStretch(1)
        controls_row.addWidget(self.unlock_check)
        controls_row.addWidget(self.shred_check)
        summary_layout.addLayout(controls_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        summary_layout.addWidget(self.progress_bar)

        root.addWidget(summary_card)

        # Таблица категорий очистки
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                tr("Выбор"),
                tr("Категория очистки"),
                tr("Группа"),
                tr("Файлов"),
                tr("Объём"),
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 64)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self.table.itemChanged.connect(lambda _item: self._recalculate_selected_total())
        root.addWidget(self.table, 1)

        # Нижняя карточка: Диски и SSD TRIM
        trim_card = QFrame()
        trim_card.setObjectName("Card")
        trim_layout = QHBoxLayout(trim_card)
        trim_layout.setContentsMargins(16, 12, 16, 12)
        trim_layout.setSpacing(12)

        trim_info = QVBoxLayout()
        trim_title = QLabel(tr("⚡ Оптимизация накопителей и SSD TRIM"))
        trim_title.setObjectName("SectionTitle")
        self.volumes_label = QLabel(tr("Загрузка сведений о дисках…"))
        self.volumes_label.setObjectName("Muted")
        self.volumes_label.setWordWrap(True)
        trim_info.addWidget(trim_title)
        trim_info.addWidget(self.volumes_label)
        trim_layout.addLayout(trim_info, 1)

        self.drive_combo = QComboBox()
        self.drive_combo.setMinimumWidth(210)
        self.trim_button = QPushButton(tr("Выполнить SSD TRIM"))
        self.trim_button.setToolTip(
            tr("Отправить команду ReTrim (Optimize-Volume) выбранному SSD-накопителю (требуются права администратора)")
        )
        self.refresh_drives_btn = QPushButton(tr("Обновить диски"))

        trim_layout.addWidget(self.drive_combo)
        trim_layout.addWidget(self.trim_button)
        trim_layout.addWidget(self.refresh_drives_btn)
        root.addWidget(trim_card)

        self.scan_button.clicked.connect(self.start_scan)
        self.clean_button.clicked.connect(self.start_clean)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.trim_button.clicked.connect(self.run_trim_selected)
        self.refresh_drives_btn.clicked.connect(self.refresh_volumes)

    def on_activated(self) -> None:
        """При первом открытии вкладки автоматически запускает быстрое сканирование."""
        if not self._has_initial_scan:
            self._has_initial_scan = True
            self.start_scan()

    def _populate_initial_definitions(self) -> None:
        defs = get_quick_clean_definitions()
        self._categories = [
            {**d, "size_bytes": 0, "files_count": 0, "resolved_paths": d.get("paths", [])}
            for d in defs
        ]
        self._render_table()

    def _render_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._categories))
        for row_idx, cat in enumerate(self._categories):
            chk_item = QTableWidgetItem()
            chk_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            checked = cat.get("checked", cat.get("default_checked", True))
            chk_item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            chk_item.setData(Qt.ItemDataRole.UserRole, cat["id"])
            self.table.setItem(row_idx, 0, chk_item)

            title_item = QTableWidgetItem(cat["title"])
            tooltip_lines = [
                cat.get("description", ""),
                "",
                tr("Папки:"),
                *(cat.get("resolved_paths") or [tr("(не найдено на диске)")]),
                "",
                tr("Двойной клик — открыть папку в Проводнике"),
            ]
            title_item.setToolTip("\n".join(tooltip_lines))
            self.table.setItem(row_idx, 1, title_item)

            group_item = QTableWidgetItem(cat.get("group", ""))
            group_item.setForeground(QColor("#8b9bb4"))
            self.table.setItem(row_idx, 2, group_item)

            files_cnt = int(cat.get("files_count", 0))
            files_item = QTableWidgetItem(f"{files_cnt:,}".replace(",", " "))
            files_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row_idx, 3, files_item)

            sz = int(cat.get("size_bytes", 0))
            sz_item = QTableWidgetItem(format_bytes(sz))
            sz_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            if sz > 100 * 1024 * 1024:
                sz_item.setForeground(QColor("#ffb020"))
            elif sz > 0:
                sz_item.setForeground(QColor("#42f59b"))
            else:
                sz_item.setForeground(QColor("#8b9bb4"))
            self.table.setItem(row_idx, 4, sz_item)

        self.table.blockSignals(False)
        self._recalculate_selected_total()

    def _set_all_checked(self, checked: bool) -> None:
        self.table.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item:
                item.setCheckState(state)
        self.table.blockSignals(False)
        self._recalculate_selected_total()

    def _selected_category_ids(self) -> list[str]:
        selected: list[str] = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                cid = item.data(Qt.ItemDataRole.UserRole)
                if cid:
                    selected.append(str(cid))
        return selected

    def _recalculate_selected_total(self) -> None:
        selected_ids = set(self._selected_category_ids())
        sel_bytes = 0
        sel_files = 0
        for cat in self._categories:
            if cat["id"] in selected_ids:
                sel_bytes += int(cat.get("size_bytes", 0))
                sel_files += int(cat.get("files_count", 0))
        self.total_badge.setText(
            f"{format_bytes(sel_bytes)}  ({sel_files:,} файл.)".replace(",", " ")
        )

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        if not (0 <= row < len(self._categories)):
            return
        cat = self._categories[row]
        paths = cat.get("resolved_paths") or []
        for p in paths:
            if p and p != "Корзина Windows":
                open_in_explorer(p)
                return

    # ------------------------------------------------------------------
    # Сканирование и очистка
    # ------------------------------------------------------------------
    def start_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.clean_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_message.emit(tr("Сканирование временных папок и кэшей…"))

        self._scan_worker = _QuickScanWorker()
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_finished(self, payload: dict) -> None:
        self.scan_button.setEnabled(True)
        self.clean_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)

        prev_checked = {
            self.table.item(r, 0).data(Qt.ItemDataRole.UserRole): (
                self.table.item(r, 0).checkState() == Qt.CheckState.Checked
            )
            for r in range(self.table.rowCount())
            if self.table.item(r, 0) is not None
        }

        cats = payload.get("categories", [])
        for c in cats:
            if c["id"] in prev_checked:
                c["checked"] = prev_checked[c["id"]]
        self._categories = cats
        self._render_table()

        total_b = int(payload.get("total_bytes", 0))
        total_f = int(payload.get("total_files", 0))
        ms = payload.get("elapsed_ms", 0)
        self.status_message.emit(
            tr(
                "Сканирование завершено за {ms} мс: обнаружено {size} ({files} файлов)",
                ms=ms,
                size=format_bytes(total_b),
                files=total_f,
            )
        )

    def start_clean(self) -> None:
        if self._clean_worker and self._clean_worker.isRunning():
            return
        selected = self._selected_category_ids()
        if not selected:
            QMessageBox.information(
                self, tr("Быстрая очистка"), tr("Отметьте хотя бы одну категорию для очистки.")
            )
            return

        answer = QMessageBox.question(
            self,
            tr("Подтверждение быстрой очистки"),
            tr(
                "Удалить временные файлы и кэш в выбранных категориях ({count} шт.)?\n"
                "Открытые вкладки и пароли в браузерах затронуты не будут.",
                count=len(selected),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        shred = 1 if self.shred_check.isChecked() else 0
        unlock = self.unlock_check.isChecked()

        self.scan_button.setEnabled(False)
        self.clean_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(selected))
        self.progress_bar.setValue(0)

        self._clean_worker = _QuickCleanWorker(
            selected, shred_passes=shred, unlock_locked=unlock
        )
        self._clean_worker.progress.connect(self._on_clean_progress)
        self._clean_worker.finished_clean.connect(self._on_clean_finished)
        self._clean_worker.start()

    def _on_clean_progress(self, title: str, current: int, total: int) -> None:
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(current)
        self.status_message.emit(tr("Очистка: {title} ({cur}/{total})…", title=title, cur=current, total=total))

    def _on_clean_finished(self, res: dict) -> None:
        self.scan_button.setEnabled(True)
        self.clean_button.setEnabled(True)
        self.progress_bar.setVisible(False)

        freed = int(res.get("freed_bytes", 0))
        deleted = int(res.get("deleted_files", 0))
        skipped = int(res.get("skipped_files", 0))
        msg = tr(
            "Очистка завершена! Освобождено: {freed} (удалено файлов: {deleted}, пропущено занятых: {skipped})",
            freed=format_bytes(freed),
            deleted=deleted,
            skipped=skipped,
        )
        self.status_message.emit(msg)
        QMessageBox.information(self, tr("Результат очистки"), msg)
        self.refresh_volumes()
        self.start_scan()

    # ------------------------------------------------------------------
    # Тома и SSD TRIM
    # ------------------------------------------------------------------
    def refresh_volumes(self) -> None:
        vols = list_volumes()
        self.drive_combo.clear()
        summary_parts: list[str] = []
        for v in vols:
            letter = v["letter"]
            free_str = format_bytes(v["free"])
            tot_str = format_bytes(v["total"])
            pct = v["percent"]
            label = f"Диск {letter}: — свободно {free_str} из {tot_str} (занято {pct}%)"
            self.drive_combo.addItem(label, letter)
            summary_parts.append(f"{letter}: свободно {free_str} / {tot_str} ({pct}%)")
        self.volumes_label.setText("   ·   ".join(summary_parts) if summary_parts else tr("Тома не найдены"))

    def run_trim_selected(self) -> None:
        if self._trim_worker and self._trim_worker.isRunning():
            return
        letter = self.drive_combo.currentData() or "C"
        self.trim_button.setEnabled(False)
        self.status_message.emit(tr("Выполнение SSD TRIM на диске {letter}:…", letter=letter))

        self._trim_worker = _TrimWorker(str(letter))
        self._trim_worker.finished_trim.connect(self._on_trim_finished)
        self._trim_worker.start()

    def _on_trim_finished(self, ok: bool, message: str) -> None:
        self.trim_button.setEnabled(True)
        self.status_message.emit(message)
        if ok:
            QMessageBox.information(self, tr("SSD TRIM"), message)
        else:
            QMessageBox.warning(self, tr("SSD TRIM"), message)
