"""Сбор сведений о процессах Windows (включая фоновые и скрытые)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import psutil

from .i18n import tr
from .utils import format_bytes, format_duration, format_timestamp
from .winapi import file_version_info, process_sessions, visible_windows

_STATUS_LABELS = (
    ("STATUS_RUNNING", "Работает"),
    ("STATUS_SLEEPING", "Ожидание"),
    ("STATUS_DISK_SLEEP", "Ожидание диска"),
    ("STATUS_STOPPED", "Остановлен"),
    ("STATUS_TRACING_STOP", "Отладка"),
    ("STATUS_ZOMBIE", "Зомби"),
    ("STATUS_DEAD", "Завершён"),
    ("STATUS_WAKE_KILL", "Завершается"),
    ("STATUS_WAKING", "Пробуждение"),
    ("STATUS_IDLE", "Простой"),
    ("STATUS_LOCKED", "Заблокирован"),
    ("STATUS_WAITING", "Ожидает"),
    ("STATUS_SUSPENDED", "Приостановлен"),
    ("STATUS_PARKED", "Припаркован"),
    ("STATUS_WAITING", "Ожидает"),
)

# Часть констант psutil доступна только на отдельных платформах.
STATUS_RU = {
    getattr(psutil, name): label
    for name, label in _STATUS_LABELS
    if getattr(psutil, name, None) is not None
}

SYSTEM32 = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows") + r"\System32")
WINDIR = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))

TEMP_DIRS = [d for d in (os.environ.get("TEMP"), os.environ.get("TMP"),
                         os.path.join(WINDIR, "Temp")) if d]

USER_WRITABLE_DIRS = [
    d for d in (
        os.environ.get("APPDATA"),
        os.environ.get("LOCALAPPDATA"),
        str(Path.home() / "Downloads"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "Documents"),
    ) if d
]

SYSTEM_PROCESS_NAMES = {
    "svchost.exe", "lsass.exe", "winlogon.exe", "services.exe", "csrss.exe",
    "smss.exe", "wininit.exe", "spoolsv.exe", "taskhostw.exe", "explorer.exe",
    "dwm.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "audiodg.exe",
}

PRIORITIES = {
    "Низкий": psutil.IDLE_PRIORITY_CLASS,
    "Ниже обычного": psutil.BELOW_NORMAL_PRIORITY_CLASS,
    "Обычный": psutil.NORMAL_PRIORITY_CLASS,
    "Выше обычного": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
    "Высокий": psutil.HIGH_PRIORITY_CLASS,
    "Реального времени": psutil.REALTIME_PRIORITY_CLASS,
}


def _lower(value: str | None) -> str:
    return (value or "").lower()


def _is_under(path: str, directories: list[str]) -> bool:
    if not path:
        return False
    candidate = os.path.normcase(path)
    for directory in directories:
        if not directory:
            continue
        root = os.path.normcase(directory).rstrip("\\")
        if candidate == root or candidate.startswith(root + "\\"):
            return True
    return False


class ProcessCollector:
    """Кэширует объекты Process, чтобы корректно считать CPU и не нагружать ПК."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, float], dict[str, Any]] = {}
        self._cores = max(1, psutil.cpu_count(logical=True) or 1)
        try:
            self._total_ram = psutil.virtual_memory().total
        except Exception:
            self._total_ram = 0
        self._visible_windows: dict[int, str] = {}
        self._sessions: dict[int, int] = {}
        self._last_rows: list[dict[str, Any]] = []
        self._last_time = 0.0
        self._with_handles = False
        self._prev_cpu: dict[int, tuple[float, float]] = {}

    def snapshot(self) -> dict[str, Any]:
        """Быстрый снимок через NtQuery с откатом на psutil."""
        started = time.perf_counter()
        try:
            from .sysinfo import query_processes

            items = query_processes()
        except Exception:
            return self._snapshot_psutil(started)
        return self._snapshot_fast(items, started)

    def _snapshot_fast(self, items: list[dict], started: float) -> dict[str, Any]:
        visible = visible_windows()
        self._visible_windows = visible

        now = time.perf_counter()
        seen: set[int] = set()
        for item in items:
            pid = int(item["pid"])
            seen.add(pid)
            entry = self._cache.get(pid)
            create_time = float(item.get("create_time") or 0.0)
            if entry is None or abs(
                float(entry.get("create_time") or 0.0) - create_time
            ) > 1.0:
                entry = {
                    "pid": pid,
                    "name": item.get("name", ""),
                    "create_time": create_time,
                    "exe": None,
                    "cmdline": None,
                    "user": None,
                    "ps_name": None,
                    "exe_reasons": None,
                }
                self._cache[pid] = entry

            previous = self._prev_cpu.get(pid)
            cpu = 0.0
            cpu_seconds = float(item.get("cpu_seconds") or 0.0)
            if previous is not None:
                delta = now - previous[1]
                if delta > 0:
                    cpu = ((cpu_seconds - previous[0]) / delta) / self._cores * 100.0
            self._prev_cpu[pid] = (cpu_seconds, now)
            entry["_cpu"] = round(min(max(cpu, 0.0), 100.0), 1)

        # Путь, пользователь и командная строка дорогие — добираем порциями,
        # ограничивая не только количество, но и время на один снимок.
        budget = 20
        enrich_started = time.perf_counter()
        for item in items:
            if budget <= 0 or time.perf_counter() - enrich_started > 0.04:
                break
            entry = self._cache.get(int(item["pid"]))
            if entry is None or entry.get("exe") is not None:
                continue
            if int(item.get("session") or 0) == 0:
                continue
            self._enrich_entry(entry, item)
            budget -= 1

        if len(self._cache) > len(seen):
            for pid in list(self._cache):
                if pid not in seen:
                    self._cache.pop(pid, None)
        if len(self._prev_cpu) > len(seen):
            for pid in list(self._prev_cpu):
                if pid not in seen:
                    self._prev_cpu.pop(pid, None)

        rows: list[dict[str, Any]] = []
        hidden_count = 0
        suspicious_count = 0
        total_ram = self._total_ram or 1

        for item in items:
            row = self._build_fast_row(item, total_ram)
            if row is None:
                continue
            if "скрыт" in row["flags"]:
                hidden_count += 1
            if row["suspicious"]:
                suspicious_count += 1
            rows.append(row)

        rows.sort(key=lambda row: row["pid"])
        self._last_rows = rows
        self._last_time = time.time()
        elapsed_ms = (time.perf_counter() - started) * 1000

        return {
            "rows": rows,
            "stats": {
                "total": len(rows),
                "hidden": hidden_count,
                "suspicious": suspicious_count,
                "elapsed_ms": round(elapsed_ms, 1),
                "timestamp": self._last_time,
                "cores": self._cores,
            },
        }

    def _enrich_entry(self, entry: dict[str, Any], item: dict) -> None:
        pid = int(item["pid"])
        try:
            process = psutil.Process(pid)
            entry["exe"] = process.exe() or ""
            try:
                entry["cmdline"] = " ".join(process.cmdline())
            except Exception:
                entry["cmdline"] = ""
            try:
                entry["user"] = process.username() or ""
            except Exception:
                entry["user"] = ""
            try:
                entry["ps_name"] = process.name() or ""
            except Exception:
                entry["ps_name"] = ""
        except Exception:
            entry["exe"] = ""
            entry["cmdline"] = ""
            entry["user"] = ""
        entry["exe_reasons"] = self._exe_reasons(
            entry.get("exe") or "", entry.get("name") or ""
        )

    @staticmethod
    def _exe_reasons(exe: str, name: str) -> list[str]:
        reasons: list[str] = []
        if not exe:
            return reasons
        exe_lower = _lower(exe)
        name_lower = _lower(name)
        if _is_under(exe, TEMP_DIRS):
            reasons.append("запущен из TEMP")
        if name_lower in SYSTEM_PROCESS_NAMES and not any(
            exe_lower.startswith(root) for root in (SYSTEM32, WINDIR)
        ):
            reasons.append("системное имя вне System32")
        if not os.path.isfile(exe):
            reasons.append("файл отсутствует")
        if _is_under(exe, USER_WRITABLE_DIRS) and name_lower in SYSTEM_PROCESS_NAMES:
            reasons.append("системное имя в пользовательской папке")
        return reasons

    def _build_fast_row(self, item: dict, total_ram: int) -> dict[str, Any] | None:
        pid = int(item["pid"])
        entry = self._cache.get(pid) or {}
        session = int(item.get("session") or 0)
        window_title = self._visible_windows.get(pid, "")

        name = item.get("name") or entry.get("ps_name") or ""
        if not name:
            if pid == 0:
                name = "System Idle Process"
            elif pid == 4:
                name = "System"
            else:
                name = f"PID {pid}"

        is_system_name = name.lower() in SYSTEM_PROCESS_NAMES
        flags: list[str] = []
        if pid in (0, 4) or session == 0 or is_system_name:
            flags.append("системный")
        if session == 0:
            flags.append("служба")
        elif not window_title and not is_system_name:
            flags.append("скрыт")

        exe = entry.get("exe")
        suspicious_reasons = list(entry.get("exe_reasons") or [])
        if exe == "" and session > 0 and is_system_name:
            suspicious_reasons.append("путь недоступен")
        suspicious = bool(suspicious_reasons)
        if suspicious:
            flags.append("подозрительный")

        rss = int(item.get("rss") or 0)
        mem_pct = (rss / total_ram * 100.0) if total_ram else 0.0
        cpu = float(entry.get("_cpu", 0.0) or 0.0)
        create_time = float(item.get("create_time") or 0.0)

        return {
            "pid": pid,
            "ppid": int(item.get("ppid") or 0),
            "name": name,
            "flags": ", ".join(flags),
            "flags_list": flags,
            "suspicious": suspicious,
            "suspicious_reasons": suspicious_reasons,
            "cpu": cpu,
            "cpu_raw": round(cpu * self._cores, 1),
            "mem": rss,
            "mem_pct": round(mem_pct, 2),
            "threads": int(item.get("threads") or 0),
            "handles": int(item.get("handles") or 0),
            "user": entry.get("user") or "",
            "status": "Простой" if pid == 0 else "Работает",
            "session": session,
            "started": format_timestamp(create_time) if create_time > 0 else "—",
            "started_ts": create_time,
            "window": window_title,
            "exe": exe or "",
            "cmdline": entry.get("cmdline") or "",
            "io_read": 0,
            "io_write": 0,
            "mem_text": format_bytes(rss),
            "cpu_text": f"{cpu:.1f}%",
            "mem_pct_text": f"{mem_pct:.1f}%",
        }


    def _snapshot_psutil(self, started: float) -> dict[str, Any]:
        self._visible_windows = visible_windows()
        # Подсчёт дескрипторов — дорогая операция, поэтому только по запросу.
        try:
            from .config_manager import config

            self._with_handles = bool(config.get("processes.columns.handles", False))
        except Exception:
            self._with_handles = False

        raw_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        current_keys: set[tuple[int, float]] = set()

        for proc in psutil.process_iter(
            attrs=["pid", "name", "create_time"], ad_value=None
        ):
            info = proc.info
            pid = info.get("pid")
            if pid is None:
                continue
            key = (int(pid), float(info.get("create_time") or 0.0))
            current_keys.add(key)
            entry = self._cache.get(key)
            if entry is None:
                entry = {
                    "proc": proc,
                    "pid": int(pid),
                    "name": info.get("name") or f"PID {pid}",
                    "exe": None,
                    "cmdline": None,
                    "user": None,
                    "create_time": key[1],
                    "exe_reasons": None,
                    "handles": 0,
                    "handles_ts": 0.0,
                }
                self._cache[key] = entry
            raw_entries.append((entry, info))

        if len(self._cache) > len(current_keys):
            for key in list(self._cache):
                if key not in current_keys:
                    self._cache.pop(key, None)

        pids = [entry["pid"] for entry, _info in raw_entries]
        self._sessions = process_sessions(pids)

        rows: list[dict[str, Any]] = []
        hidden_count = 0
        suspicious_count = 0

        for entry, info in raw_entries:
            row = self._build_row(entry, info)
            if row is None:
                continue
            if "скрыт" in row["flags"]:
                hidden_count += 1
            if row["suspicious"]:
                suspicious_count += 1
            rows.append(row)

        rows.sort(key=lambda item: item["pid"])
        self._last_rows = rows
        self._last_time = time.time()
        elapsed_ms = (time.perf_counter() - started) * 1000

        return {
            "rows": rows,
            "stats": {
                "total": len(rows),
                "hidden": hidden_count,
                "suspicious": suspicious_count,
                "elapsed_ms": round(elapsed_ms, 1),
                "timestamp": self._last_time,
                "cores": self._cores,
            },
        }

    def _build_row(
        self, entry: dict[str, Any], info: dict[str, Any]
    ) -> dict[str, Any] | None:
        proc: psutil.Process = entry["proc"]
        pid: int = entry["pid"]
        name: str = entry["name"] or "—"

        try:
            cpu_raw = proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        except Exception:
            cpu_raw = 0.0

        if entry["exe"] is None:
            try:
                entry["exe"] = proc.exe() or ""
            except Exception:
                entry["exe"] = ""

        if entry["cmdline"] is None:
            try:
                parts = proc.cmdline()
                entry["cmdline"] = " ".join(parts) if parts else ""
            except Exception:
                entry["cmdline"] = ""

        if entry["user"] is None:
            try:
                entry["user"] = proc.username() or ""
            except Exception:
                entry["user"] = ""

        try:
            memory = proc.memory_info()
            rss = int(memory.rss)
        except Exception:
            rss = 0

        mem_pct = (rss / self._total_ram * 100.0) if self._total_ram else 0.0

        try:
            threads = int(proc.num_threads())
        except Exception:
            threads = 0

        handles = int(entry.get("handles", 0) or 0)
        now = time.time()
        # num_handles перечисляет все дескрипторы системы — обновляем редко.
        if self._with_handles and now - float(entry.get("handles_ts", 0.0)) > 15.0:
            try:
                handles = int(proc.num_handles())
            except Exception:
                handles = 0
            entry["handles"] = handles
            entry["handles_ts"] = now

        try:
            status = proc.status()
        except Exception:
            status = "unknown"

        try:
            ppid = int(proc.ppid())
        except Exception:
            ppid = 0

        io_read = 0
        io_write = 0

        create_time = float(entry.get("create_time") or 0.0)
        exe = entry["exe"] or ""
        window_title = self._visible_windows.get(pid, "")
        session = self._sessions.get(pid, -1)
        user = entry["user"] or ""

        flags: list[str] = []
        if pid in (0, 4) or session == 0:
            flags.append("системный")
        if session == 0:
            flags.append("служба")
        elif not window_title:
            # Приложение работает в сессии пользователя без видимого окна.
            flags.append("скрыт")

        exe_lower = _lower(exe)
        name_lower = _lower(name)

        if entry.get("exe_reasons") is None:
            reasons: list[str] = []
            if exe:
                if _is_under(exe, TEMP_DIRS):
                    reasons.append("запущен из TEMP")
                if name_lower in SYSTEM_PROCESS_NAMES and not any(
                    exe_lower.startswith(root) for root in (SYSTEM32, WINDIR)
                ):
                    reasons.append("системное имя вне System32")
                if not os.path.isfile(exe):
                    reasons.append("файл отсутствует")
                if (
                    _is_under(exe, USER_WRITABLE_DIRS)
                    and name_lower in SYSTEM_PROCESS_NAMES
                ):
                    reasons.append("системное имя в пользовательской папке")
            entry["exe_reasons"] = reasons

        suspicious_reasons = list(entry["exe_reasons"])
        if not exe and pid > 4 and session > 0:
            suspicious_reasons.append("путь недоступен")

        suspicious = bool(suspicious_reasons)
        if suspicious:
            flags.append("подозрительный")

        cpu_total = round(min(max(cpu_raw / self._cores, 0.0), 100.0), 1)

        return {
            "pid": pid,
            "ppid": ppid,
            "name": name,
            "flags": ", ".join(flags),
            "flags_list": flags,
            "suspicious": suspicious,
            "suspicious_reasons": suspicious_reasons,
            "cpu": cpu_total,
            "cpu_raw": round(float(cpu_raw), 1),
            "mem": rss,
            "mem_pct": round(mem_pct, 2),
            "threads": threads,
            "handles": handles,
            "user": user,
            "status": STATUS_RU.get(status, str(status)),
            "session": session,
            "started": format_timestamp(create_time) if create_time else "—",
            "started_ts": create_time,
            "window": window_title,
            "exe": exe,
            "cmdline": entry["cmdline"] or "",
            "io_read": io_read,
            "io_write": io_write,
            "mem_text": format_bytes(rss),
            "cpu_text": f"{cpu_total:.1f}%",
            "mem_pct_text": f"{mem_pct:.1f}%",
        }

    # ------------------------------------------------------------------
    # Действия с процессами
    # ------------------------------------------------------------------
    @staticmethod
    def _proc(pid: int) -> psutil.Process:
        return psutil.Process(pid)

    def terminate(self, pid: int, force: bool = False) -> tuple[bool, str]:
        try:
            process = self._proc(pid)
            process.terminate()
            try:
                process.wait(timeout=2)
            except psutil.TimeoutExpired:
                if force:
                    process.kill()
                    process.wait(timeout=2)
                else:
                    return False, tr(
                        "Процесс не завершился за 2 секунды. "
                        "Попробуйте принудительное завершение."
                    )
            return True, tr("Процесс завершён")
        except psutil.NoSuchProcess:
            return True, tr("Процесс уже завершён")
        except psutil.AccessDenied:
            return False, tr(
                "Недостаточно прав. Запустите монитор от администратора."
            )
        except Exception as exc:
            return False, tr("Ошибка: {error}", error=exc)

    def suspend(self, pid: int) -> tuple[bool, str]:
        try:
            self._proc(pid).suspend()
            return True, tr("Процесс приостановлен")
        except psutil.AccessDenied:
            return False, tr("Недостаточно прав для приостановки процесса")
        except psutil.NoSuchProcess:
            return False, tr("Процесс не найден")
        except Exception as exc:
            return False, tr("Ошибка: {error}", error=exc)

    def resume(self, pid: int) -> tuple[bool, str]:
        try:
            self._proc(pid).resume()
            return True, tr("Процесс продолжен")
        except psutil.AccessDenied:
            return False, tr("Недостаточно прав для продолжения процесса")
        except psutil.NoSuchProcess:
            return False, tr("Процесс не найден")
        except Exception as exc:
            return False, tr("Ошибка: {error}", error=exc)

    def set_priority(self, pid: int, priority_name: str) -> tuple[bool, str]:
        priority = PRIORITIES.get(priority_name)
        if priority is None:
            return False, tr("Неизвестный приоритет")
        try:
            self._proc(pid).nice(priority)
            return True, tr(
                "Приоритет изменён: {priority}", priority=tr(priority_name)
            )
        except psutil.AccessDenied:
            return False, tr("Недостаточно прав для смены приоритета")
        except psutil.NoSuchProcess:
            return False, tr("Процесс не найден")
        except Exception as exc:
            return False, tr("Ошибка: {error}", error=exc)

    # ------------------------------------------------------------------
    # Подробности
    # ------------------------------------------------------------------
    def describe(self, pid: int) -> dict[str, Any]:
        result: dict[str, Any] = {"pid": pid, "connections": []}
        try:
            proc = self._proc(pid)
            with proc.oneshot():
                result["name"] = proc.name()
                result["exe"] = self._safe(proc.exe, "")
                result["cmdline"] = " ".join(self._safe(proc.cmdline, []) or [])
                result["cwd"] = self._safe(proc.cwd, "")
                result["user"] = self._safe(proc.username, "")
                result["status"] = STATUS_RU.get(
                    self._safe(proc.status, "unknown"), "—"
                )
                result["ppid"] = self._safe(proc.ppid, 0)
                result["threads"] = self._safe(proc.num_threads, 0)
                result["handles"] = self._safe(proc.num_handles, 0)
                created = self._safe(proc.create_time, 0)
                result["created"] = format_timestamp(created)
                result["uptime"] = format_duration(
                    time.time() - (created or time.time())
                )
                memory = self._safe(proc.memory_info, None)
                if memory is not None:
                    result["rss"] = format_bytes(memory.rss)
                    result["vms"] = format_bytes(memory.vms)
                else:
                    result["rss"] = "—"
                    result["vms"] = "—"
                result["mem_pct"] = f"{self._safe(proc.memory_percent, 0.0):.2f}%"
                result["nice"] = self._safe(proc.nice, "—")
                try:
                    connections = proc.net_connections(kind="inet")
                except Exception:
                    connections = []
                result["connections"] = [
                    f"{self._endpoint(conn.laddr)} → {self._endpoint(conn.raddr)} "
                    f"[{conn.status or conn.type}]"
                    for conn in connections[:40]
                ]
                try:
                    result["open_files"] = len(proc.open_files())
                except Exception:
                    result["open_files"] = "—"
                result["priority_classes"] = list(PRIORITIES.keys())

            info = file_version_info(result.get("exe", ""))
            result.update({f"file_{key}": value for key, value in info.items()})
        except psutil.NoSuchProcess:
            result["error"] = "Процесс не найден"
        except psutil.AccessDenied:
            result["error"] = "Доступ запрещён (нужны права администратора)"
        except Exception as exc:
            result["error"] = str(exc)
        return result

    @staticmethod
    def _endpoint(addr) -> str:
        if not addr:
            return "*"
        try:
            host, port = addr
            if ":" in str(host):
                host = f"[{host}]"
            return f"{host}:{port}"
        except (TypeError, ValueError):
            return str(addr)

    @staticmethod
    def _safe(func, default):
        try:
            value = func()
            return default if value is None else value
        except Exception:
            return default

    def last_rows(self) -> list[dict[str, Any]]:
        return self._last_rows


