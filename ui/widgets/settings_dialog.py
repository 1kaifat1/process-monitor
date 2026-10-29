"""Диалог настроек: темы, интервалы, столбцы, поведение, автозапуск."""

from __future__ import annotations

import sys

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import PROCESS_COLUMNS, config
from core.winapi import autostart_enabled, set_autostart


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки Pulse Monitor")
        self.setMinimumSize(680, 580)
        self.resize(720, 620)
        self._accent = str(config.get("accent", "#00f0ff"))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("Настройки")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self._build_appearance_tab()
        self._build_intervals_tab()
        self._build_processes_tab()
        self._build_behavior_tab()
        self._build_buttons(root)
        self._load_from_config()

    # ------------------------------------------------------------------
    # Вкладки
    # ------------------------------------------------------------------
    def _build_appearance_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Тёмная", "dark")
        self.theme_combo.addItem("Светлая", "light")
        form.addRow("Тема оформления:", self.theme_combo)

        accent_row = QHBoxLayout()
        self.accent_button = QPushButton("Выбрать цвет…")
        self.accent_button.clicked.connect(self._pick_accent)
        self.accent_preview = QLabel()
        self.accent_preview.setFixedSize(54, 26)
        self.accent_label = QLabel(self._accent)
        self.accent_label.setObjectName("Muted")
        accent_row.addWidget(self.accent_preview)
        accent_row.addWidget(self.accent_button)
        accent_row.addWidget(self.accent_label)
        accent_row.addStretch(1)
        accent_widget = QWidget()
        accent_widget.setLayout(accent_row)
        form.addRow("Акцентный цвет:", accent_widget)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 18)
        self.font_spin.setSuffix(" px")
        form.addRow("Размер шрифта:", self.font_spin)
        layout.addLayout(form)

        hint = QLabel(
            "Тема и акцент применяются ко всем элементам: таблицам, графикам, "
            "кнопкам, меню и боковой панели."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        self.tabs.addTab(page, "Внешний вид")

    def _build_intervals_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.interval_processes = QSpinBox()
        self.interval_processes.setRange(300, 20000)
        self.interval_processes.setSingleStep(100)
        self.interval_processes.setSuffix(" мс")
        form.addRow("Процессы:", self.interval_processes)

        self.interval_network = QSpinBox()
        self.interval_network.setRange(300, 20000)
        self.interval_network.setSingleStep(100)
        self.interval_network.setSuffix(" мс")
        form.addRow("Сеть:", self.interval_network)

        self.interval_dashboard = QSpinBox()
        self.interval_dashboard.setRange(300, 20000)
        self.interval_dashboard.setSingleStep(100)
        self.interval_dashboard.setSuffix(" мс")
        form.addRow("Обзор (графики):", self.interval_dashboard)
        layout.addLayout(form)

        hint = QLabel(
            "Чем больше интервал, тем ниже нагрузка. При неактивной вкладке "
            "опрос автоматически замедляется в 3 раза. Рекомендуемые значения: "
            "2000 мс для процессов и сети, 1200 мс для обзора."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.tabs.addTab(page, "Обновление")

    def _build_processes_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.show_system_check = QCheckBox("Показывать системные процессы и службы")
        self.confirm_kill_check = QCheckBox("Спрашивать подтверждение перед завершением")
        layout.addWidget(self.show_system_check)
        layout.addWidget(self.confirm_kill_check)

        columns_group = QGroupBox("Отображаемые столбцы")
        group_layout = QVBoxLayout(columns_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        self.column_checks: dict[str, QCheckBox] = {}
        for index, (key, title, _width, _default) in enumerate(PROCESS_COLUMNS):
            checkbox = QCheckBox(title)
            self.column_checks[key] = checkbox
            grid.addWidget(checkbox, index // 3, index % 3)
        scroll.setWidget(inner)
        group_layout.addWidget(scroll)
        layout.addWidget(columns_group, 1)

        self.tabs.addTab(page, "Процессы")

    def _build_behavior_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.close_to_tray_check = QCheckBox(
            "Скрывать окно в трей при закрытии (работа в фоне)"
        )
        self.start_minimized_check = QCheckBox("Запускать свёрнутым в трей")
        self.autostart_check = QCheckBox("Добавить Pulse Monitor в автозапуск Windows")
        self.remember_geometry_check = QCheckBox("Запоминать размер и положение окна")
        self.slow_inactive_check = QCheckBox(
            "Снижать частоту опроса, когда вкладка неактивна"
        )
        for checkbox in (
            self.close_to_tray_check,
            self.start_minimized_check,
            self.autostart_check,
            self.remember_geometry_check,
            self.slow_inactive_check,
        ):
            layout.addWidget(checkbox)

        hint = QLabel(
            "Фоновый режим использует те же потоки опроса. Без прав администратора "
            "часть системных данных и путей процессов будет недоступна."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.tabs.addTab(page, "Поведение")

    def _build_buttons(self, root: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.reset_button = QPushButton("Сбросить всё")
        self.export_button = QPushButton("Экспорт…")
        self.import_button = QPushButton("Импорт…")
        self.cancel_button = QPushButton("Отмена")
        self.save_button = QPushButton("Сохранить")
        self.save_button.setObjectName("PrimaryButton")
        row.addWidget(self.reset_button)
        row.addWidget(self.export_button)
        row.addWidget(self.import_button)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.save_button)
        root.addLayout(row)

        self.reset_button.clicked.connect(self._reset)
        self.export_button.clicked.connect(self._export)
        self.import_button.clicked.connect(self._import)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)

    # ------------------------------------------------------------------
    # Значения
    # ------------------------------------------------------------------
    def _update_accent_preview(self) -> None:
        self.accent_preview.setStyleSheet(
            f"background: {self._accent}; border-radius: 6px; "
            "border: 1px solid rgba(255,255,255,0.25);"
        )
        self.accent_label.setText(self._accent)

    def _pick_accent(self) -> None:
        color = QColorDialog.getColor(QColor(self._accent), self, "Акцентный цвет")
        if color.isValid():
            self._accent = color.name()
            self._update_accent_preview()

    def _load_from_config(self) -> None:
        theme_index = self.theme_combo.findData(config.get("theme", "dark"))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self._accent = str(config.get("accent", "#00f0ff"))
        self._update_accent_preview()
        self.font_spin.setValue(int(config.get("font_size", 13)))
        self.interval_processes.setValue(int(config.get("intervals.processes", 2000)))
        self.interval_network.setValue(int(config.get("intervals.network", 2500)))
        self.interval_dashboard.setValue(int(config.get("intervals.dashboard", 1200)))
        for key, checkbox in self.column_checks.items():
            checkbox.setChecked(bool(config.get(f"processes.columns.{key}", True)))
        self.show_system_check.setChecked(
            bool(config.get("processes.show_system", True))
        )
        self.confirm_kill_check.setChecked(
            bool(config.get("processes.confirm_kill", True))
        )
        self.close_to_tray_check.setChecked(
            bool(config.get("behavior.close_to_tray", True))
        )
        self.start_minimized_check.setChecked(
            bool(config.get("behavior.start_minimized", False))
        )
        self.remember_geometry_check.setChecked(
            bool(config.get("behavior.remember_geometry", True))
        )
        self.slow_inactive_check.setChecked(
            bool(config.get("behavior.slow_when_inactive", True))
        )
        self.autostart_check.setChecked(autostart_enabled())

    def _save(self) -> None:
        if not any(checkbox.isChecked() for checkbox in self.column_checks.values()):
            QMessageBox.warning(
                self,
                "Столбцы",
                "Должен быть выбран хотя бы один отображаемый столбец.",
            )
            return

        autostart = self.autostart_check.isChecked()
        values = {
            "theme": self.theme_combo.currentData() or "dark",
            "accent": self._accent,
            "font_size": self.font_spin.value(),
            "intervals": {
                "processes": self.interval_processes.value(),
                "network": self.interval_network.value(),
                "dashboard": self.interval_dashboard.value(),
            },
            "processes": {
                "columns": {
                    key: checkbox.isChecked()
                    for key, checkbox in self.column_checks.items()
                },
                "show_system": self.show_system_check.isChecked(),
                "confirm_kill": self.confirm_kill_check.isChecked(),
            },
            "behavior": {
                "close_to_tray": self.close_to_tray_check.isChecked(),
                "start_minimized": self.start_minimized_check.isChecked(),
                "autostart_app": autostart,
                "remember_geometry": self.remember_geometry_check.isChecked(),
                "slow_when_inactive": self.slow_inactive_check.isChecked(),
            },
        }
        config.update(values)

        try:
            from pathlib import Path

            if getattr(sys, "frozen", False):
                script = None
                executable = sys.executable
            else:
                script = str(Path(sys.argv[0]).resolve()) if sys.argv else None
                executable = sys.executable
                # Для фонового автозапуска нужен pythonw.exe (без консоли).
                pythonw = Path(executable).with_name("pythonw.exe")
                if pythonw.exists():
                    executable = str(pythonw)
            if not set_autostart(executable, script, autostart):
                QMessageBox.warning(
                    self,
                    "Автозапуск",
                    "Не удалось изменить автозапуск Windows. "
                    "Проверьте права доступа к реестру.",
                )
        except Exception:
            pass
        self.accept()

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "Сброс настроек",
            "Вернуть все настройки к значениям по умолчанию?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        config.reset()
        self._load_from_config()
        self.accept()

    def _export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Экспорт настроек", "pulse-monitor-settings.json", "JSON (*.json)"
        )
        if path and not config.export_to(path):
            QMessageBox.warning(self, "Экспорт", "Не удалось сохранить настройки")

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Импорт настроек", "", "JSON (*.json)"
        )
        if not path:
            return
        if config.import_from(path):
            self._load_from_config()
            QMessageBox.information(
                self, "Импорт", "Настройки загружены. Нажмите «Сохранить»."
            )
        else:
            QMessageBox.warning(self, "Импорт", "Не удалось прочитать файл настроек")


