"""Главное окно Pulse Monitor."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core.autorun_manager import AutorunManager
from core.config_manager import config
from core.net_collector import NetworkCollector
from core.process_collector import ProcessCollector
from core.system_stats import collect_system_stats
from core.utils import is_admin, relaunch_as_admin
from core.workers import CollectorThread, stop_all
from ui.theme import apply_theme, create_app_icon
from ui.widgets.autorun_view import AutorunView
from ui.widgets.dashboard_view import DashboardView
from ui.widgets.network_view import NetworkView
from ui.widgets.process_view import ProcessView
from ui.widgets.settings_dialog import SettingsDialog

PAGES = [
    ("Обзор", "Сводка по системе, графики и топ процессов"),
    ("Процессы", "Все процессы, включая скрытые и фоновые"),
    ("Сеть", "Скорость интерфейсов и соединения процессов"),
    ("Автозагрузка", "Реестр, папка «Автозагрузка» и службы"),
]

APP_TITLE = "Pulse Monitor"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} — мониторинг системы")
        self.setWindowIcon(create_app_icon(64))
        self.setMinimumSize(1080, 680)

        self.process_collector = ProcessCollector()
        self.network_collector = NetworkCollector()
        self.autorun_manager = AutorunManager()
        self._threads: list[CollectorThread] = []
        self._tray_message_shown = False
        self._current_page = 0

        self._build_ui()
        self._build_tray()
        self._restore_geometry()
        self._start_workers()
        self._setup_shortcuts()

        QTimer.singleShot(250, self.autorun_view.refresh_now)
        QTimer.singleShot(250, self.process_view.refresh_now)
        QTimer.singleShot(450, self.network_view.refresh_now)
        QTimer.singleShot(0, self._on_page_changed)

        if config.get("behavior.start_minimized", False):
            QTimer.singleShot(600, self._hide_to_tray)

    # ------------------------------------------------------------------
    # Интерфейс
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 14, 18, 8)
        body_layout.setSpacing(10)

        self.stack = QStackedWidget()
        self.dashboard_view = DashboardView(self.process_collector)
        self.process_view = ProcessView(self.process_collector)
        self.network_view = NetworkView(self.network_collector, self.process_collector)
        self.autorun_view = AutorunView(self.autorun_manager)
        self.views = [
            self.dashboard_view,
            self.process_view,
            self.network_view,
            self.autorun_view,
        ]
        for view in self.views:
            self.stack.addWidget(view)
            if hasattr(view, "status_message"):
                view.status_message.connect(self._show_status)
        body_layout.addWidget(self.stack, 1)
        content_layout.addWidget(body, 1)
        layout.addWidget(content, 1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self._status_label = QLabel("Готово")
        self._status_label.setObjectName("Muted")
        self.statusBar().addWidget(self._status_label, 1)
        self.version_label = QLabel("v1.0 · psutil")
        self.version_label.setObjectName("Muted")
        self.statusBar().addPermanentWidget(self.version_label)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        logo = QLabel("PULSE")
        logo.setObjectName("Logo")
        sub = QLabel("MONITOR · все процессы")
        sub.setObjectName("LogoSub")
        layout.addWidget(logo)
        layout.addWidget(sub)
        layout.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        icons = ["◉  Обзор", "▤  Процессы", "⇅  Сеть", "⏻  Автозагрузка"]
        for index, (title, _subtitle) in enumerate(PAGES):
            button = QPushButton(icons[index])
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(title)
            button.clicked.connect(lambda _checked, page=index: self.set_page(page))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)

        layout.addStretch(1)

        self.theme_button = QPushButton()
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_button)

        self.settings_button = QPushButton("⚙  Настройки")
        self.settings_button.setObjectName("NavButton")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)

        self.admin_label = QLabel()
        self.admin_label.setWordWrap(True)
        self.admin_label.setObjectName("Muted")
        layout.addWidget(self.admin_label)

        self.elevate_button = QPushButton("Запустить от администратора")
        self.elevate_button.clicked.connect(self._elevate)
        layout.addWidget(self.elevate_button)
        self._update_admin_state()

        version = QLabel("Pulse Monitor 1.0")
        version.setObjectName("LogoSub")
        layout.addWidget(version)
        self._update_theme_button()
        return sidebar

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(74)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 12, 18, 12)
        layout.setSpacing(10)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.header_title = QLabel(PAGES[0][0])
        self.header_title.setObjectName("PageTitle")
        self.header_subtitle = QLabel(PAGES[0][1])
        self.header_subtitle.setObjectName("PageSubtitle")
        texts.addWidget(self.header_title)
        texts.addWidget(self.header_subtitle)
        layout.addLayout(texts)
        layout.addStretch(1)

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh_current)
        layout.addWidget(self.refresh_button)

        settings_action = QPushButton("Настройки")
        settings_action.setObjectName("PrimaryButton")
        settings_action.clicked.connect(self.open_settings)
        layout.addWidget(settings_action)
        return header

    # ------------------------------------------------------------------
    # Трей и потоки
    # ------------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.windowIcon(), self)
        tray.setToolTip(f"{APP_TITLE} — мониторинг системы")
        menu = QMenu()
        show_action = menu.addAction("Показать окно")
        show_action.triggered.connect(self._show_window)
        menu.addSeparator()
        for index, (title, _subtitle) in enumerate(PAGES):
            action = menu.addAction(title)
            action.triggered.connect(
                lambda _checked=False, page=index: self._show_page(page)
            )
        menu.addSeparator()
        settings_action = menu.addAction("Настройки…")
        settings_action.triggered.connect(self.open_settings)
        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(self.quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self.tray = tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_window()

    def _hide_to_tray(self) -> None:
        if self.tray is None:
            self.showMinimized()
            return
        self.hide()
        if not self._tray_message_shown:
            self.tray.showMessage(
                APP_TITLE,
                "Приложение продолжает работать в фоне. "
                "Двойной клик по иконке — открыть.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            self._tray_message_shown = True

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_page(self, index: int) -> None:
        self._show_window()
        self.set_page(index)

    def _start_workers(self) -> None:
        self._process_thread = CollectorThread(
            "Процессы",
            self.process_collector.snapshot,
            lambda: int(config.get("intervals.processes", 2000)),
            lambda: self._is_page_active(1),
        )
        self._process_thread.data_ready.connect(self._on_processes)
        self._process_thread.failed.connect(self._on_worker_error)

        self._network_thread = CollectorThread(
            "Сеть",
            self.network_collector.snapshot,
            lambda: int(config.get("intervals.network", 2500)),
            lambda: self._is_page_active(2),
        )
        self._network_thread.data_ready.connect(self._on_network)
        self._network_thread.failed.connect(self._on_worker_error)

        self._system_thread = CollectorThread(
            "Обзор",
            collect_system_stats,
            lambda: int(config.get("intervals.dashboard", 1200)),
            lambda: self._is_page_active(0),
        )
        self._system_thread.data_ready.connect(self.dashboard_view.set_system_snapshot)
        self._system_thread.failed.connect(self._on_worker_error)

        for thread in (self._process_thread, self._network_thread, self._system_thread):
            self._threads.append(thread)
            thread.start()

    def _is_page_active(self, page: int) -> bool:
        if not config.get("behavior.slow_when_inactive", True):
            return True
        return (
            self.isVisible() and not self.isMinimized() and self._current_page == page
        )

    def _on_processes(self, payload: dict) -> None:
        self.process_view.set_snapshot(payload)
        self.dashboard_view.set_process_snapshot(payload)
        stats = payload.get("stats", {})
        self._status_label.setText(
            f"Процессов: {stats.get('total', 0)} · скрытых: {stats.get('hidden', 0)} · "
            f"подозрительных: {stats.get('suspicious', 0)} · "
            f"опрос: {stats.get('elapsed_ms', 0):.0f} мс"
        )

    def _on_network(self, payload: dict) -> None:
        self.network_view.set_snapshot(payload)
        self.dashboard_view.set_network_snapshot(payload)

    def _on_worker_error(self, message: str) -> None:
        self._show_status(f"Ошибка мониторинга — {message}")

    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    # ------------------------------------------------------------------
    # Навигация
    # ------------------------------------------------------------------
    def set_page(self, index: int) -> None:
        index = max(0, min(index, len(PAGES) - 1))
        self._current_page = index
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        title, subtitle = PAGES[index]
        self.header_title.setText(title)
        self.header_subtitle.setText(subtitle)
        self._on_page_changed()

    def _on_page_changed(self) -> None:
        for index, view in enumerate(self.views):
            if hasattr(view, "set_active"):
                view.set_active(index == self._current_page)
        if self._current_page == 0:
            self.dashboard_view.set_active(True)
            self.process_view.set_active(False)
        view = self.views[self._current_page]
        if self._current_page == 3:
            if not self.autorun_view._entries:
                self.autorun_view.refresh_now()
        elif hasattr(view, "refresh_now"):
            view.refresh_now()

    def refresh_current(self) -> None:
        if self._current_page == 0:
            try:
                self.dashboard_view.set_system_snapshot(collect_system_stats())
            except Exception:
                pass
            self.process_view.refresh_now()
        elif self._current_page == 1:
            self.process_view.refresh_now()
        elif self._current_page == 2:
            self.network_view.refresh_now()
        else:
            self.autorun_view.refresh_now()

    # ------------------------------------------------------------------
    # Настройки, тема, права
    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if not dialog.exec():
            return
        self._apply_theme()
        self._update_theme_button()
        accent = str(config.get("accent", "#00f0ff"))
        self.dashboard_view.apply_settings(accent)
        self.network_view.apply_settings(accent)
        self.process_view.apply_settings()
        self._update_admin_state()
        self._show_status("Настройки сохранены")

    def _apply_theme(self) -> None:
        apply_theme(
            QApplication.instance(),
            str(config.get("theme", "dark")),
            str(config.get("accent", "#00f0ff")),
            int(config.get("font_size", 13)),
        )

    def _toggle_theme(self) -> None:
        current = str(config.get("theme", "dark"))
        config.set("theme", "light" if current == "dark" else "dark")
        self._apply_theme()
        self._update_theme_button()
        accent = str(config.get("accent", "#00f0ff"))
        self.dashboard_view.apply_settings(accent)
        self.network_view.apply_settings(accent)

    def _update_theme_button(self) -> None:
        theme = str(config.get("theme", "dark"))
        self.theme_button.setText(
            "☀  Светлая тема" if theme == "dark" else "☾  Тёмная тема"
        )

    def _update_admin_state(self) -> None:
        if is_admin():
            self.admin_label.setText("✓ Права администратора")
            self.elevate_button.hide()
        else:
            self.admin_label.setText(
                "Ограниченный доступ: часть системных данных и путей скрыта"
            )
            self.elevate_button.show()

    def _elevate(self) -> None:
        if relaunch_as_admin():
            self._shutdown()
            QApplication.quit()
        else:
            QMessageBox.warning(
                self, "Права администратора", "Не удалось перезапустить приложение."
            )

    # ------------------------------------------------------------------
    # Геометрия, закрытие, горячие клавиши
    # ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        width = int(config.get("window.width", 1320))
        height = int(config.get("window.height", 840))
        x = config.get("window.x")
        y = config.get("window.y")
        if x is None or y is None:
            screen = QApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                x = available.x() + max(0, (available.width() - width) // 2)
                y = available.y() + max(0, (available.height() - height) // 2)
            else:
                x, y = 80, 60
        self.setGeometry(int(x), int(y), width, height)
        if config.get("window.maximized", False):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        last_page = int(config.get("window.last_page", 0))
        if 0 <= last_page < len(PAGES):
            self.set_page(last_page)

    def _save_geometry(self) -> None:
        config.set("window.last_page", self._current_page, save=False)
        if config.get("behavior.remember_geometry", True):
            geometry = self.normalGeometry()
            config.update(
                {
                    "window": {
                        "width": geometry.width(),
                        "height": geometry.height(),
                        "x": geometry.x(),
                        "y": geometry.y(),
                        "maximized": self.isMaximized(),
                        "last_page": self._current_page,
                    }
                }
            )
        else:
            config.save()

    def _setup_shortcuts(self) -> None:
        bindings = {
            "F5": self.refresh_current,
            "Ctrl+F": lambda: self.process_view.search.setFocus(),
            "Ctrl+,": self.open_settings,
            "Ctrl+Q": self.quit_app,
            "Ctrl+1": lambda: self.set_page(0),
            "Ctrl+2": lambda: self.set_page(1),
            "Ctrl+3": lambda: self.set_page(2),
            "Ctrl+4": lambda: self.set_page(3),
        }
        for sequence, handler in bindings.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(handler)

    def _shutdown(self) -> None:
        self._save_geometry()
        stop_all(self._threads)
        if self.tray is not None:
            self.tray.hide()

    def quit_app(self) -> None:
        self._shutdown()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.tray is not None and config.get("behavior.close_to_tray", True):
            event.ignore()
            self._hide_to_tray()
            return
        self._shutdown()
        event.accept()
        QApplication.quit()




