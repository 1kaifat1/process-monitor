"""Идентификация приложения в оболочке Windows (AUMID и ярлык в меню «Пуск»).

Панель задач Windows берёт иконку кнопки не из окна, а из «приложения»,
которое определяется по AppUserModelID (AUMID). Если у процесса задан AUMID,
но в меню «Пуск» нет ярлыка с тем же AUMID, оболочка откатывается к иконке
исполняемого файла — для запуска из исходников это иконка ``pythonw.exe``
(«пустое окно»). Поэтому приложение регистрирует собственный ярлык с AUMID
и иконкой ``assets/pulse.ico``: тогда кнопка на панели задач, закрепление и
уведомления всегда используют иконку Pulse Monitor.

Модуль не тянет сторонних зависимостей: COM вызывается через ctypes.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Optional

APP_USER_MODEL_ID = "PulseMonitor.1.0"
SHORTCUT_NAME = "Pulse Monitor.lnk"
SHORTCUT_DESCRIPTION = "Pulse Monitor — мониторинг системы"

_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_ISHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_IID_IPERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
_FMTID_APP_USER_MODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F2}"
_PID_APP_USER_MODEL_ID = 5

# Индексы методов в vtable
_ISHELL_LINK_GET_PATH = 3
_ISHELL_LINK_SET_DESCRIPTION = 7
_ISHELL_LINK_SET_WORKING_DIR = 9
_ISHELL_LINK_SET_ARGUMENTS = 11
_ISHELL_LINK_GET_ICON = 16
_ISHELL_LINK_SET_ICON = 17
_ISHELL_LINK_SET_PATH = 20
_IPROPERTY_STORE_SET_VALUE = 6
_IPROPERTY_STORE_COMMIT = 7
_IPERSIST_FILE_LOAD = 5
_IPERSIST_FILE_SAVE = 6
_IUNKNOWN_QUERY_INTERFACE = 0
_IUNKNOWN_RELEASE = 2

_VT_LPWSTR = 31
_SLGP_RAWPATH = 4
_CLSCTX_INPROC_SERVER = 1


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("data", ctypes.c_void_p),
    ]


def _guid(text: str) -> _GUID:
    value = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
    return value


def _method(interface, index: int, *argtypes):
    """Получить вызываемый метод COM-интерфейса по индексу в vtable."""
    vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.c_void_p))[0]
    entries = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return prototype(entries[index])


def _query(interface, iid_text: str):
    iid = _guid(iid_text)
    result = ctypes.c_void_p()
    query = _method(
        interface,
        _IUNKNOWN_QUERY_INTERFACE,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    if query(interface, ctypes.byref(iid), ctypes.byref(result)) != 0:
        return None
    return result


def _release(interface) -> None:
    try:
        _method(interface, _IUNKNOWN_RELEASE)(interface)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Пути и параметры запуска
# ---------------------------------------------------------------------------
def project_root() -> Path:
    """Каталог проекта (для запуска из исходников)."""
    return Path(__file__).resolve().parents[1]


def icon_path() -> Optional[Path]:
    """Файл иконки ``assets/pulse.ico`` (в onefile-сборке его нет)."""
    candidate = project_root() / "assets" / "pulse.ico"
    return candidate if candidate.is_file() else None


def start_menu_shortcut_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (
        Path(base)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / SHORTCUT_NAME
    )


def launch_target() -> tuple[str, str, str]:
    """(exe, аргументы, рабочая папка) для ярлыка."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", str(Path(sys.executable).parent)
    root = project_root()
    return sys.executable, f'"{root / "main.py"}"', str(root)


def shortcut_icon() -> str:
    """Иконка ярлыка: сам EXE в сборке, ``assets/pulse.ico`` в исходниках.

    В onefile-сборке иконка из ``_MEIPASS`` живёт только до выхода из
    приложения, поэтому ярлык должен ссылаться на сам EXE.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    icon = icon_path()
    return str(icon) if icon is not None else sys.executable


# ---------------------------------------------------------------------------
# AUMID
# ---------------------------------------------------------------------------
def set_app_user_model_id(aumid: str = APP_USER_MODEL_ID) -> bool:
    """Назначить процессу AppUserModelID (до создания окон)."""
    if sys.platform != "win32":
        return False
    try:
        return (
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(aumid) == 0
        )
    except Exception:
        return False



# ---------------------------------------------------------------------------
# Ярлык в меню «Пуск»
# ---------------------------------------------------------------------------
def _create_shell_link():
    ole32 = ctypes.windll.ole32
    try:
        ole32.CoInitialize(None)
    except Exception:
        pass
    clsid = _guid(_CLSID_SHELL_LINK)
    iid = _guid(_IID_ISHELL_LINK_W)
    link = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(clsid),
        ctypes.c_void_p(),
        _CLSCTX_INPROC_SERVER,
        ctypes.byref(iid),
        ctypes.byref(link),
    )
    if hr != 0 or not link:
        return None
    return link


def _read_shortcut_target(path: Path) -> Optional[str]:
    """Прочитать путь, на который указывает существующий ярлык."""
    link = _create_shell_link()
    if link is None:
        return None
    try:
        persist = _query(link, _IID_IPERSIST_FILE)
        if persist is None:
            return None
        try:
            load = _method(persist, _IPERSIST_FILE_LOAD, ctypes.c_wchar_p, ctypes.c_int)
            if load(persist, str(path), 0) != 0:
                return None
        finally:
            _release(persist)
        buffer = ctypes.create_unicode_buffer(1024)
        get_path = _method(
            link,
            _ISHELL_LINK_GET_PATH,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        if get_path(link, buffer, len(buffer), None, _SLGP_RAWPATH) != 0:
            return None
        return buffer.value or None
    except Exception:
        return None
    finally:
        _release(link)


def _read_shortcut_icon(path: Path) -> Optional[str]:
    """Прочитать путь иконки из ярлыка (None, если иконка не задана)."""
    link = _create_shell_link()
    if link is None:
        return None
    try:
        persist = _query(link, _IID_IPERSIST_FILE)
        if persist is None:
            return None
        try:
            load = _method(persist, _IPERSIST_FILE_LOAD, ctypes.c_wchar_p, ctypes.c_int)
            if load(persist, str(path), 0) != 0:
                return None
        finally:
            _release(persist)
        buffer = ctypes.create_unicode_buffer(1024)
        index = ctypes.c_int(0)
        get_icon = _method(
            link,
            _ISHELL_LINK_GET_ICON,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        )
        if get_icon(link, buffer, len(buffer), ctypes.byref(index)) != 0:
            return None
        return buffer.value or None
    except Exception:
        return None
    finally:
        _release(link)


def _write_shortcut(path: Path, target: str, arguments: str, workdir: str) -> bool:
    link = _create_shell_link()
    if link is None:
        return False
    try:
        _method(link, _ISHELL_LINK_SET_PATH, ctypes.c_wchar_p)(link, target)
        _method(link, _ISHELL_LINK_SET_ARGUMENTS, ctypes.c_wchar_p)(link, arguments)
        _method(link, _ISHELL_LINK_SET_WORKING_DIR, ctypes.c_wchar_p)(link, workdir)
        _method(link, _ISHELL_LINK_SET_DESCRIPTION, ctypes.c_wchar_p)(
            link, SHORTCUT_DESCRIPTION
        )
        _method(link, _ISHELL_LINK_SET_ICON, ctypes.c_wchar_p, ctypes.c_int)(
            link, shortcut_icon(), 0
        )

        store = _query(link, _IID_IPROPERTY_STORE)
        if store is not None:
            try:
                key = _PROPERTYKEY()
                key.fmtid = _guid(_FMTID_APP_USER_MODEL)
                key.pid = _PID_APP_USER_MODEL_ID
                text = ctypes.c_wchar_p(APP_USER_MODEL_ID)
                value = _PROPVARIANT()
                value.vt = _VT_LPWSTR
                value.data = ctypes.cast(text, ctypes.c_void_p)
                set_value = _method(
                    store,
                    _IPROPERTY_STORE_SET_VALUE,
                    ctypes.POINTER(_PROPERTYKEY),
                    ctypes.POINTER(_PROPVARIANT),
                )
                set_value(store, ctypes.byref(key), ctypes.byref(value))
                _method(store, _IPROPERTY_STORE_COMMIT)(store)
            finally:
                _release(store)

        persist = _query(link, _IID_IPERSIST_FILE)
        if persist is None:
            return False
        try:
            save = _method(persist, _IPERSIST_FILE_SAVE, ctypes.c_wchar_p, ctypes.c_int)
            result = save(persist, str(path), 1)
        finally:
            _release(persist)
        return result == 0
    except Exception:
        return False
    finally:
        _release(link)


def ensure_start_menu_shortcut() -> bool:
    """Создать (или обновить) ярлык «Pulse Monitor» в меню «Пуск».

    Ярлык нужен ради корректной иконки и группировки на панели задач:
    Windows сопоставляет AUMID окна с ярлыком и берёт иконку из него.
    """
    if sys.platform != "win32":
        return False
    try:
        path = start_menu_shortcut_path()
        target, arguments, workdir = launch_target()
        icon = shortcut_icon()
        if path.is_file():
            existing_target = _read_shortcut_target(path)
            existing_icon = _read_shortcut_icon(path)
            target_ok = bool(existing_target) and Path(existing_target).resolve() == Path(
                target
            ).resolve()
            icon_ok = bool(existing_icon) and Path(existing_icon).resolve() == Path(
                icon
            ).resolve()
            if target_ok and icon_ok:
                return True
        path.parent.mkdir(parents=True, exist_ok=True)
        return _write_shortcut(path, target, arguments, workdir)
    except Exception:
        return False


def remove_start_menu_shortcut() -> bool:
    """Удалить ярлык (для самопроверки и деинсталляции)."""
    try:
        path = start_menu_shortcut_path()
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False


def prepare_shell_identity() -> bool:
    """Полная регистрация: AUMID процесса + ярлык в меню «Пуск»."""
    if sys.platform != "win32":
        return False
    ok = set_app_user_model_id()
    ok = ensure_start_menu_shortcut() and ok
    return ok

