"""Поиск и завершение процессов, удерживающих файл или папку.

Используется нативный Windows Restart Manager (``rstrtmgr.dll``): он знает,
какие процессы держат дескрипторы ресурса, и умеет перечислить их мгновенно
(``RmStartSession`` → ``RmRegisterResources`` → ``RmGetList``).

Завершение выполняется через ``OpenProcess(TerminateProcess)``: в отличие от
``RmShutdown`` этот путь позволяет точно определить процесс, который не удалось
завершить из-за нехватки прав (``ERROR_ACCESS_DENIED``), и показать
пользователю предложение перезапустить Pulse Monitor от администратора.

Модуль импортируется на любой платформе: WinAPI загружается только под Windows,
а вызовы на других ОС возвращают понятную ошибку.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
CCH_RM_SESSION_KEY = 32

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_MORE_DATA = 234

PROCESS_TERMINATE = 0x0001

# Сколько файлов внутри папки регистрировать в Restart Manager. Папка сама по
# себе не всегда попадает в список, поэтому дополнительно опрашиваются
# вложенные файлы (ограниченная глубина и количество — без зависаний на
# огромных каталогах).
MAX_DIRECTORY_FILES = 500
DIRECTORY_SCAN_DEPTH = 2

# Ключи типов приложений Restart Manager для перевода в интерфейсе.
APP_TYPE_KEYS = {
    0: "неизвестно",
    1: "приложение",
    2: "приложение",
    3: "служба",
    4: "проводник",
    5: "консоль",
    1000: "критический",
}


class RestartManagerError(OSError):
    """Ошибка вызова Restart Manager."""

    def __init__(self, code: int, operation: str) -> None:
        message = f"{operation}: код {code}"
        if os.name == "nt" and code:
            try:
                message = f"{operation}: {ctypes.FormatError(code).strip()}"
            except Exception:
                pass
        super().__init__(message)
        self.winerror = code
        self.operation = operation


@dataclass(frozen=True)
class LockingProcess:
    """Процесс, удерживающий дескриптор файла."""

    pid: int
    name: str
    exe: str
    app_name: str
    app_type: int
    session: int
    restartable: bool

    @property
    def app_type_key(self) -> str:
        return APP_TYPE_KEYS.get(self.app_type, "неизвестно")


@dataclass
class UnlockResult:
    """Результат принудительной разблокировки."""

    terminated: list[LockingProcess] = field(default_factory=list)
    failed: list[tuple[LockingProcess, str]] = field(default_factory=list)
    remaining: list[LockingProcess] = field(default_factory=list)
    access_denied: bool = False
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error and not self.failed and not self.remaining


if os.name == "nt":
    _rstrtmgr = ctypes.WinDLL("rstrtmgr", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [
            ("dwProcessId", wintypes.DWORD),
            ("ProcessStartTime", wintypes.FILETIME),
        ]

    class _RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", _RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
            ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
            ("ApplicationType", ctypes.c_uint),
            ("AppStatus", wintypes.ULONG),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    _rstrtmgr.RmStartSession.argtypes = [
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        wintypes.LPWSTR,
    ]
    _rstrtmgr.RmStartSession.restype = wintypes.DWORD

    _rstrtmgr.RmRegisterResources.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        ctypes.POINTER(wintypes.LPCWSTR),
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    _rstrtmgr.RmRegisterResources.restype = wintypes.DWORD

    _rstrtmgr.RmGetList.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(_RM_PROCESS_INFO),
        ctypes.POINTER(wintypes.ULONG),
    ]
    _rstrtmgr.RmGetList.restype = wintypes.DWORD

    _rstrtmgr.RmEndSession.argtypes = [wintypes.DWORD]
    _rstrtmgr.RmEndSession.restype = wintypes.DWORD

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:  # pragma: no cover - проект рассчитан на Windows
    _rstrtmgr = None
    _kernel32 = None
    _RM_PROCESS_INFO = None  # type: ignore[assignment]


def is_supported() -> bool:
    """Доступен ли Restart Manager на этой платформе."""
    return _rstrtmgr is not None


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _directory_files(folder: Path) -> list[str]:
    """Файлы внутри папки (до ``MAX_DIRECTORY_FILES``, глубина ограничена)."""
    collected: list[str] = []

    def walk(current: Path, level: int) -> bool:
        try:
            entries = list(os.scandir(current))
        except OSError:
            return False
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False):
                    collected.append(entry.path)
                    if len(collected) >= MAX_DIRECTORY_FILES:
                        return True
                elif entry.is_dir(follow_symlinks=False) and level < DIRECTORY_SCAN_DEPTH:
                    if walk(Path(entry.path), level + 1):
                        return True
            except OSError:
                continue
        return False

    walk(folder, 0)
    return collected


def _paths_for(path: Path) -> list[str]:
    """Ресурсы для регистрации в Restart Manager: файл или папка + её файлы."""
    if path.is_dir():
        return [str(path), *_directory_files(path)]
    return [str(path)]


def _process_details(pid: int) -> tuple[str, str]:
    """Имя и путь процесса через psutil (если доступны)."""
    try:
        import psutil

        process = psutil.Process(pid)
        name = process.name() or ""
        try:
            exe = process.exe() or ""
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            exe = ""
        return name, exe
    except Exception:
        return "", ""


def _to_process(info: "_RM_PROCESS_INFO") -> LockingProcess:
    pid = int(info.Process.dwProcessId)
    name, exe = _process_details(pid)
    app_name = (info.strAppName or "").strip()
    return LockingProcess(
        pid=pid,
        name=name or app_name or f"PID {pid}",
        exe=exe,
        app_name=app_name,
        app_type=int(info.ApplicationType),
        session=int(info.TSSessionId),
        restartable=bool(info.bRestartable),
    )


# ---------------------------------------------------------------------------
# Поиск блокирующих процессов
# ---------------------------------------------------------------------------
def _query_restart_manager(paths: list[str]) -> list["_RM_PROCESS_INFO"]:
    if _rstrtmgr is None:
        raise RestartManagerError(0, "Restart Manager недоступен (только Windows)")
    if not paths:
        return []

    session = wintypes.DWORD(0)
    key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
    code = _rstrtmgr.RmStartSession(ctypes.byref(session), 0, key)
    if code != ERROR_SUCCESS:
        raise RestartManagerError(int(code), "RmStartSession")
    try:
        files = (wintypes.LPCWSTR * len(paths))(*paths)
        code = _rstrtmgr.RmRegisterResources(
            session, len(paths), files, 0, None, 0, None
        )
        if code != ERROR_SUCCESS:
            raise RestartManagerError(int(code), "RmRegisterResources")

        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reasons = wintypes.ULONG(0)
        code = _rstrtmgr.RmGetList(
            session,
            ctypes.byref(needed),
            ctypes.byref(count),
            None,
            ctypes.byref(reasons),
        )
        if code == ERROR_SUCCESS and needed.value == 0:
            return []
        if code not in (ERROR_SUCCESS, ERROR_MORE_DATA):
            raise RestartManagerError(int(code), "RmGetList")
        if needed.value == 0:
            return []

        infos = (_RM_PROCESS_INFO * needed.value)()
        count = wintypes.UINT(needed.value)
        code = _rstrtmgr.RmGetList(
            session,
            ctypes.byref(needed),
            ctypes.byref(count),
            infos,
            ctypes.byref(reasons),
        )
        if code != ERROR_SUCCESS:
            raise RestartManagerError(int(code), "RmGetList")
        return [infos[index] for index in range(count.value)]
    finally:
        _rstrtmgr.RmEndSession(session)


def find_locking_processes(path: str | Path) -> list[LockingProcess]:
    """Список процессов, удерживающих файл или папку (может быть пустым)."""
    text = str(path or "").strip().strip('"')
    if not text:
        return []
    target = Path(text)
    if not target.exists():
        return []

    infos = _query_restart_manager(_paths_for(target))
    processes: list[LockingProcess] = []
    seen: set[int] = set()
    for info in infos:
        process = _to_process(info)
        if process.pid in seen:
            continue
        seen.add(process.pid)
        processes.append(process)
    processes.sort(key=lambda item: item.name.lower())
    return processes


# ---------------------------------------------------------------------------
# Завершение процессов
# ---------------------------------------------------------------------------
def _terminate_pid(pid: int) -> None:
    """Завершить процесс; при отказе бросает ``OSError`` (winerror 5)."""
    if _kernel32 is None:
        raise RestartManagerError(0, "Kernel32 недоступен (только Windows)")
    handle = _kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not _kernel32.TerminateProcess(handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _kernel32.CloseHandle(handle)


def terminate_processes(processes: list[LockingProcess]) -> UnlockResult:
    """Принудительно завершить перечисленные процессы."""
    result = UnlockResult()
    for process in processes:
        pid = process.pid
        if pid in (0, 4):
            # System Idle Process / System — завершить нельзя ни при каких правах.
            result.failed.append((process, "system"))
            result.access_denied = True
            continue
        try:
            _terminate_pid(pid)
            result.terminated.append(process)
        except OSError as exc:
            code = int(getattr(exc, "winerror", 0) or 0)
            if code == ERROR_ACCESS_DENIED:
                result.access_denied = True
                reason = "access_denied"
            elif code == 87:  # ERROR_INVALID_PARAMETER — процесса уже нет
                reason = "already_exited"
            else:
                reason = str(exc)
            result.failed.append((process, reason))
    return result


def _wait_for_release(path: Path, timeout: float = 2.0) -> list[LockingProcess]:
    """Дождаться, пока Windows освободит дескрипторы после завершения."""
    deadline = time.monotonic() + timeout
    remaining = find_locking_processes(path)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.1)
        remaining = find_locking_processes(path)
    return remaining


def force_unlock(
    path: str | Path, processes: list[LockingProcess] | None = None
) -> UnlockResult:
    """Завершить удерживающие процессы и дождаться снятия блокировки."""
    text = str(path or "").strip().strip('"')
    if not text:
        return UnlockResult(error="empty_path")
    target = Path(text)
    if not target.exists():
        return UnlockResult(error="not_found")

    holders = processes if processes is not None else find_locking_processes(target)
    if not holders:
        return UnlockResult()

    result = terminate_processes(holders)
    if result.terminated:
        result.remaining = _wait_for_release(target)
    else:
        result.remaining = holders
    return result
