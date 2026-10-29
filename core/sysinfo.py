"""Быстрый снимок всех процессов одним вызовом NtQuerySystemInformation.

Один системный вызов отдаёт PID, имя, память, потоки, дескрипторы, сессию
и процессорное время. Это в десятки раз дешевле, чем опрашивать psutil
по каждому процессу отдельно.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
SYSTEM_PROCESS_INFORMATION_CLASS = 5

_ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
_ntdll.NtQuerySystemInformation.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
_ntdll.NtQuerySystemInformation.restype = ctypes.c_long


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


class SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_int64),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", ctypes.c_uint64),
        ("CreateTime", ctypes.c_int64),
        ("UserTime", ctypes.c_int64),
        ("KernelTime", ctypes.c_int64),
        ("ImageName", UNICODE_STRING),
        ("BasePriority", ctypes.c_int32),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_void_p),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivatePageCount", ctypes.c_size_t),
        ("ReadOperationCount", ctypes.c_int64),
        ("WriteOperationCount", ctypes.c_int64),
        ("OtherOperationCount", ctypes.c_int64),
        ("ReadTransferCount", ctypes.c_int64),
        ("WriteTransferCount", ctypes.c_int64),
        ("OtherTransferCount", ctypes.c_int64),
    ]


def _query_buffer() -> tuple[ctypes.Array, int]:
    size = 1 << 20  # 1 МБ обычно достаточно для ~400 процессов
    for _attempt in range(8):
        buffer = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(
            SYSTEM_PROCESS_INFORMATION_CLASS,
            buffer,
            size,
            ctypes.byref(needed),
        )
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size = max(int(needed.value) + 65536, size * 2)
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation вернул 0x{status & 0xFFFFFFFF:08X}")
        return buffer, size
    raise OSError("Не удалось получить размер буфера процессов")


def query_processes() -> list[dict]:
    """Вернуть список процессов (без путей и пользователей)."""
    # Буфер должен оставаться живым: указатели ImageName смотрят внутрь него.
    buffer, total = _query_buffer()
    items: list[dict] = []
    offset = 0
    guard = 0
    while guard < 20000:
        guard += 1
        if offset + ctypes.sizeof(SYSTEM_PROCESS_INFORMATION) > total:
            break
        info = SYSTEM_PROCESS_INFORMATION.from_buffer(buffer, offset)

        pid = int(info.UniqueProcessId or 0)
        name = ""
        if info.ImageName.Buffer and info.ImageName.Length:
            name = ctypes.wstring_at(
                info.ImageName.Buffer, info.ImageName.Length // 2
            )
        name = (name or "").rsplit("\\", 1)[-1]

        # CreateTime приходит в FILETIME (100 нс с 1601 года).
        create_time = 0.0
        if info.CreateTime:
            create_time = info.CreateTime / 10_000_000 - 11_644_473_600
        user_time = max(info.UserTime, 0) / 10_000_000
        kernel_time = max(info.KernelTime, 0) / 10_000_000

        if 0 <= pid < 10_000_000:
            items.append(
                {
                    "pid": pid,
                    "ppid": int(info.InheritedFromUniqueProcessId or 0),
                    "name": name,
                    "threads": int(info.NumberOfThreads),
                    "handles": int(info.HandleCount),
                    "session": int(info.SessionId),
                    "create_time": create_time,
                    "cpu_seconds": user_time + kernel_time,
                    "rss": int(info.WorkingSetSize),
                    "private": int(info.PrivatePageCount),
                    "virtual": int(info.VirtualSize),
                }
            )

        step = int(info.NextEntryOffset)
        if step <= 0:
            break
        offset += step
    return items
