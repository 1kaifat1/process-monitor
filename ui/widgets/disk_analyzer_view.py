"""Вкладка «Анализатор диска (WizTree + Монитор процессов) и Дубликаты»: дерево папок/файлов, связь с процессами, Treemap, топ-100 файлов и дубликаты SHA-1."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import psutil
from PyQt6.QtCore import QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.cleaner_engine import (
    analyze_disk_space,
    collect_active_processes_for_disk,
    delete_path_forced,
    find_duplicates,
    find_processes_for_path,
    is_safe_delete_path,
    list_volumes,
    send_to_recycle_bin,
    terminate_processes_in_path_and_delete,
)
from core.i18n import tr
from core.utils import format_bytes, format_timestamp, open_in_explorer

TREEMAP_PALETTE = [
    "#00d4ff",
    "#3b82f6",
    "#8b5cf6",
    "#10b981",
    "#f59e0b",
    "#ec4899",
    "#06b6d4",
    "#6366f1",
    "#14b8a6",
    "#f97316",
    "#a855f7",
    "#22c55e",
]


def _make_bar_text(pct: float, width: int = 10) -> str:
    """Сформировать текстовую полоску заполнения в стиле WizTree."""
    pct_clamped = max(0.0, min(100.0, pct))
    filled = int(round((pct_clamped / 100.0) * width))
    empty = max(0, width - filled)
    bar = "█" * filled + "░" * empty
    return f"{bar} {pct_clamped:5.1f}%"


class _WizTreeWidgetItem(QTreeWidgetItem):
    """Элемент дерева WizTree с корректной числовой сортировкой по размеру, доле % и числу процессов."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 2
        if col in (1, 2):
            s1 = int(self.data(0, Qt.ItemDataRole.UserRole + 1) or 0)
            s2 = int(other.data(0, Qt.ItemDataRole.UserRole + 1) or 0)
            return s1 < s2
        if col == 3:
            p1 = int(self.data(0, Qt.ItemDataRole.UserRole + 2) or 0)
            p2 = int(other.data(0, Qt.ItemDataRole.UserRole + 2) or 0)
            return p1 < p2
        if col == 4:
            f1 = int(self.data(0, Qt.ItemDataRole.UserRole + 3) or 0)
            f2 = int(other.data(0, Qt.ItemDataRole.UserRole + 3) or 0)
            return f1 < f2
        return super().__lt__(other)


class TreemapWidget(QWidget):
    """Интерактивная пропорциональная карта занятого места на диске (Treemap)."""

    node_clicked = pyqtSignal(dict)
    node_right_clicked = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(130)
        self.setMouseTracking(True)
        self._node: dict[str, Any] | None = None
        self._rects: list[tuple[QRectF, dict[str, Any], QColor]] = []
        self._hover_idx: int = -1

    def set_node(self, node: dict[str, Any] | None) -> None:
        self._node = node
        self._hover_idx = -1
        self._recompute_layout()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._recompute_layout()

    def _recompute_layout(self) -> None:
        self._rects = []
        if not self._node:
            return
        children = [c for c in (self._node.get("children") or []) if int(c.get("size", 0)) > 0]
        if not children:
            return
        bounds = QRectF(4.0, 4.0, max(10.0, self.width() - 8.0), max(10.0, self.height() - 8.0))
        self._slice_and_dice(children, bounds, 0)

    def _slice_and_dice(
        self, items: list[dict[str, Any]], rect: QRectF, color_offset: int
    ) -> None:
        if not items or rect.width() < 4 or rect.height() < 4:
            return
        if len(items) == 1:
            color = QColor(TREEMAP_PALETTE[color_offset % len(TREEMAP_PALETTE)])
            self._rects.append((rect, items[0], color))
            return

        total = sum(max(1, int(it.get("size", 0))) for it in items)
        half = total / 2.0
        acc = 0
        split_idx = 1
        for i, it in enumerate(items):
            acc += max(1, int(it.get("size", 0)))
            if acc >= half:
                split_idx = max(1, i + 1)
                break
        if split_idx >= len(items):
            split_idx = len(items) - 1

        left_items = items[:split_idx]
        right_items = items[split_idx:]
        left_sum = sum(max(1, int(it.get("size", 0))) for it in left_items)
        ratio = max(0.08, min(0.92, left_sum / max(1.0, float(total))))

        gap = 3.0
        if rect.width() >= rect.height():
            w1 = max(2.0, rect.width() * ratio - gap / 2.0)
            w2 = max(2.0, rect.width() - w1 - gap)
            r1 = QRectF(rect.x(), rect.y(), w1, rect.height())
            r2 = QRectF(rect.x() + w1 + gap, rect.y(), w2, rect.height())
        else:
            h1 = max(2.0, rect.height() * ratio - gap / 2.0)
            h2 = max(2.0, rect.height() - h1 - gap)
            r1 = QRectF(rect.x(), rect.y(), rect.width(), h1)
            r2 = QRectF(rect.x(), rect.y() + h1 + gap, rect.width(), h2)

        self._slice_and_dice(left_items, r1, color_offset)
        self._slice_and_dice(right_items, r2, color_offset + split_idx)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor("#0d1320")
        painter.fillRect(self.rect(), bg)

        if not self._rects:
            painter.setPen(QColor("#8b9bb4"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                tr("Нажмите «📊 Сканировать», чтобы построить карту папки"),
            )
            return

        total_size = max(1, int((self._node or {}).get("size", 1)))
        font_bold = QFont(self.font())
        font_bold.setBold(True)
        font_small = QFont(self.font())
        font_small.setPointSize(max(8, font_small.pointSize() - 1))

        for idx, (rect, item, base_color) in enumerate(self._rects):
            is_hovered = idx == self._hover_idx
            has_procs = int(item.get("proc_count", 0)) > 0
            fill = QColor(base_color)
            fill.setAlpha(220 if is_hovered else 160)
            painter.setBrush(QBrush(fill))
            if has_procs:
                border_color = QColor("#00f0ff") if not is_hovered else QColor("#ffffff")
                pen_w = 2.2 if is_hovered else 1.6
            else:
                border_color = QColor("#ffffff") if is_hovered else QColor(base_color).lighter(130)
                pen_w = 1.8 if is_hovered else 1.0
            painter.setPen(QPen(border_color, pen_w))
            painter.drawRoundedRect(rect, 6.0, 6.0)

            if rect.width() > 54 and rect.height() > 26:
                prefix = "⚡ " if has_procs else ("📁 " if item.get("is_dir", True) else "📄 ")
                name = prefix + str(item.get("name", ""))
                sz_str = format_bytes(int(item.get("size", 0)))
                pct = int(item.get("size", 0)) / total_size * 100.0
                text_rect = rect.adjusted(6, 4, -6, -4)
                painter.setPen(QColor("#ffffff"))
                painter.setFont(font_bold)
                painter.drawText(
                    text_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    name,
                )
                if rect.height() > 44:
                    painter.setFont(font_small)
                    painter.setPen(QColor("#e2e8f0"))
                    sub = f"{sz_str} ({pct:.1f}%)"
                    if has_procs:
                        sub += f" · ⚡ {item.get('proc_count')} проц."
                    painter.drawText(
                        text_rect.adjusted(0, 17, 0, 0),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                        sub,
                    )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        found = -1
        for idx, (rect, item, _color) in enumerate(self._rects):
            if rect.contains(pos):
                found = idx
                total_sz = max(1, int((self._node or {}).get("size", 1)))
                sz = int(item.get("size", 0))
                pct = sz / total_sz * 100.0
                procs_line = ""
                if int(item.get("proc_count", 0)) > 0:
                    names = ", ".join(item.get("proc_names") or [])
                    procs_line = f"\n⚡ Активные процессы ({item.get('proc_count')}): {names}"
                tip = (
                    f"{'📁' if item.get('is_dir', True) else '📄'} {item.get('name')}\n"
                    f"Объём: {format_bytes(sz)} ({pct:.1f}%)\n"
                    f"Путь: {item.get('path')}{procs_line}\n"
                    f"ЛКМ — выбрать в дереве WizTree | ПКМ — открыть в Проводнике"
                )
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                break
        if found != self._hover_idx:
            self._hover_idx = found
            self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hover_idx = -1
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        for _rect, item, _color in self._rects:
            if _rect.contains(pos):
                if event.button() == Qt.MouseButton.LeftButton:
                    self.node_clicked.emit(item)
                elif event.button() == Qt.MouseButton.RightButton:
                    self.node_right_clicked.emit(item)
                break


class _DiskAnalyzeWorker(QThread):
    progress = pyqtSignal(str)
    finished_analyze = pyqtSignal(dict)

    def __init__(self, root_path: str) -> None:
        super().__init__()
        self.root_path = root_path
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            res = analyze_disk_space(
                self.root_path,
                max_tree_depth=4,
                top_files_limit=100,
                cancel_event=self.cancel_event,
                progress_cb=lambda msg: self.progress.emit(msg),
            )
        except Exception as exc:
            res = {"error": str(exc)}
        self.finished_analyze.emit(res)


class _DuplicateScanWorker(QThread):
    progress = pyqtSignal(str)
    finished_duplicates = pyqtSignal(dict)

    def __init__(self, root_path: str, min_size_bytes: int = 100 * 1024) -> None:
        super().__init__()
        self.root_path = root_path
        self.min_size_bytes = min_size_bytes
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            res = find_duplicates(
                self.root_path,
                min_size_bytes=self.min_size_bytes,
                cancel_event=self.cancel_event,
                progress_cb=lambda msg: self.progress.emit(msg),
            )
        except Exception as exc:
            res = {"groups": [], "error": str(exc)}
        self.finished_duplicates.emit(res)


class DiskAnalyzerView(QWidget):
    """Анализатор диска в стиле WizTree + Монитор процессов в папках, Топ-100 файлов и Дубликаты SHA-1."""

    status_message = pyqtSignal(str)
    focus_process_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analyze_worker: _DiskAnalyzeWorker | None = None
        self._dup_worker: _DuplicateScanWorker | None = None
        self._root_node: dict[str, Any] | None = None
        self._active_processes: list[dict[str, Any]] = []
        self._selected_node_procs: list[dict[str, Any]] = []
        self._path_to_tree_item: dict[str, _WizTreeWidgetItem] = {}
        self._top_files: list[dict[str, Any]] = []
        self._dup_flat_rows: list[dict[str, Any]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Верхняя панель выбора папки / диска и запуска
        top_card = QFrame()
        top_card.setObjectName("Card")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(6)

        self.quick_volume_combo = QComboBox()
        self.quick_volume_combo.setMinimumWidth(145)
        self.quick_volume_combo.setMaximumWidth(205)
        self._populate_volumes_combo()

        self.path_edit = QLineEdit(str(Path.home()))
        self.path_edit.setMinimumWidth(140)
        self.path_edit.setPlaceholderText(tr("Путь к папке или диску…"))

        self.browse_btn = QPushButton(tr("Обзор…"))
        self.analyze_btn = QPushButton(tr("📊 Сканировать"))
        self.analyze_btn.setObjectName("PrimaryButton")
        self.analyze_btn.setToolTip(
            tr("Просканировать выбранную папку или диск (дерево WizTree + активные процессы + топ-100 файлов)")
        )
        self.dup_btn = QPushButton(tr("👯 Дубликаты"))
        self.dup_btn.setToolTip(tr("Найти 100% идентичные дубликаты файлов (по SHA-1)"))
        self.stop_btn = QPushButton(tr("⏹ Стоп"))
        self.stop_btn.setEnabled(False)

        top_layout.addWidget(QLabel(tr("Участок:")))
        top_layout.addWidget(self.quick_volume_combo)
        top_layout.addWidget(self.path_edit, 1)
        top_layout.addWidget(self.browse_btn)
        top_layout.addWidget(self.analyze_btn)
        top_layout.addWidget(self.dup_btn)
        top_layout.addWidget(self.stop_btn)
        root.addWidget(top_card)

        # Внутренние вкладки: 1) Дерево WizTree + Процессы, 2) Топ-100 файлов и типы, 3) Дубликаты
        self.tabs = QTabWidget()
        self._build_wiztree_tab()
        self._build_top_files_tab()
        self._build_duplicates_tab()
        root.addWidget(self.tabs, 1)

        self.status_lbl = QLabel(
            tr(
                "Выберите папку или диск и нажмите «📊 Сканировать WizTree + Процессы», "
                "чтобы увидеть размер всех папок/файлов и какие процессы в них работают."
            )
        )
        self.status_lbl.setObjectName("Muted")
        root.addWidget(self.status_lbl)

        self.quick_volume_combo.currentIndexChanged.connect(self._on_quick_volume_changed)
        self.browse_btn.clicked.connect(self._browse_folder)
        self.analyze_btn.clicked.connect(self.start_disk_analysis)
        self.dup_btn.clicked.connect(self.start_duplicate_scan)
        self.stop_btn.clicked.connect(self.stop_workers)

    def _populate_volumes_combo(self) -> None:
        self.quick_volume_combo.blockSignals(True)
        self.quick_volume_combo.clear()
        self.quick_volume_combo.addItem(tr("🏠 Профиль пользователя"), str(Path.home()))
        self.quick_volume_combo.addItem(tr("📥 Папка Загрузки"), str(Path.home() / "Downloads"))
        self.quick_volume_combo.addItem(
            tr("📦 AppData (Local)"),
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")),
        )
        self.quick_volume_combo.addItem(
            tr("🎮 Program Files"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
        )
        self.quick_volume_combo.addItem(
            tr("🎮 Program Files (x86)"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        )
        for v in list_volumes():
            self.quick_volume_combo.addItem(
                f"💾 Диск {v['letter']}: ({format_bytes(v['free'])} своб.)",
                v["mountpoint"],
            )
        self.quick_volume_combo.blockSignals(False)

    def _on_quick_volume_changed(self) -> None:
        path = self.quick_volume_combo.currentData()
        if path:
            self.path_edit.setText(str(path))

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("Выберите папку или диск"), self.path_edit.text() or str(Path.home())
        )
        if folder:
            self.path_edit.setText(folder)

    # ------------------------------------------------------------------
    # Вкладка 1: Иерархическое дерево WizTree + Живой монитор процессов в папках + Карта Treemap
    # ------------------------------------------------------------------
    def _build_wiztree_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Панель фильтрации и удаления выбранного узла WizTree
        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)

        self.tree_search_edit = QLineEdit()
        self.tree_search_edit.setMinimumWidth(160)
        self.tree_search_edit.setPlaceholderText(
            tr("🔎 Поиск файла, папки или процесса…")
        )
        self.tree_search_edit.setClearButtonEnabled(True)

        self.only_procs_chk = QCheckBox(tr("⚡ С процессами"))
        self.only_procs_chk.setToolTip(
            tr("Показывать только папки и файлы, в которых сейчас работают процессы или открыты файлы")
        )
        self.refresh_procs_btn = QPushButton(tr("🔄 Процессы"))
        self.refresh_procs_btn.setToolTip(
            tr("Пересканировать запущенные процессы и открытые ими файлы без повторного обхода диска")
        )

        self.open_node_btn = QPushButton(tr("📂 Папка"))
        self.open_node_btn.setToolTip(tr("Показать выбранную папку или файл в Проводнике Windows"))
        self.trash_btn = QPushButton(tr("♻️ В Корзину"))
        self.trash_btn.setToolTip(
            tr("Безопасно отправить выбранный файл или папку в Корзину Windows")
        )
        self.perm_delete_btn = QPushButton(tr("🧨 Удалить навсегда"))
        self.perm_delete_btn.setObjectName("DangerButton")
        self.perm_delete_btn.setToolTip(
            tr(
                "Автоматически завершить все процессы, запущенные из выбранной папки или держащие её файлы, "
                "и безвозвратно удалить папку/файл"
            )
        )

        action_bar.addWidget(self.tree_search_edit, 1)
        action_bar.addWidget(self.only_procs_chk)
        action_bar.addWidget(self.refresh_procs_btn)
        action_bar.addWidget(self.open_node_btn)
        action_bar.addWidget(self.trash_btn)
        action_bar.addWidget(self.perm_delete_btn)
        layout.addLayout(action_bar)

        # Вертикальный сплиттер: сверху широкое Дерево WizTree на всю ширину, снизу Процессы в папке + Treemap
        main_splitter = QSplitter(Qt.Orientation.Vertical)

        # Верхняя часть: иерархическое дерево WizTree во всю ширину окна
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(4)

        self.current_node_lbl = QLabel(tr("Выбранный узел: —"))
        self.current_node_lbl.setObjectName("Muted")
        tree_layout.addWidget(self.current_node_lbl)

        self.wiztree = QTreeWidget()
        self.wiztree.setColumnCount(6)
        self.wiztree.setHeaderLabels(
            [
                tr("Папка / Файл"),
                tr("Доля % (от родителя)"),
                tr("Размер"),
                tr("⚡ Активные процессы"),
                tr("Файлов / Тип"),
                tr("Изменён"),
            ]
        )
        self.wiztree.setAlternatingRowColors(True)
        self.wiztree.setUniformRowHeights(True)
        self.wiztree.setAnimated(True)
        self.wiztree.setSortingEnabled(True)
        self.wiztree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.wiztree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.wiztree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.wiztree.setColumnWidth(1, 145)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.wiztree.setColumnWidth(3, 195)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        tree_layout.addWidget(self.wiztree, 1)
        main_splitter.addWidget(tree_container)

        # Нижняя часть: горизонтальный сплиттер (Слева — Активные процессы в выбранной папке, Справа — Карта Treemap)
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)

        proc_card = QFrame()
        proc_card.setObjectName("Card")
        proc_layout = QVBoxLayout(proc_card)
        proc_layout.setContentsMargins(10, 8, 10, 8)
        proc_layout.setSpacing(4)

        proc_top_bar = QHBoxLayout()
        proc_top_bar.setSpacing(6)
        self.proc_panel_title = QLabel(tr("⚡ Процессы в выбранной папке"))
        self.proc_panel_title.setObjectName("SectionTitle")
        proc_top_bar.addWidget(self.proc_panel_title, 1)

        self.check_handles_btn = QPushButton(tr("🔍 Дескрипторы"))
        self.check_handles_btn.setToolTip(
            tr("Дополнительно опросить ядро Windows (Restart Manager) на скрытые блокировки и открытые дескрипторы")
        )
        self.jump_proc_btn = QPushButton(tr("🔎 К процессу"))
        self.jump_proc_btn.setToolTip(tr("Перейти к выбранному процессу во вкладке «Процессы»"))
        self.kill_proc_btn = QPushButton(tr("⛔ Завершить"))
        self.kill_proc_btn.setObjectName("DangerButton")
        self.kill_proc_btn.setToolTip(tr("Принудительно завершить выбранный процесс"))

        proc_top_bar.addWidget(self.check_handles_btn)
        proc_top_bar.addWidget(self.jump_proc_btn)
        proc_top_bar.addWidget(self.kill_proc_btn)
        proc_layout.addLayout(proc_top_bar)

        self.proc_panel_sub = QLabel(
            tr("Выберите папку или файл в дереве сверху — здесь появятся связанные с ней процессы и открытые файлы.")
        )
        self.proc_panel_sub.setObjectName("Muted")
        self.proc_panel_sub.setWordWrap(True)
        proc_layout.addWidget(self.proc_panel_sub)

        self.node_procs_table = QTableWidget(0, 5)
        self.node_procs_table.setHorizontalHeaderLabels(
            [
                tr("Процесс (PID)"),
                tr("Связь"),
                tr("Какой файл держит"),
                tr("Что делает процесс"),
                tr("Память"),
            ]
        )
        self.node_procs_table.setAlternatingRowColors(True)
        self.node_procs_table.setShowGrid(False)
        self.node_procs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.node_procs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.node_procs_table.verticalHeader().setVisible(False)
        self.node_procs_table.verticalHeader().setDefaultSectionSize(25)
        ph = self.node_procs_table.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.node_procs_table.setColumnWidth(2, 165)
        ph.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        proc_layout.addWidget(self.node_procs_table, 1)
        bottom_splitter.addWidget(proc_card)

        treemap_card = QFrame()
        treemap_card.setObjectName("Card")
        tm_layout = QVBoxLayout(treemap_card)
        tm_layout.setContentsMargins(10, 8, 10, 8)
        tm_layout.setSpacing(4)
        tm_header = QLabel(tr("🗺️ Карта выбранной папки (Treemap · ⚡ — есть процессы)"))
        tm_header.setObjectName("Muted")
        tm_layout.addWidget(tm_header)
        self.treemap = TreemapWidget()
        tm_layout.addWidget(self.treemap, 1)
        bottom_splitter.addWidget(treemap_card)

        bottom_splitter.setStretchFactor(0, 3)
        bottom_splitter.setStretchFactor(1, 2)
        main_splitter.addWidget(bottom_splitter)

        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)
        layout.addWidget(main_splitter, 1)

        # Сигналы WizTree и панели процессов
        self.wiztree.itemSelectionChanged.connect(self._on_wiztree_selection_changed)
        self.wiztree.itemDoubleClicked.connect(self._on_wiztree_item_double_clicked)
        self.tree_search_edit.textChanged.connect(self._apply_tree_filter)
        self.only_procs_chk.toggled.connect(self._apply_tree_filter)
        self.refresh_procs_btn.clicked.connect(self.refresh_active_processes_overlay)
        self.open_node_btn.clicked.connect(self._open_selected_wiztree_in_explorer)
        self.trash_btn.clicked.connect(self._delete_selected_wiztree_to_trash)
        self.perm_delete_btn.clicked.connect(self._delete_selected_wiztree_permanently)

        self.check_handles_btn.clicked.connect(self._check_selected_node_restart_manager)
        self.jump_proc_btn.clicked.connect(self._jump_to_selected_node_process)
        self.kill_proc_btn.clicked.connect(self._kill_selected_node_process)
        self.node_procs_table.cellDoubleClicked.connect(
            lambda _r, _c: self._jump_to_selected_node_process()
        )

        self.treemap.node_clicked.connect(self._on_treemap_node_clicked)
        self.treemap.node_right_clicked.connect(lambda n: open_in_explorer(n.get("path", "")))

        self.tabs.addTab(page, tr("🌳 Дерево WizTree + Процессы и Карта"))

    # ------------------------------------------------------------------
    # Вкладка 2: Топ-100 самых крупных файлов + Статистика расширений
    # ------------------------------------------------------------------
    def _build_top_files_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(tr("Топ-100 самых больших файлов:")))
        bar.addStretch(1)
        self.open_top_file_btn = QPushButton(tr("📂 Папка"))
        self.trash_top_files_btn = QPushButton(tr("♻️ В Корзину"))
        self.del_top_files_btn = QPushButton(tr("🧨 Удалить навсегда"))
        self.del_top_files_btn.setObjectName("DangerButton")
        bar.addWidget(self.open_top_file_btn)
        bar.addWidget(self.trash_top_files_btn)
        bar.addWidget(self.del_top_files_btn)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.top_files_table = QTableWidget(0, 5)
        self.top_files_table.setHorizontalHeaderLabels(
            [tr("Выбор"), tr("Имя файла"), tr("Размер"), tr("Изменён"), tr("Путь")]
        )
        self.top_files_table.setAlternatingRowColors(True)
        self.top_files_table.setShowGrid(False)
        self.top_files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.top_files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.top_files_table.verticalHeader().setVisible(False)
        th = self.top_files_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.top_files_table.setColumnWidth(0, 56)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.top_files_table.setColumnWidth(1, 220)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.top_files_table)

        self.ext_table = QTableWidget(0, 4)
        self.ext_table.setHorizontalHeaderLabels(
            [tr("Расширение"), tr("Объём"), tr("Файлов"), tr("Доля %")]
        )
        self.ext_table.setAlternatingRowColors(True)
        self.ext_table.setShowGrid(False)
        self.ext_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ext_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ext_table.verticalHeader().setVisible(False)
        eh = self.ext_table.horizontalHeader()
        eh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        eh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        eh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.ext_table)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.open_top_file_btn.clicked.connect(self._open_selected_top_file)
        self.trash_top_files_btn.clicked.connect(lambda: self._delete_checked_top_files(use_trash=True))
        self.del_top_files_btn.clicked.connect(lambda: self._delete_checked_top_files(use_trash=False))
        self.top_files_table.cellDoubleClicked.connect(
            lambda r, _c: open_in_explorer(self._top_files[r]["path"]) if 0 <= r < len(self._top_files) else None
        )

        self.tabs.addTab(page, tr("📦 Топ-100 крупных файлов и Типы"))

    # ------------------------------------------------------------------
    # Вкладка 3: Поиск дубликатов файлов (SHA-1)
    # ------------------------------------------------------------------
    def _build_duplicates_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        self.dup_summary_lbl = QLabel(
            tr("Дубликаты ищутся в 3 этапа (размер → быстрый краевой хэш → полный SHA-1). Оригиналы защищены от случайного удаления.")
        )
        self.dup_summary_lbl.setObjectName("Muted")
        bar.addWidget(self.dup_summary_lbl, 1)

        self.open_dup_btn = QPushButton(tr("📂 Папка"))
        self.restore_dups_btn = QPushButton(tr("⏪ Восстановить удалённые"))
        self.restore_dups_btn.setToolTip(
            tr("Восстанавливает удалённые копии один-в-один на прежние места из сохранённых оригиналов")
        )
        self.del_dups_btn = QPushButton(tr("♻️ Удалить отмеченные копии (в Корзину)"))
        self.del_dups_btn.setObjectName("DangerButton")
        bar.addWidget(self.open_dup_btn)
        bar.addWidget(self.restore_dups_btn)
        bar.addWidget(self.del_dups_btn)
        layout.addLayout(bar)

        self.dup_table = QTableWidget(0, 5)
        self.dup_table.setHorizontalHeaderLabels(
            [tr("Удалить?"), tr("Статус"), tr("Группа SHA-1 / Имя"), tr("Размер"), tr("Полный путь")]
        )
        self.dup_table.setAlternatingRowColors(True)
        self.dup_table.setShowGrid(False)
        self.dup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dup_table.verticalHeader().setVisible(False)
        dh = self.dup_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.dup_table.setColumnWidth(0, 64)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.dup_table.setColumnWidth(2, 185)
        dh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.dup_table, 1)

        self.open_dup_btn.clicked.connect(self._open_selected_dup)
        self.restore_dups_btn.clicked.connect(self._restore_deleted_duplicates)
        self.del_dups_btn.clicked.connect(self._delete_checked_duplicates)
        self.dup_table.cellDoubleClicked.connect(
            lambda r, _c: open_in_explorer(self._dup_flat_rows[r]["path"]) if 0 <= r < len(self._dup_flat_rows) else None
        )
        self._update_restore_dups_btn()

        self.tabs.addTab(page, tr("👯 Дубликаты файлов (SHA-1)"))

    # ------------------------------------------------------------------
    # Запуск и обработка анализа WizTree + Процессы
    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self.analyze_btn.setEnabled(not busy)
        self.dup_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def _refresh_busy_state(self) -> None:
        running = bool(
            (self._analyze_worker and self._analyze_worker.isRunning())
            or (self._dup_worker and self._dup_worker.isRunning())
        )
        self._set_busy(running)

    def stop_workers(self) -> None:
        if self._analyze_worker and self._analyze_worker.isRunning():
            self._analyze_worker.cancel()
        if self._dup_worker and self._dup_worker.isRunning():
            self._dup_worker.cancel()
        self.status_lbl.setText(tr("Остановка сканирования…"))
        self.dup_summary_lbl.setText(tr("Остановка сканирования…"))

    def start_disk_analysis(self) -> None:
        if self._analyze_worker and self._analyze_worker.isRunning():
            return
        if self._dup_worker and self._dup_worker.isRunning():
            self._dup_worker.cancel()
        folder = self.path_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, tr("Анализ диска"), tr("Укажите существующую папку или диск."))
            return
        self._set_busy(True)
        self.tabs.setCurrentIndex(0)
        self.status_lbl.setText(tr("Сканирование дерева WizTree и активных процессов: {folder}…", folder=folder))

        self._analyze_worker = _DiskAnalyzeWorker(folder)
        self._analyze_worker.progress.connect(lambda m: self.status_lbl.setText(m))
        self._analyze_worker.finished_analyze.connect(self._on_analyze_finished)
        self._analyze_worker.start()

    def _on_analyze_finished(self, payload: dict) -> None:
        self._refresh_busy_state()
        if payload.get("error"):
            self.status_lbl.setText(tr("Ошибка анализа: {err}", err=payload["error"]))
            return

        self._root_node = payload.get("root")
        self._active_processes = payload.get("active_processes") or collect_active_processes_for_disk()
        self._populate_wiztree()

        self._top_files = payload.get("top_files", [])
        self._render_top_files(payload.get("extensions", []))

        summary = payload.get("summary", {})
        root_procs = int((self._root_node or {}).get("proc_count", 0))
        msg = tr(
            "WizTree готов за {ms} мс: {files} файлов в {dirs} папках ({size}) · "
            "активных процессов в этой области: {procs}",
            ms=summary.get("elapsed_ms", 0),
            files=summary.get("files_count", 0),
            dirs=summary.get("dirs_count", 0),
            size=format_bytes(int(summary.get("total_size", 0))),
            procs=root_procs,
        )
        self.status_lbl.setText(msg)
        self.status_message.emit(msg)

    def _populate_wiztree(self) -> None:
        self.wiztree.setSortingEnabled(False)
        self.wiztree.clear()
        self._path_to_tree_item.clear()

        if not self._root_node:
            self.treemap.set_node(None)
            self.wiztree.setSortingEnabled(True)
            return

        root_sz = max(1, int(self._root_node.get("size", 1)))
        root_item = self._create_wiztree_item(self._root_node, root_sz)
        self.wiztree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self.wiztree.setCurrentItem(root_item)

        self.wiztree.setSortingEnabled(True)
        self.wiztree.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self._apply_tree_filter()

    def _create_wiztree_item(
        self, node: dict[str, Any], parent_size: int
    ) -> _WizTreeWidgetItem:
        sz = int(node.get("size", 0))
        pct = (sz / max(1, parent_size)) * 100.0
        is_dir = bool(node.get("is_dir", True))
        proc_cnt = int(node.get("proc_count", 0))
        proc_names = node.get("proc_names") or []

        icon = "📁" if is_dir else "📄"
        if proc_cnt > 0:
            icon = f"⚡{icon}"
        name_text = f"{icon} {node.get('name', '')}"

        bar_text = _make_bar_text(pct)
        sz_text = format_bytes(sz)

        if proc_cnt > 0:
            preview = ", ".join(proc_names[:3])
            if len(proc_names) > 3:
                preview += f" (+{len(proc_names) - 3})"
            proc_text = f"⚡ {proc_cnt} проц.: {preview}"
        else:
            proc_text = "—"

        if is_dir:
            f_cnt = int(node.get("files_count", 0))
            d_cnt = int(node.get("dirs_count", 0))
            meta_text = f"{f_cnt} ф. / {d_cnt} пап."
            sort_count = f_cnt + d_cnt
        else:
            ext = Path(str(node.get("name", ""))).suffix.lower() or "файл"
            meta_text = f"Файл ({ext})"
            sort_count = 1

        mtime_text = format_timestamp(node.get("mtime")) if node.get("mtime") else "—"

        item = _WizTreeWidgetItem(
            [name_text, bar_text, sz_text, proc_text, meta_text, mtime_text]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, sz)
        item.setData(0, Qt.ItemDataRole.UserRole + 2, proc_cnt)
        item.setData(0, Qt.ItemDataRole.UserRole + 3, sort_count)

        item.setToolTip(0, str(node.get("path", "")))
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Цветовые акценты для размера и активных процессов
        if sz >= 1024 * 1024 * 1024:
            item.setForeground(2, QColor("#ff5c7c"))
        elif sz >= 100 * 1024 * 1024:
            item.setForeground(2, QColor("#ffb020"))
        else:
            item.setForeground(2, QColor("#e2e8f0"))

        if pct >= 50.0:
            item.setForeground(1, QColor("#ff5c7c"))
        elif pct >= 20.0:
            item.setForeground(1, QColor("#ffb020"))
        else:
            item.setForeground(1, QColor("#00d4ff"))

        if proc_cnt > 0:
            item.setForeground(0, QColor("#00f0ff"))
            item.setForeground(3, QColor("#00f0ff"))
            item.setToolTip(
                3,
                tr("В этой папке/файле работают процессы: {names}", names=", ".join(proc_names)),
            )
        else:
            item.setForeground(3, QColor("#64748b"))

        norm_path = os.path.normcase(os.path.normpath(str(node.get("path", ""))))
        if norm_path:
            self._path_to_tree_item[norm_path] = item

        children = node.get("children") or []
        child_base = max(1, sz)
        for child in children:
            child_item = self._create_wiztree_item(child, child_base)
            item.addChild(child_item)

        return item

    def refresh_active_processes_overlay(self) -> None:
        """Мгновенно обновить привязку живых процессов к уже построенному дереву WizTree."""
        self._active_processes = collect_active_processes_for_disk()
        if not self._root_node:
            return
        self._recompute_node_processes_recursive(self._root_node)
        selected_node = self._get_selected_wiztree_node()
        selected_path = selected_node.get("path") if selected_node else None
        self._populate_wiztree()
        if selected_path:
            norm = os.path.normcase(os.path.normpath(selected_path))
            item = self._path_to_tree_item.get(norm)
            if item:
                self.wiztree.setCurrentItem(item)
                self.wiztree.scrollToItem(item)
        self.status_message.emit(tr("Список активных процессов в папках WizTree обновлён"))

    def _recompute_node_processes_recursive(self, node: dict[str, Any]) -> None:
        path = str(node.get("path", ""))
        matched = find_processes_for_path(path, self._active_processes, check_restart_manager=False)
        node["proc_count"] = len(matched)
        node["proc_names"] = [str(p.get("name", "")) for p in matched[:6]]
        for child in node.get("children") or []:
            self._recompute_node_processes_recursive(child)

    def _apply_tree_filter(self) -> None:
        query = self.tree_search_edit.text().strip().lower()
        only_procs = self.only_procs_chk.isChecked()
        root_count = self.wiztree.topLevelItemCount()
        for i in range(root_count):
            top = self.wiztree.topLevelItem(i)
            if top:
                self._filter_tree_item_recursive(top, query, only_procs)

    def _filter_tree_item_recursive(
        self, item: QTreeWidgetItem, query: str, only_procs: bool
    ) -> bool:
        node = item.data(0, Qt.ItemDataRole.UserRole) or {}
        name = str(node.get("name", "")).lower()
        path = str(node.get("path", "")).lower()
        proc_names = " ".join(node.get("proc_names") or []).lower()
        proc_cnt = int(node.get("proc_count", 0))

        self_matches_query = (not query) or (query in name) or (query in path) or (query in proc_names)
        self_matches_procs = (not only_procs) or (proc_cnt > 0)
        self_match = self_matches_query and self_matches_procs

        any_child_visible = False
        for idx in range(item.childCount()):
            child = item.child(idx)
            if child and self._filter_tree_item_recursive(child, query, only_procs):
                any_child_visible = True

        visible = self_match or any_child_visible
        item.setHidden(not visible)
        if any_child_visible and (query or only_procs):
            item.setExpanded(True)
        return visible

    def _get_selected_wiztree_node(self) -> dict[str, Any] | None:
        items = self.wiztree.selectedItems()
        if not items:
            return self._root_node
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def _on_wiztree_selection_changed(self) -> None:
        node = self._get_selected_wiztree_node()
        if not node:
            self.current_node_lbl.setText(tr("Выбранный узел: —"))
            self.treemap.set_node(None)
            self._selected_node_procs = []
            self._render_selected_node_processes("")
            return

        path = str(node.get("path", ""))
        sz = int(node.get("size", 0))
        is_dir = bool(node.get("is_dir", True))
        self.current_node_lbl.setText(
            f"{'📁' if is_dir else '📄'} {path} — {format_bytes(sz)}"
        )

        # Если выбран файл, на карте Treemap показываем родительскую папку, а если папка — саму папку
        if is_dir and node.get("children"):
            self.treemap.set_node(node)
        else:
            items = self.wiztree.selectedItems()
            parent_item = items[0].parent() if items else None
            parent_node = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item else self._root_node
            self.treemap.set_node(parent_node or node)

        # Находим все процессы, связанные с этим путём
        self._selected_node_procs = find_processes_for_path(
            path, self._active_processes, check_restart_manager=False
        )
        self._render_selected_node_processes(path)

    def _check_selected_node_restart_manager(self) -> None:
        node = self._get_selected_wiztree_node()
        if not node:
            return
        path = str(node.get("path", ""))
        self._active_processes = collect_active_processes_for_disk()
        self._selected_node_procs = find_processes_for_path(
            path, self._active_processes, check_restart_manager=True
        )
        self._render_selected_node_processes(path, checked_rm=True)

    def _render_selected_node_processes(self, path: str, checked_rm: bool = False) -> None:
        procs = self._selected_node_procs
        if not path:
            self.proc_panel_sub.setText(tr("Выберите любую папку или файл в дереве WizTree слева."))
            self.node_procs_table.setRowCount(0)
            return

        if not procs:
            suffix = tr(" (включая проверку дескрипторов ядра Restart Manager)") if checked_rm else ""
            self.proc_panel_sub.setText(
                tr("🟢 В папке/файле «{name}» нет активных процессов{suffix} — объект свободен и может быть безопасно удалён.",
                   name=Path(path).name or path,
                   suffix=suffix)
            )
            self.node_procs_table.setRowCount(0)
            return

        self.proc_panel_sub.setText(
            tr(
                "⚡ Найдено активных процессов в «{name}»: {count}. "
                "Вы можете посмотреть, какой именно файл они вызывают, перейти к процессу или завершить его.",
                name=Path(path).name or path,
                count=len(procs),
            )
        )
        self.node_procs_table.setRowCount(len(procs))
        for r, p in enumerate(procs):
            pid = int(p.get("pid", 0))
            name = str(p.get("name", ""))
            proc_it = QTableWidgetItem(f"{name} (PID {pid})")
            proc_it.setForeground(QColor("#00f0ff"))
            proc_it.setToolTip(str(p.get("exe", "")))
            self.node_procs_table.setItem(r, 0, proc_it)

            reason_it = QTableWidgetItem(str(p.get("reason", "")))
            reason_it.setForeground(QColor("#ffb020"))
            self.node_procs_table.setItem(r, 1, reason_it)

            target_file = str(p.get("target_file", "") or p.get("exe", ""))
            tf_it = QTableWidgetItem(target_file)
            tf_it.setToolTip(target_file)
            self.node_procs_table.setItem(r, 2, tf_it)

            desc = str(p.get("description", ""))
            desc_it = QTableWidgetItem(desc)
            desc_it.setToolTip(str(p.get("details", "") or desc))
            self.node_procs_table.setItem(r, 3, desc_it)

            rss_it = QTableWidgetItem(format_bytes(int(p.get("rss", 0))))
            rss_it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.node_procs_table.setItem(r, 4, rss_it)

    def _on_wiztree_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        node = item.data(0, Qt.ItemDataRole.UserRole) or {}
        path = str(node.get("path", ""))
        if not node.get("is_dir", True) and path:
            open_in_explorer(path)

    def _on_treemap_node_clicked(self, child_node: dict[str, Any]) -> None:
        path = str(child_node.get("path", ""))
        if not path:
            return
        norm = os.path.normcase(os.path.normpath(path))
        item = self._path_to_tree_item.get(norm)
        if item:
            self.wiztree.setCurrentItem(item)
            item.setExpanded(True)
            self.wiztree.scrollToItem(item)

    def _open_selected_wiztree_in_explorer(self) -> None:
        node = self._get_selected_wiztree_node()
        if node and node.get("path"):
            open_in_explorer(str(node["path"]))

    def _jump_to_selected_node_process(self) -> None:
        r = self.node_procs_table.currentRow()
        if not (0 <= r < len(self._selected_node_procs)):
            if self._selected_node_procs:
                r = 0
            else:
                QMessageBox.information(
                    self,
                    tr("Переход к процессу"),
                    tr("В выбранной папке нет активных процессов или строка процесса не выбрана."),
                )
                return
        pid = int(self._selected_node_procs[r].get("pid", 0))
        if pid > 0:
            self.focus_process_requested.emit(pid)

    def _kill_selected_node_process(self) -> None:
        r = self.node_procs_table.currentRow()
        if not (0 <= r < len(self._selected_node_procs)):
            QMessageBox.information(
                self,
                tr("Завершение процесса"),
                tr("Выберите процесс в таблице справа, чтобы завершить его."),
            )
            return
        proc_info = self._selected_node_procs[r]
        pid = int(proc_info.get("pid", 0))
        name = str(proc_info.get("name", ""))
        if proc_info.get("safety") == "critical":
            QMessageBox.warning(
                self,
                tr("Защита системы"),
                tr("Процесс {name} (PID {pid}) является критическим системным процессом Windows и не может быть завершён.",
                   name=name, pid=pid),
            )
            return

        ans = QMessageBox.question(
            self,
            tr("Завершить процесс"),
            tr(
                "Принудительно завершить процесс {name} (PID {pid})?\n\n"
                "Связь с папкой: {reason}\nФайл: {file}",
                name=name,
                pid=pid,
                reason=proc_info.get("reason", ""),
                file=proc_info.get("target_file", ""),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        try:
            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=1.5)
            except psutil.TimeoutExpired:
                p.kill()
            self.status_message.emit(tr("Процесс {name} (PID {pid}) завершён", name=name, pid=pid))
            self.refresh_active_processes_overlay()
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("Ошибка завершения"),
                tr("Не удалось завершить {name} (PID {pid}): {err}", name=name, pid=pid, err=str(exc)),
            )

    # ------------------------------------------------------------------
    # Удаление узлов в WizTree: 1) В Корзину, 2) Навсегда с авто-завершением процессов
    # ------------------------------------------------------------------
    def _delete_selected_wiztree_to_trash(self) -> None:
        node = self._get_selected_wiztree_node()
        if not node or not node.get("path"):
            QMessageBox.information(self, tr("Удаление в Корзину"), tr("Выберите папку или файл в дереве WizTree."))
            return
        target_path = str(node["path"])
        if self._root_node and os.path.normcase(target_path) == os.path.normcase(str(self._root_node.get("path", ""))):
            QMessageBox.warning(
                self,
                tr("Защита корневой папки"),
                tr("Нельзя удалить саму корневую анализируемую папку целиком. Выберите подпапку или файл внутри неё."),
            )
            return

        safe, reason = is_safe_delete_path(target_path)
        if not safe:
            QMessageBox.warning(self, tr("Защита системы"), reason)
            return

        sz = int(node.get("size", 0))
        procs = find_processes_for_path(target_path, self._active_processes, check_restart_manager=False)
        proc_warn = ""
        if procs:
            p_names = ", ".join(f"{p['name']} (PID {p['pid']})" for p in procs[:5])
            proc_warn = tr(
                "\n\n⚠️ Внимание: в этой папке сейчас активны процессы ({count}): {names}.\n"
                "Если Windows не даст переместить занятые файлы в Корзину, используйте кнопку «🧨 Удалить навсегда (с авто-завершением процессов)».",
                count=len(procs),
                names=p_names,
            )

        ans = QMessageBox.question(
            self,
            tr("Отправить в Корзину Windows"),
            tr(
                "Переместить в Корзину выбранный объект?\n\n"
                "Путь: {path}\nОбъём: {size}{warn}",
                path=target_path,
                size=format_bytes(sz),
                warn=proc_warn,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        res = send_to_recycle_bin(target_path)
        if res.get("ok"):
            self._remove_selected_wiztree_item_after_delete(int(res.get("freed_bytes", sz)))
            msg = tr("Объект перемещён в Корзину: {path} ({size})", path=target_path, size=format_bytes(sz))
            self.status_lbl.setText(msg)
            self.status_message.emit(msg)
        else:
            QMessageBox.warning(
                self,
                tr("Не удалось переместить в Корзину"),
                tr(
                    "Ошибка при перемещении в Корзину: {err}\n\n"
                    "Попробуйте кнопку «🧨 Удалить навсегда (с авто-завершением процессов)».",
                    err=res.get("error", ""),
                ),
            )

    def _delete_selected_wiztree_permanently(self) -> None:
        node = self._get_selected_wiztree_node()
        if not node or not node.get("path"):
            QMessageBox.information(self, tr("Удаление навсегда"), tr("Выберите папку или файл в дереве WizTree."))
            return
        target_path = str(node["path"])
        if self._root_node and os.path.normcase(target_path) == os.path.normcase(str(self._root_node.get("path", ""))):
            QMessageBox.warning(
                self,
                tr("Защита корневой папки"),
                tr("Нельзя удалить саму корневую анализируемую папку целиком. Выберите подпапку или файл внутри неё."),
            )
            return

        safe, reason = is_safe_delete_path(target_path)
        if not safe:
            QMessageBox.warning(self, tr("Защита системы"), reason)
            return

        sz = int(node.get("size", 0))
        procs = find_processes_for_path(target_path, self._active_processes, check_restart_manager=True)
        proc_block = tr("Активных процессов в папке не обнаружено.")
        if procs:
            lines = [f"• {p['name']} (PID {p['pid']}) — {p['reason']}" for p in procs[:8]]
            proc_block = tr("Будут автоматически завершены следующие процессы ({count}):\n", count=len(procs)) + "\n".join(lines)

        ans = QMessageBox.warning(
            self,
            tr("Удалить навсегда (с авто-завершением процессов)"),
            tr(
                "Вы уверены, что хотите БЕЗВОЗВРАТНО удалить этот объект?\n\n"
                "Путь: {path}\n"
                "Объём: {size}\n\n"
                "{procs}",
                path=target_path,
                size=format_bytes(sz),
                procs=proc_block,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        res = terminate_processes_in_path_and_delete(target_path)
        if res.get("ok"):
            killed = res.get("killed_processes") or []
            freed = int(res.get("freed_bytes", sz))
            self._remove_selected_wiztree_item_after_delete(freed)
            self._active_processes = collect_active_processes_for_disk()
            msg = tr(
                "Удалено навсегда: {path} (освобождено {size}, завершено процессов: {killed})",
                path=target_path,
                size=format_bytes(freed),
                killed=len(killed),
            )
            self.status_lbl.setText(msg)
            self.status_message.emit(msg)
            QMessageBox.information(self, tr("Удаление выполнено"), msg)
        else:
            QMessageBox.warning(
                self,
                tr("Ошибка удаления"),
                tr("Не удалось полностью удалить объект: {err}", err=res.get("error", "")),
            )

    def _remove_selected_wiztree_item_after_delete(self, freed_bytes: int) -> None:
        items = self.wiztree.selectedItems()
        if not items:
            return
        item = items[0]
        node = item.data(0, Qt.ItemDataRole.UserRole) or {}
        norm_path = os.path.normcase(os.path.normpath(str(node.get("path", ""))))
        self._path_to_tree_item.pop(norm_path, None)

        parent = item.parent()
        if parent:
            parent_node = parent.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(parent_node, dict):
                parent_node["size"] = max(0, int(parent_node.get("size", 0)) - freed_bytes)
                children = parent_node.get("children") or []
                parent_node["children"] = [
                    c for c in children if os.path.normcase(str(c.get("path", ""))) != norm_path
                ]
                parent.setText(2, format_bytes(int(parent_node["size"])))
                parent.setData(0, Qt.ItemDataRole.UserRole + 1, int(parent_node["size"]))
            parent.removeChild(item)
            self.wiztree.setCurrentItem(parent)
        else:
            idx = self.wiztree.indexOfTopLevelItem(item)
            if idx >= 0:
                self.wiztree.takeTopLevelItem(idx)

    # ------------------------------------------------------------------
    # Топ-100 файлов и расширения
    # ------------------------------------------------------------------
    def _render_top_files(self, extensions: list[dict[str, Any]]) -> None:
        self.top_files_table.setRowCount(len(self._top_files))
        for r, item in enumerate(self._top_files):
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(Qt.CheckState.Unchecked)
            self.top_files_table.setItem(r, 0, chk)

            self.top_files_table.setItem(r, 1, QTableWidgetItem(str(item.get("name", ""))))
            sz_it = QTableWidgetItem(format_bytes(int(item.get("size", 0))))
            sz_it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sz_it.setForeground(QColor("#ffb020"))
            self.top_files_table.setItem(r, 2, sz_it)

            self.top_files_table.setItem(
                r, 3, QTableWidgetItem(format_timestamp(item.get("mtime")))
            )
            path_it = QTableWidgetItem(str(item.get("path", "")))
            path_it.setForeground(QColor("#8b9bb4"))
            self.top_files_table.setItem(r, 4, path_it)

        if extensions:
            self.ext_table.setRowCount(len(extensions))
            for r, ext in enumerate(extensions):
                self.ext_table.setItem(r, 0, QTableWidgetItem(str(ext.get("ext", ""))))
                sz_it = QTableWidgetItem(format_bytes(int(ext.get("size", 0))))
                sz_it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.ext_table.setItem(r, 1, sz_it)

                cnt_it = QTableWidgetItem(str(ext.get("count", 0)))
                cnt_it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.ext_table.setItem(r, 2, cnt_it)

                pct_it = QTableWidgetItem(f"{ext.get('pct', 0):.1f}%")
                pct_it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.ext_table.setItem(r, 3, pct_it)

    def _open_selected_top_file(self) -> None:
        r = self.top_files_table.currentRow()
        if 0 <= r < len(self._top_files):
            open_in_explorer(self._top_files[r]["path"])

    def _delete_checked_top_files(self, use_trash: bool = True) -> None:
        selected: list[dict[str, Any]] = []
        for r in range(min(self.top_files_table.rowCount(), len(self._top_files))):
            it = self.top_files_table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                selected.append(self._top_files[r])
        if not selected:
            QMessageBox.information(self, tr("Топ файлов"), tr("Отметьте галочками файлы для удаления."))
            return
        total_sz = sum(int(f["size"]) for f in selected)
        prompt = (
            tr("Отправить в Корзину выбранные крупные файлы ({count} шт., {size})?", count=len(selected), size=format_bytes(total_sz))
            if use_trash
            else tr("Безвозвратно удалить выбранные крупные файлы ({count} шт., {size})?", count=len(selected), size=format_bytes(total_sz))
        )
        ans = QMessageBox.warning(
            self,
            tr("Удаление крупных файлов"),
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        freed = 0
        deleted = 0
        for f in selected:
            res = (
                send_to_recycle_bin(f["path"])
                if use_trash
                else terminate_processes_in_path_and_delete(f["path"])
            )
            if res.get("ok"):
                freed += int(res.get("freed_bytes", 0))
                deleted += 1
        self._top_files = [f for f in self._top_files if os.path.exists(f["path"])]
        self._render_top_files([])
        msg = tr("Удалено файлов: {deleted}, освобождено {size}", deleted=deleted, size=format_bytes(freed))
        self.status_message.emit(msg)
        QMessageBox.information(self, tr("Удаление завершено"), msg)

    # ------------------------------------------------------------------
    # Поиск и удаление дубликатов
    # ------------------------------------------------------------------
    def start_duplicate_scan(self) -> None:
        if self._dup_worker and self._dup_worker.isRunning():
            return
        if self._analyze_worker and self._analyze_worker.isRunning():
            self._analyze_worker.cancel()
        folder = self.path_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, tr("Поиск дубликатов"), tr("Укажите существующую папку для поиска дубликатов."))
            return

        self._set_busy(True)
        self.tabs.setCurrentIndex(2)
        self.dup_table.setRowCount(0)
        # Для всего системного диска используем порог 512 КБ (чтобы не тратить время на сотни тысяч мелких служебных файлов),
        # а для конкретной папки — 64 КБ.
        norm_f = os.path.abspath(folder).rstrip("\\/")
        min_sz = 512 * 1024 if len(norm_f) <= 3 else 64 * 1024
        start_msg = tr("Поиск дубликатов файлов в {folder}…", folder=folder)
        self.status_lbl.setText(start_msg)
        self.dup_summary_lbl.setText(start_msg)

        self._dup_worker = _DuplicateScanWorker(folder, min_size_bytes=min_sz)
        self._dup_worker.progress.connect(self._on_dup_progress)
        self._dup_worker.finished_duplicates.connect(self._on_duplicates_finished)
        self._dup_worker.start()

    def _on_dup_progress(self, msg: str) -> None:
        self.status_lbl.setText(msg)
        self.dup_summary_lbl.setText(msg)

    def _on_duplicates_finished(self, payload: dict) -> None:
        self._refresh_busy_state()
        groups = payload.get("groups", [])
        self._dup_flat_rows = []
        for g in groups:
            for f in g.get("files", []):
                self._dup_flat_rows.append(
                    {
                        "hash": g["hash"],
                        "size": g["size"],
                        "path": f["path"],
                        "name": f["name"],
                        "is_original": f["is_original"],
                        "checked": f["checked"],
                    }
                )
        self._render_duplicates_table()
        wasted = int(payload.get("total_wasted_bytes", 0))
        g_cnt = int(payload.get("total_groups", 0))
        d_cnt = int(payload.get("total_duplicate_files", 0))
        msg = tr(
            "Найдено групп дубликатов: {groups} (лишних копий: {copies}, можно освободить: {wasted})",
            groups=g_cnt,
            copies=d_cnt,
            wasted=format_bytes(wasted),
        )
        self.dup_summary_lbl.setText(msg)
        self.status_lbl.setText(msg)
        self.status_message.emit(msg)

    def _render_duplicates_table(self) -> None:
        self.dup_table.setRowCount(len(self._dup_flat_rows))
        for r, row in enumerate(self._dup_flat_rows):
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(
                Qt.CheckState.Checked if row.get("checked") else Qt.CheckState.Unchecked
            )
            self.dup_table.setItem(r, 0, chk)

            is_orig = bool(row.get("is_original"))
            status_it = QTableWidgetItem(
                tr("🟢 Оригинал (сохранить)") if is_orig else tr("🟠 Копия (к удалению)")
            )
            status_it.setForeground(QColor("#42f59b" if is_orig else "#ffb020"))
            self.dup_table.setItem(r, 1, status_it)

            name_it = QTableWidgetItem(f"[{row['hash']}]  {row['name']}")
            name_it.setToolTip(str(row["path"]))
            self.dup_table.setItem(r, 2, name_it)

            sz_it = QTableWidgetItem(format_bytes(int(row["size"])))
            sz_it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.dup_table.setItem(r, 3, sz_it)

            path_it = QTableWidgetItem(str(row["path"]))
            path_it.setToolTip(str(row["path"]))
            path_it.setForeground(QColor("#8b9bb4"))
            self.dup_table.setItem(r, 4, path_it)

    def _dup_backup_log_path(self) -> Path:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PulseMonitor"
        base.mkdir(parents=True, exist_ok=True)
        return base / "deleted_duplicates_log.json"

    def _load_dup_backup_log(self) -> list[dict[str, Any]]:
        p = self._dup_backup_log_path()
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_dup_backup_log(self, entries: list[dict[str, Any]]) -> None:
        try:
            self._dup_backup_log_path().write_text(
                json.dumps(entries[-500:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _update_restore_dups_btn(self) -> None:
        if not hasattr(self, "restore_dups_btn"):
            return
        entries = self._load_dup_backup_log()
        restorable = [
            e
            for e in entries
            if e.get("deleted_path")
            and not os.path.exists(e["deleted_path"])
            and e.get("original_path")
            and os.path.exists(e["original_path"])
        ]
        self.restore_dups_btn.setEnabled(bool(restorable))
        if restorable:
            self.restore_dups_btn.setText(tr("⏪ Восстановить удалённые ({count})", count=len(restorable)))
        else:
            self.restore_dups_btn.setText(tr("⏪ Восстановить удалённые"))

    def _restore_deleted_duplicates(self) -> None:
        entries = self._load_dup_backup_log()
        restorable = [
            e
            for e in entries
            if e.get("deleted_path")
            and not os.path.exists(e["deleted_path"])
            and e.get("original_path")
            and os.path.exists(e["original_path"])
        ]
        if not restorable:
            QMessageBox.information(
                self,
                tr("Восстановление дубликатов"),
                tr("Нет удалённых копий, ожидающих восстановления."),
            )
            self._update_restore_dups_btn()
            return

        ans = QMessageBox.question(
            self,
            tr("Восстановление удалённых копий"),
            tr(
                "Восстановить {count} ранее удалённых копий на их прежние места из сохранённых оригиналов?",
                count=len(restorable),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        restored_cnt = 0
        for item in restorable:
            src = item["original_path"]
            dst = item["deleted_path"]
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                restored_cnt += 1
            except Exception:
                continue

        remaining = [
            e
            for e in entries
            if e.get("deleted_path") and not os.path.exists(e["deleted_path"])
        ]
        self._save_dup_backup_log(remaining)
        self._update_restore_dups_btn()
        msg = tr("Восстановлено файлов на прежние места: {count}", count=restored_cnt)
        self.dup_summary_lbl.setText(msg)
        self.status_message.emit(msg)
        QMessageBox.information(self, tr("Восстановление завершено"), msg)

    def _open_selected_dup(self) -> None:
        r = self.dup_table.currentRow()
        if 0 <= r < len(self._dup_flat_rows):
            open_in_explorer(self._dup_flat_rows[r]["path"])

    def _delete_checked_duplicates(self) -> None:
        by_hash_total: dict[str, int] = {}
        by_hash_checked: dict[str, int] = {}
        by_hash_surviving: dict[str, str] = {}
        to_delete: list[dict[str, Any]] = []

        for r, row in enumerate(self._dup_flat_rows):
            h = row["hash"]
            by_hash_total[h] = by_hash_total.get(h, 0) + 1
            it = self.dup_table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                by_hash_checked[h] = by_hash_checked.get(h, 0) + 1
                to_delete.append(row)
            else:
                if h not in by_hash_surviving and os.path.exists(row["path"]):
                    by_hash_surviving[h] = row["path"]

        if not to_delete:
            QMessageBox.information(
                self, tr("Удаление дубликатов"), tr("Отметьте копии файлов для удаления.")
            )
            return

        for h, chk_cnt in by_hash_checked.items():
            if chk_cnt >= by_hash_total.get(h, 0):
                QMessageBox.warning(
                    self,
                    tr("Защита оригинала"),
                    tr(
                        "В группе [{hash}] отмечены ВСЕ экземпляры файла. "
                        "Снимите галочку хотя бы с одного оригинала!",
                        hash=h,
                    ),
                )
                return

        total_sz = sum(int(x["size"]) for x in to_delete)
        ans = QMessageBox.question(
            self,
            tr("Подтверждение удаления дубликатов"),
            tr(
                "Отправить выбранные копии ({count} шт., {size}) в Корзину Windows?\n"
                "Оригиналы останутся нетронутыми, а копии можно вернуть в 1 клик кнопкой «⏪ Восстановить удалённые».",
                count=len(to_delete),
                size=format_bytes(total_sz),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        freed = 0
        deleted = 0
        backup_entries = self._load_dup_backup_log()
        for row in to_delete:
            res = send_to_recycle_bin(row["path"])
            if res.get("ok"):
                freed += int(res.get("freed_bytes", 0))
                deleted += 1
                orig_surviving = by_hash_surviving.get(row["hash"], "")
                if orig_surviving:
                    backup_entries.append(
                        {
                            "deleted_path": row["path"],
                            "original_path": orig_surviving,
                            "hash": row["hash"],
                            "size": int(row["size"]),
                            "ts": time.time(),
                        }
                    )

        self._save_dup_backup_log(backup_entries)
        self._update_restore_dups_btn()
        self._dup_flat_rows = [r for r in self._dup_flat_rows if os.path.exists(r["path"])]
        self._render_duplicates_table()
        msg = tr(
            "Удалено дубликатов в Корзину: {deleted}, освобождено: {size}",
            deleted=deleted,
            size=format_bytes(freed),
        )
        self.dup_summary_lbl.setText(msg)
        self.status_message.emit(msg)
        QMessageBox.information(self, tr("Дубликаты удалены"), msg)
