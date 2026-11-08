"""Регистрация пункта «Разблокировать / Завершить процесс» в меню Проводника.

Ключи пишутся в ``HKEY_CURRENT_USER\\Software\\Classes`` — это ветка текущего
пользователя, поэтому права администратора не нужны:

* ``*\\shell\\PulseUnlocker`` — пункт для файлов;
* ``Directory\\shell\\PulseUnlocker`` — пункт для папок.

Команда запускает приложение с флагом ``--unlock "%1"``. При выделении
нескольких файлов Проводник запускает отдельный экземпляр на каждый файл —
для разблокировки это допустимо и не требует IPC.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - проект рассчитан на Windows
    winreg = None  # type: ignore[assignment]

from core.i18n import tr

MENU_KEY_NAME = "PulseUnlocker"
MENU_TITLE = "Разблокировать / Завершить процесс (Pulse Monitor)"
# Области Проводника: любые файлы и любые папки.
REGISTRY_SCOPES = ("*", "Directory")
UNLOCK_FLAG = "--unlock"

_SHCNE_ASSOCCHANGED = 0x08000000
_SHCNF_IDLIST = 0x0000


def _key_path(scope: str) -> str:
    return rf"Software\Classes\{scope}\shell\{MENU_KEY_NAME}"


def _launcher() -> tuple[str, str]:
    """(исполняемый файл, аргументы до флага --unlock) для команды меню."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    executable = Path(sys.executable)
    # Из исходников запускаем pythonw.exe: без мигающего консольного окна.
    windowed = executable.with_name("pythonw.exe")
    if windowed.exists():
        executable = windowed
    script = Path(__file__).resolve().parents[1] / "main.py"
    return str(executable), f'"{script}"'


def context_menu_command() -> str:
    """Полная команда, которую выполнит Проводник (``%1`` — путь)."""
    executable, arguments = _launcher()
    prefix = f'"{executable}"'
    if arguments:
        prefix = f"{prefix} {arguments}"
    return f'{prefix} {UNLOCK_FLAG} "%1"'


def context_menu_icon() -> str:
    """Иконка пункта меню: иконка EXE в сборке, ``assets/pulse.ico`` иначе."""
    if getattr(sys, "frozen", False):
        return sys.executable
    icon = Path(__file__).resolve().parents[1] / "assets" / "pulse.ico"
    return str(icon) if icon.is_file() else sys.executable


def _notify_shell() -> None:
    """Сообщить Проводнику, что ассоциации изменились."""
    try:
        ctypes.windll.shell32.SHChangeNotify(
            _SHCNE_ASSOCCHANGED, _SHCNF_IDLIST, None, None
        )
    except Exception:
        pass


def _write_scope(scope: str, title: str, command: str, icon: str) -> bool:
    if winreg is None:
        return False
    path = _key_path(scope)
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, title)
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon)
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, path + r"\command", 0, winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
        return True
    except OSError:
        return False


def register_context_menu() -> bool:
    """Добавить пункт в контекстное меню файлов и папок (HKCU)."""
    if winreg is None or os.name != "nt":
        return False
    title = tr(MENU_TITLE)
    command = context_menu_command()
    icon = context_menu_icon()
    ok = True
    for scope in REGISTRY_SCOPES:
        ok = _write_scope(scope, title, command, icon) and ok
    _notify_shell()
    return ok


def _delete_key(path: str) -> bool:
    if winreg is None:
        return False
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def unregister_context_menu() -> bool:
    """Удалить пункт из контекстного меню файлов и папок."""
    if winreg is None or os.name != "nt":
        return False
    ok = True
    for scope in REGISTRY_SCOPES:
        path = _key_path(scope)
        ok = _delete_key(path + r"\command") and ok
        ok = _delete_key(path) and ok
    _notify_shell()
    return ok


def context_menu_registered() -> bool:
    """Зарегистрирован ли пункт меню (проверяется команда в реестре)."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _key_path("*") + r"\command",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "")
        return bool(value)
    except OSError:
        return False
