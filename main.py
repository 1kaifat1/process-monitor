"""Pulse Monitor — лёгкий мониторинг процессов, сети и автозагрузки Windows."""

from __future__ import annotations

import sys
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox, QStyleFactory

from core.app_identity import prepare_shell_identity
from core.config_manager import CONFIG_DIR, config
from core.i18n import apply_config_language, tr
from core.single_instance import SingleInstance
from core.utils import REPLACE_INSTANCE_FLAG
from ui.main_window import MainWindow
from ui.theme import apply_theme, load_app_icon
from ui.widgets.unlock_dialog import UnlockDialog

UNLOCK_FLAG = "--unlock"


def _exception_hook(exc_type, exc_value, exc_traceback) -> None:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG_DIR / "error.log").write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        QMessageBox.critical(
            None,
            tr("Pulse Monitor — ошибка"),
            text[-3500:] or tr("Неизвестная ошибка"),
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _unlock_paths(argv: list[str]) -> list[str]:
    """Пути, переданные после ``--unlock`` (Проводник передаёт один)."""
    try:
        index = argv.index(UNLOCK_FLAG)
    except ValueError:
        return []
    paths: list[str] = []
    for argument in argv[index + 1 :]:
        if argument.startswith("--"):
            break
        path = argument.strip().strip('"')
        if path:
            paths.append(path)
    return paths


def main() -> int:
    unlock_paths = _unlock_paths(sys.argv)
    if sys.platform == "win32" and not unlock_paths:
        # AUMID + ярлык в меню «Пуск»: иначе панель задач берёт иконку
        # исполняемого файла (для запуска из исходников — pythonw.exe).
        # Для компактного диалога разблокировки это не нужно.
        prepare_shell_identity()

    app = QApplication(sys.argv)
    app.setApplicationName("Pulse Monitor")
    app.setApplicationDisplayName("Pulse Monitor")
    app.setOrganizationName("PulseMonitor")
    app.setApplicationVersion("1.0.0")
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setWindowIcon(load_app_icon(128))
    apply_config_language()
    apply_theme(
        app,
        str(config.get("theme", "dark")),
        str(config.get("accent", "#00f0ff")),
        int(config.get("font_size", 13)),
    )
    sys.excepthook = _exception_hook

    if unlock_paths:
        # Режим разблокировки: без главного окна, single-instance и трея.
        for path in unlock_paths:
            UnlockDialog(path).exec()
        return 0

    single = SingleInstance()
    replace_instance = REPLACE_INSTANCE_FLAG in sys.argv
    if not replace_instance and single.notify_existing():
        # Приложение уже работает (возможно, в трее) — окно показал он.
        return 0

    window = MainWindow()
    app._pulse_window = window  # type: ignore[attr-defined]
    single.show_requested.connect(
        lambda: getattr(app, "_pulse_window", window).present()
    )
    single.listen(takeover=replace_instance)

    start_minimized = bool(config.get("behavior.start_minimized", False))
    if not (start_minimized and window.tray is not None):
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
