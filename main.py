"""Pulse Monitor — лёгкий мониторинг процессов, сети и автозагрузки Windows."""

from __future__ import annotations

import sys
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox, QStyleFactory

from core.config_manager import CONFIG_DIR, config
from ui.main_window import MainWindow
from ui.theme import apply_theme, create_app_icon


def _exception_hook(exc_type, exc_value, exc_traceback) -> None:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG_DIR / "error.log").write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        QMessageBox.critical(
            None, "Pulse Monitor — ошибка", text[-3500:] or "Неизвестная ошибка"
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "PulseMonitor.1.0"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Pulse Monitor")
    app.setApplicationDisplayName("Pulse Monitor")
    app.setOrganizationName("PulseMonitor")
    app.setApplicationVersion("1.0.0")
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setWindowIcon(create_app_icon(128))
    apply_theme(
        app,
        str(config.get("theme", "dark")),
        str(config.get("accent", "#00f0ff")),
        int(config.get("font_size", 13)),
    )
    sys.excepthook = _exception_hook

    window = MainWindow()
    start_minimized = bool(config.get("behavior.start_minimized", False))
    if not (start_minimized and window.tray is not None):
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
