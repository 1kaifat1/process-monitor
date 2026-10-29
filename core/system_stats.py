"""Быстрые системные метрики для панели обзора."""

from __future__ import annotations

import os
import platform
import time

import psutil

from .utils import format_bytes, format_duration, format_timestamp

_cpu_name_cache: str | None = None
_disk_cache: tuple[float, dict] | None = None


def cpu_name() -> str:
    global _cpu_name_cache
    if _cpu_name_cache is not None:
        return _cpu_name_cache
    name = ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except Exception:
        name = platform.processor()
    _cpu_name_cache = name or "Неизвестный процессор"
    return _cpu_name_cache


def system_info() -> dict:
    try:
        memory = psutil.virtual_memory()
        total_ram = format_bytes(memory.total)
    except Exception:
        total_ram = "—"
    return {
        "hostname": platform.node() or "—",
        "os": f"{platform.system()} {platform.release()}",
        "cpu": cpu_name(),
        "physical_cores": psutil.cpu_count(logical=False) or 0,
        "logical_cores": psutil.cpu_count(logical=True) or 0,
        "total_ram": total_ram,
        "boot_time": format_timestamp(psutil.boot_time()),
        "user": os.environ.get("USERNAME", "—"),
        "python": platform.python_version(),
    }


def collect_system_stats() -> dict:
    """CPU/RAM/диск/аптайм — несколько дешёвых вызовов."""
    global _disk_cache

    cpu = 0.0
    try:
        cpu = float(psutil.cpu_percent(None))
    except Exception:
        pass

    ram_percent = 0.0
    ram_text = "—"
    swap_percent = 0.0
    try:
        memory = psutil.virtual_memory()
        ram_percent = float(memory.percent)
        ram_text = f"{format_bytes(memory.used)} / {format_bytes(memory.total)}"
    except Exception:
        pass
    try:
        swap_percent = float(psutil.swap_memory().percent)
    except Exception:
        pass

    now = time.time()
    disk_percent = 0.0
    disk_text = "—"
    if _disk_cache is None or now - _disk_cache[0] > 10:
        try:
            usage = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
            _disk_cache = (
                now,
                {
                    "percent": float(usage.percent),
                    "text": f"{format_bytes(usage.used)} / {format_bytes(usage.total)}",
                },
            )
        except Exception:
            _disk_cache = (now, {"percent": 0.0, "text": "—"})
    disk_percent = _disk_cache[1]["percent"]
    disk_text = _disk_cache[1]["text"]

    try:
        uptime = max(0.0, time.time() - psutil.boot_time())
    except Exception:
        uptime = 0.0

    return {
        "cpu": round(cpu, 1),
        "ram_percent": round(ram_percent, 1),
        "ram_text": ram_text,
        "swap_percent": round(swap_percent, 1),
        "disk_percent": round(disk_percent, 1),
        "disk_text": disk_text,
        "uptime": uptime,
        "uptime_text": format_duration(uptime),
        "timestamp": now,
    }
