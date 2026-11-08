"""Безопасная очистка рабочих наборов процессов (RAM Cleaner).

Windows: ``EmptyWorkingSet`` для доступных процессов (PID > 4). Процессы без
прав доступа пропускаются, приложение не падает. Linux: сброс pagecache при
наличии root. Тяжёлая операция выполняется в ``RamCleanWorker`` (QThread,
``ui.ram_clean_controller``).

Автономная проверка::

    python core/ram_cleaner.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

MB = 1024 * 1024
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100
ERROR_ACCESS_DENIED = 5


@dataclass(frozen=True)
class RamCleanResult:
    status: str
    freed_mb: float = 0.0
    working_set_freed_mb: float = 0.0
    before_used_mb: float = 0.0
    after_used_mb: float = 0.0
    processes_cleaned: int = 0
    processes_denied: int = 0
    processes_skipped: int = 0
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("success", "partial")


class _WindowsMemoryApi:
    def __init__(self) -> None:
        from ctypes import wintypes

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        self.psapi.EmptyWorkingSet.restype = wintypes.BOOL

    def empty_working_set(self, pid: int) -> str:
        """Вернуть ``cleaned`` / ``denied`` / ``skipped``."""
        access = PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA
        handle = self.kernel32.OpenProcess(access, False, pid)
        if not handle:
            return (
                "denied"
                if ctypes.get_last_error() == ERROR_ACCESS_DENIED
                else "skipped"
            )
        try:
            if self.psapi.EmptyWorkingSet(handle):
                return "cleaned"
            return (
                "denied"
                if ctypes.get_last_error() == ERROR_ACCESS_DENIED
                else "skipped"
            )
        finally:
            self.kernel32.CloseHandle(handle)


def _memory_before() -> psutil._common.svmem:
    return psutil.virtual_memory()


def _memory_result(
    before: psutil._common.svmem,
    after: psutil._common.svmem,
    working_set_freed: int,
    status: str,
    cleaned: int,
    denied: int,
    skipped: int,
    detail: str = "",
) -> RamCleanResult:
    system_freed = max(0, int(before.used) - int(after.used))
    available_gain = max(0, int(after.available) - int(before.available))
    freed = max(system_freed, available_gain)
    return RamCleanResult(
        status=status,
        freed_mb=round(freed / MB, 1),
        working_set_freed_mb=round(working_set_freed / MB, 1),
        before_used_mb=round(before.used / MB, 1),
        after_used_mb=round(after.used / MB, 1),
        processes_cleaned=cleaned,
        processes_denied=denied,
        processes_skipped=skipped,
        detail=detail,
    )


def _clean_windows() -> RamCleanResult:
    before = _memory_before()
    api = _WindowsMemoryApi()
    cleaned = denied = skipped = 0
    working_set_freed = 0

    try:
        processes = list(psutil.process_iter(["pid"]))
    except Exception as exc:
        return RamCleanResult(status="error", detail=str(exc))

    for process in processes:
        pid = int(process.info["pid"])
        if pid <= 4:
            continue

        rss_before = 0
        try:
            rss_before = int(process.memory_info().rss)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        try:
            outcome = api.empty_working_set(pid)
        except Exception:
            outcome = "skipped"

        if outcome == "cleaned":
            cleaned += 1
            try:
                rss_after = int(process.memory_info().rss)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                rss_after = rss_before
            working_set_freed += max(0, rss_before - rss_after)
        elif outcome == "denied":
            denied += 1
        else:
            skipped += 1

    time.sleep(0.15)  # дать системе обновить счётчики памяти
    after = _memory_before()
    if cleaned == 0:
        status = "permission_denied" if denied else "partial"
    else:
        status = "partial" if denied or skipped else "success"

    return _memory_result(
        before,
        after,
        working_set_freed,
        status,
        cleaned,
        denied,
        skipped,
    )


def _clean_linux() -> RamCleanResult:
    before = _memory_before()
    if os.geteuid() != 0:
        after = _memory_before()
        return _memory_result(
            before, after, 0, "permission_denied", 0, 1, 0, "root required"
        )
    try:
        os.sync()
        Path("/proc/sys/vm/drop_caches").write_text("3\n", encoding="ascii")
    except PermissionError:
        after = _memory_before()
        return _memory_result(
            before, after, 0, "permission_denied", 0, 1, 0, "root required"
        )
    except OSError as exc:
        after = _memory_before()
        return RamCleanResult(status="error", detail=str(exc))

    after = _memory_before()
    return _memory_result(before, after, 0, "success", 1, 0, 0)


def clean_ram() -> RamCleanResult:
    """Очистить рабочие наборы процессов и вернуть статистику."""
    if sys.platform == "win32":
        try:
            return _clean_windows()
        except Exception as exc:
            return RamCleanResult(status="error", detail=str(exc))
    if sys.platform.startswith("linux"):
        try:
            return _clean_linux()
        except Exception as exc:
            return RamCleanResult(status="error", detail=str(exc))
    return RamCleanResult(status="unsupported")


if __name__ == "__main__":
    result = clean_ram()
    print(f"status={result.status}")
    print(f"freed={result.freed_mb:.1f} MB")
    print(f"working_set={result.working_set_freed_mb:.1f} MB")
    print(f"used={result.before_used_mb:.1f} -> {result.after_used_mb:.1f} MB")
    print(
        "cleaned={} denied={} skipped={}".format(
            result.processes_cleaned,
            result.processes_denied,
            result.processes_skipped,
        )
    )
    if result.detail:
        print(f"detail={result.detail}")

