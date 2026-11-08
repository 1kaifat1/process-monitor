"""Тонкая обёртка над WinAPI: видимые окна, сессии, пути процессов, версии файлов."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_version = ctypes.WinDLL("version", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

if os.name == "nt":
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND

    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    _version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    _version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    _version.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    _version.GetFileVersionInfoW.restype = wintypes.BOOL
    _version.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    _version.VerQueryValueW.restype = wintypes.BOOL

_VERSION_CACHE: dict[str, dict[str, str]] = {}


def visible_windows() -> dict[int, str]:
    """Карта PID -> заголовок первого видимого окна процесса."""
    titles: dict[int, str] = {}

    @WNDENUMPROC
    def _callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value and pid.value not in titles:
                titles[pid.value] = title
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_callback, 0)
    except Exception:
        pass
    return titles


def foreground_pid() -> int | None:
    """PID процесса активного окна переднего плана."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None
    except Exception:
        return None


def query_process_image_path(pid: int) -> str:
    """Быстрое получение полного пути к EXE процесса (включая Session 0) без прав администратора."""
    if pid <= 4:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            val = buf.value.strip()
            # Для псевдопроцессов ядра (Registry, Memory Compression) Windows возвращает имя без пути
            if len(val) >= 3 and (val[1] == ":" or val.startswith("\\\\")):
                return val
            return ""
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(handle)
    return ""


def process_session_id(pid: int) -> int:
    """Идентификатор сессии Windows для процесса (0 — службы)."""
    session = wintypes.DWORD(0)
    try:
        if kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session)):
            return int(session.value)
    except Exception:
        pass
    return -1


def process_sessions(pids: list[int]) -> dict[int, int]:
    return {pid: process_session_id(pid) for pid in pids}


def file_version_info(path: str) -> dict[str, str]:
    """Описание, компания и версия EXE-файла через version.dll (с кэшированием)."""
    if not path:
        return {}
    norm = os.path.normcase(os.path.normpath(path))
    if norm in _VERSION_CACHE:
        return _VERSION_CACHE[norm]

    result: dict[str, str] = {}
    if not os.path.isfile(path):
        return result
    try:
        dummy = wintypes.DWORD(0)
        size = _version.GetFileVersionInfoSizeW(str(path), ctypes.byref(dummy))
        if not size:
            _VERSION_CACHE[norm] = result
            return result
        buffer = ctypes.create_string_buffer(size)
        if not _version.GetFileVersionInfoW(str(path), 0, size, buffer):
            _VERSION_CACHE[norm] = result
            return result

        langs: list[str] = []
        trans_ptr = ctypes.c_void_p()
        trans_len = wintypes.UINT(0)
        if _version.VerQueryValueW(
            buffer, r"\VarFileInfo\Translation", ctypes.byref(trans_ptr), ctypes.byref(trans_len)
        ) and trans_ptr.value and trans_len.value >= 4:
            count = int(trans_len.value) // 4
            words = (wintypes.WORD * (count * 2)).from_address(trans_ptr.value)
            for i in range(count):
                lang_id = words[i * 2]
                codepage = words[i * 2 + 1]
                code = f"{lang_id:04x}{codepage:04x}"
                if code not in langs:
                    langs.append(code)

        for fallback in ("041904b0", "040904b0", "040904e4", "000004b0", "04090000"):
            if fallback not in langs:
                langs.append(fallback)

        for lang in langs:
            for key, label in (
                ("FileDescription", "description"),
                ("CompanyName", "company"),
                ("ProductName", "product"),
                ("FileVersion", "version"),
            ):
                if label in result:
                    continue
                block = ctypes.c_void_p()
                length = wintypes.UINT(0)
                sub = f"\\StringFileInfo\\{lang}\\{key}"
                if _version.VerQueryValueW(
                    buffer, sub, ctypes.byref(block), ctypes.byref(length)
                ) and block.value and length.value > 0:
                    text = ctypes.wstring_at(block.value).strip("\x00").strip()
                    if text:
                        result[label] = text
            if len(result) >= 3:
                break
    except Exception:
        pass

    if len(_VERSION_CACHE) < 4096:
        _VERSION_CACHE[norm] = result
    return result


def set_autostart(executable: str, script: str | None, enabled: bool) -> bool:
    """Добавить/удалить приложение из автозапуска текущего пользователя."""
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "PulseMonitor"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                if script:
                    command = f'"{executable}" "{script}"'
                else:
                    command = f'"{executable}"'
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, "PulseMonitor")
        return True
    except OSError:
        return False


def executable_display_name(path: str) -> str:
    info = file_version_info(path)
    return info.get("description") or Path(path).name if path else ""
