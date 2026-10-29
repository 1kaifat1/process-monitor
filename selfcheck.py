"""Быстрая самопроверка без запуска окна: python selfcheck.py"""

from __future__ import annotations

import sys
import time

from core.autorun_manager import AutorunManager
from core.config_manager import config
from core.net_collector import NetworkCollector
from core.process_collector import ProcessCollector
from core.system_stats import collect_system_stats, system_info

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    print("Pulse Monitor self-check")
    print("-" * 60)

    try:
        import PyQt6  # noqa: F401

        check("PyQt6 установлен", True)
    except Exception as exc:
        check("PyQt6 установлен", False, str(exc))

    process_collector = ProcessCollector()
    process_collector.snapshot()
    time.sleep(0.2)
    started = time.perf_counter()
    payload = process_collector.snapshot()
    elapsed_ms = (time.perf_counter() - started) * 1000
    stats = payload["stats"]
    check("Процессы собраны", stats["total"] > 20, f"{stats['total']} шт.")
    check(
        "Снимок процессов быстрый",
        elapsed_ms < 500,
        f"{elapsed_ms:.0f} мс (порог 500 мс)",
    )
    check(
        "Есть PID/имя/память",
        all(
            key in payload["rows"][0]
            for key in ("pid", "name", "mem", "cpu", "flags")
        ),
    )
    check(
        "Классификация скрытых процессов работает",
        any("скрыт" in row["flags"] for row in payload["rows"]),
        f"скрытых: {stats['hidden']}",
    )
    import os

    fake_system = os.path.join(
        os.environ.get("TEMP", "C:\\Temp"), "svchost.exe"
    )
    check(
        "Эвристика подозрительных процессов",
        bool(ProcessCollector._exe_reasons(fake_system, "svchost.exe")),
        ", ".join(ProcessCollector._exe_reasons(fake_system, "svchost.exe")),
    )

    network_collector = NetworkCollector()
    network_collector.snapshot()
    time.sleep(0.2)
    net = network_collector.snapshot()
    check("Сеть опрошена", "stats" in net, f"соединений: {net['stats']['count']}")
    check("Интерфейсы найдены", len(net["interfaces"]) >= 1)

    autorun = AutorunManager()
    entries = autorun.list_entries()
    check("Автозагрузка прочитана", len(entries) > 0, f"{len(entries)} элементов")
    check(
        "Есть записи разных типов",
        len({entry["type"] for entry in entries}) >= 2,
        str(sorted({entry["type"] for entry in entries})),
    )

    stats_system = collect_system_stats()
    check("Системные метрики", 0 <= stats_system["cpu"] <= 100)
    check("Информация о системе", bool(system_info()["hostname"]))
    check("Конфигурация загружается", config.get("theme") in ("dark", "light"))

    print("-" * 60)
    if FAILURES:
        print("Провалено проверок:", len(FAILURES))
        for label in FAILURES:
            print(" -", label)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
