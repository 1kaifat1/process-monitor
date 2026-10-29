"""Мониторинг сетевых соединений и скорости интерфейсов."""

from __future__ import annotations

import time
from typing import Any

import psutil

from .utils import format_bytes

FAMILY_NAMES = {2: "IPv4", 23: "IPv6"}


class NetworkCollector:
    """Считает скорость по дельте счётчиков и собирает таблицу соединений."""

    def __init__(self) -> None:
        self._prev_total = None
        self._prev_time: float | None = None
        self._prev_interfaces: dict[str, Any] = {}
        self._name_cache: dict[int, str] = {}
        self._last_payload: dict[str, Any] = {
            "connections": [], "stats": {}, "interfaces": []
        }

    def _process_name(self, pid: int | None) -> str:
        if pid is None:
            return "Система"
        if pid in self._name_cache:
            return self._name_cache[pid]
        try:
            name = psutil.Process(pid).name()
        except Exception:
            name = "—"
        self._name_cache[pid] = name
        if len(self._name_cache) > 2000:
            self._name_cache.clear()
        return name

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

    def snapshot(self) -> dict[str, Any]:
        now = time.perf_counter()
        try:
            total = psutil.net_io_counters()
        except Exception:
            total = None

        down_rate = 0.0
        up_rate = 0.0
        if (
            total is not None
            and self._prev_total is not None
            and self._prev_time is not None
        ):
            delta = max(now - self._prev_time, 0.001)
            down_rate = max(total.bytes_recv - self._prev_total.bytes_recv, 0) / delta
            up_rate = max(total.bytes_sent - self._prev_total.bytes_sent, 0) / delta
        self._prev_total = total
        self._prev_time = now

        interfaces = self._collect_interfaces(now)
        connections, conn_error = self._collect_connections()

        established = sum(1 for row in connections if row["status"] == "ESTABLISHED")
        listening = sum(1 for row in connections if row["status"] == "LISTEN")
        unique_processes = len(
            {row["pid"] for row in connections if row["pid"] is not None}
        )

        payload = {
            "connections": connections,
            "interfaces": interfaces,
            "stats": {
                "down_rate": down_rate,
                "up_rate": up_rate,
                "down_text": format_bytes(down_rate, per_second=True),
                "up_text": format_bytes(up_rate, per_second=True),
                "total_recv": format_bytes(total.bytes_recv if total else 0),
                "total_sent": format_bytes(total.bytes_sent if total else 0),
                "count": len(connections),
                "established": established,
                "listening": listening,
                "processes": unique_processes,
                "error": conn_error,
                "timestamp": time.time(),
            },
        }
        self._last_payload = payload
        return payload

    def _collect_connections(self) -> tuple[list[dict[str, Any]], str]:
        rows: list[dict[str, Any]] = []
        try:
            connections = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            return rows, "Нет прав на чтение всех соединений (нужен администратор)"
        except Exception as exc:
            return rows, f"Не удалось получить соединения: {exc}"

        for conn in connections:
            try:
                pid = conn.pid
                family = FAMILY_NAMES.get(int(conn.family), str(conn.family))
                kind = "TCP" if str(conn.type).endswith("SOCK_STREAM") else "UDP"
                status = conn.status or "—"
                local = self._endpoint(conn.laddr)
                remote = self._endpoint(conn.raddr)
                name = self._process_name(pid)
                rows.append(
                    {
                        "pid": pid,
                        "process": name,
                        "local": local,
                        "remote": remote,
                        "status": status,
                        "family": family,
                        "kind": kind,
                        "loopback": local.startswith(("127.", "::1", "[::1]"))
                        or remote.startswith(("127.", "::1", "[::1]")),
                        "remote_ip": conn.raddr[0] if conn.raddr else "",
                    }
                )
            except Exception:
                continue

        order = {"ESTABLISHED": 0, "SYN_SENT": 1, "LISTEN": 2}
        rows.sort(key=lambda item: (order.get(item["status"], 3), item["process"].lower()))
        return rows, ""

    def _collect_interfaces(self, now: float) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        try:
            counters = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
            addresses = psutil.net_if_addrs()
        except Exception:
            return result

        for name, counter in counters.items():
            previous = self._prev_interfaces.get(name)
            down = up = 0.0
            if previous is not None:
                previous_counter, previous_time = previous
                delta = max(now - previous_time, 0.001)
                down = max(counter.bytes_recv - previous_counter.bytes_recv, 0) / delta
                up = max(counter.bytes_sent - previous_counter.bytes_sent, 0) / delta
            self._prev_interfaces[name] = (counter, now)

            ipv4 = ""
            for addr in addresses.get(name, []):
                if addr.family == 2:
                    ipv4 = addr.address
                    break

            stat = stats.get(name)
            result.append(
                {
                    "name": name,
                    "ip": ipv4 or "—",
                    "up": bool(stat.isup) if stat else False,
                    "speed": f"{stat.speed} Мбит/с" if stat and stat.speed else "—",
                    "down": format_bytes(down, per_second=True),
                    "up_rate": format_bytes(up, per_second=True),
                    "received": format_bytes(counter.bytes_recv),
                    "sent": format_bytes(counter.bytes_sent),
                }
            )
        result.sort(key=lambda item: item["name"].lower())
        return result

    def last_payload(self) -> dict[str, Any]:
        return self._last_payload

