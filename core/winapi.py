"""Тонкая обёртка над WinAPI: видимые окна, сессии, версии файлов."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_version = ctypes.WinDLL("version", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

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
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


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
    """Описание, компания и версия EXE-файла через version.dll."""
    result: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return result
    try:
        size = _version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return result
        buffer = ctypes.create_string_buffer(size)
        if not _version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return result
        for lang in ("040904b0", "040904e4", "000004b0"):
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
                ) and block.value:
                    text = ctypes.wstring_at(block.value, length.value).strip("\x00").strip()
                    if text:
                        result[label] = text
            if len(result) >= 3:
                break
    except Exception:
        return result
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
