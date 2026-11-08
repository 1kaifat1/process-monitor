"""Быстрая самопроверка без запуска окна: python selfcheck.py"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from core.app_identity import APP_USER_MODEL_ID, icon_path, start_menu_shortcut_path
from core.autorun_manager import AutorunManager
from core.cleaner_engine import (
    analyze_disk_space,
    collect_active_processes_for_disk,
    delete_path_forced,
    find_duplicates,
    find_processes_for_path,
    is_safe_delete_path,
    list_volumes,
    scan_custom_filter,
    scan_quick_clean,
    send_to_recycle_bin,
    terminate_processes_in_path_and_delete,
)
from core.config_manager import config
from core.gpu_monitor import GPUMonitor
from core.i18n import active_language, apply_config_language, tr
from core.net_collector import NetworkCollector
from core.process_collector import ProcessCollector
from core.process_kb import describe_process
from core.ram_cleaner import RamCleanResult, clean_ram
from core.system_stats import collect_system_stats, system_info
from core.winapi import query_process_image_path

FAILURES: list[str] = []


def _configure_console_output() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            continue


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    _configure_console_output()
    apply_config_language()
    print("Pulse Monitor 2.0 (Monitor + Cleaner) self-check")
    print("-" * 60)

    try:
        import PyQt6  # noqa: F401

        check("PyQt6 установлен", True)
    except Exception as exc:
        check("PyQt6 установлен", False, str(exc))

    # 1. Процессы и база знаний «Что делает процесс»
    process_collector = ProcessCollector()
    process_collector.snapshot()
    time.sleep(0.15)
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
        "Есть PID/имя/память/описание («Что делает процесс»)",
        all(
            key in payload["rows"][0]
            for key in ("pid", "name", "description", "kb_safety", "mem", "cpu", "flags", "exe")
        ),
    )
    with_exe = sum(1 for r in payload["rows"] if r.get("exe"))
    check(
        "Пути EXE определяются (включая службы Session 0)",
        with_exe > 15,
        f"путь найден у {with_exe}/{stats['total']} процессов",
    )
    own_path = query_process_image_path(os.getpid())
    check(
        "WinAPI QueryFullProcessImageNameW работает",
        bool(own_path and os.path.isfile(own_path)),
        own_path,
    )

    kb_svchost = describe_process("svchost.exe", r"C:\Windows\System32\svchost.exe", 100, 0, ["Dhcp", "Dnscache"])
    check(
        "База знаний процессов (svchost + службы)",
        "Dhcp" in kb_svchost["summary"] and kb_svchost["safety"] == "caution",
        kb_svchost["summary"],
    )

    check(
        "Классификация скрытых процессов работает",
        any("скрыт" in row["flags"] for row in payload["rows"]),
        f"скрытых: {stats['hidden']}",
    )

    fake_system = os.path.join(
        os.environ.get("TEMP", "C:\\Temp"), "svchost.exe"
    )
    check(
        "Эвристика подозрительных процессов",
        bool(ProcessCollector._exe_reasons(fake_system, "svchost.exe")),
        ", ".join(ProcessCollector._exe_reasons(fake_system, "svchost.exe")),
    )

    # 2. Защита путей HARDBLOCK и движок очистки
    safe_sys32, _ = is_safe_delete_path(r"C:\Windows\System32\ntoskrnl.exe")
    safe_root, _ = is_safe_delete_path(r"C:\\")
    safe_wintemp, _ = is_safe_delete_path(r"C:\Windows\Temp\pulse_test.tmp")
    check(
        "HARDBLOCK блокирует удаление System32 и корня диска",
        (not safe_sys32) and (not safe_root) and safe_wintemp,
    )

    qscan = scan_quick_clean()
    check(
        "Быстрая очистка: сканирование категорий",
        len(qscan.get("categories", [])) >= 10,
        f"категорий: {len(qscan.get('categories', []))}, найдено: {qscan.get('total_files', 0)} файл.",
    )

    vols = list_volumes()
    check("Тома диска определены", len(vols) >= 1, ", ".join(v["letter"] + ":" for v in vols))

    # Проверка точечной очистки, анализатора диска и поиска дубликатов во временной песочнице
    with tempfile.TemporaryDirectory(prefix="pulse_selftest_") as tmp_dir:
        p1 = Path(tmp_dir) / "sub1"
        p2 = Path(tmp_dir) / "sub2"
        p1.mkdir()
        p2.mkdir()
        payload_bytes = b"PulseMonitorDuplicateTestContent!" * 4096  # ~135 KB
        f1 = p1 / "report.log"
        f2 = p2 / "report_copy.log"
        f3 = p2 / "unique.tmp"
        f1.write_bytes(payload_bytes)
        f2.write_bytes(payload_bytes)
        f3.write_bytes(b"unique_data" * 1024)

        custom_hits = scan_custom_filter(
            root_paths=[tmp_dir],
            extensions={".log", ".tmp"},
            min_size_bytes=1024,
        )
        check("Точечная очистка: поиск по фильтрам", len(custom_hits) == 3, f"найдено {len(custom_hits)}")

        disk_res = analyze_disk_space(tmp_dir)
        check(
            "Анализатор диска WizTree (дерево папок + файлов + процессы)",
            disk_res["summary"]["files_count"] == 3
            and len(disk_res["top_files"]) == 3
            and "proc_count" in disk_res["root"],
            f"файлов: {disk_res['summary']['files_count']}, узлов: {len(disk_res['root'].get('children', []))}",
        )

        active_procs = collect_active_processes_for_disk()
        py_dir = str(Path(sys.executable).parent)
        matched_py = find_processes_for_path(py_dir, active_procs)
        check(
            "Привязка активных процессов к папкам WizTree",
            isinstance(active_procs, list) and isinstance(matched_py, list),
            f"активных процессов с путями: {len(active_procs)}, в папке Python: {len(matched_py)}",
        )

        dup_res = find_duplicates(tmp_dir, min_size_bytes=1024)
        check(
            "Поиск дубликатов (3-этапный SHA-1)",
            dup_res["total_groups"] == 1 and dup_res["total_duplicate_files"] == 1,
            f"групп: {dup_res['total_groups']}, дубликатов: {dup_res['total_duplicate_files']}",
        )

        f4 = p2 / "trash_test.tmp"
        f4.write_bytes(b"recycle_bin_test" * 64)
        trash_res = send_to_recycle_bin(str(f4))
        check(
            "Удаление в Корзину Windows (SHFileOperationW)",
            trash_res["ok"] and not f4.exists(),
        )

        del_res = terminate_processes_in_path_and_delete(str(f3), shred_passes=1)
        check("Шредер и принудительное удаление файла", del_res["ok"] and not f3.exists())

    # 3. Сеть, автозагрузка, GPU, ОЗУ и UI-модули
    network_collector = NetworkCollector()
    network_collector.snapshot()
    time.sleep(0.1)
    net = network_collector.snapshot()
    check("Сеть опрошена", "stats" in net, f"соединений: {net['stats']['count']}")
    check("Интерфейсы найдены", len(net["interfaces"]) >= 1)

    autorun = AutorunManager()
    entries = autorun.list_entries()
    check("Автозагрузка прочитана", len(entries) > 0, f"{len(entries)} элементов")

    stats_system = collect_system_stats()
    check("Системные метрики", 0 <= stats_system["cpu"] <= 100)
    check("Информация о системе", bool(system_info()["hostname"]))

    gpu_monitor = GPUMonitor()
    gpu_stats = gpu_monitor.get_stats()
    check(
        "GPU-мониторинг не падает",
        gpu_stats is None or gpu_stats.get("available") is True,
        str(gpu_stats.get("name")) if gpu_stats else "GPU: N/A",
    )
    gpu_monitor.shutdown()
    check(
        "RAM Cleaner доступен",
        callable(clean_ram) and RamCleanResult("success").ok,
    )
    check("Конфигурация загружается", config.get("theme") in ("dark", "light"))
    check(
        "Локализация работает",
        active_language() in ("ru", "en")
        and tr("Процессы") in ("Процессы", "Processes"),
        f"{active_language()} · «{tr('Процессы')}»",
    )

    icon_file = icon_path()
    check(
        "Иконка assets/pulse.ico на месте",
        icon_file is not None
        and icon_file.read_bytes()[:4] == b"\x00\x00\x01\x00",
        str(icon_file),
    )
    check("AUMID для панели задач", bool(APP_USER_MODEL_ID), APP_USER_MODEL_ID)
    check(
        "Каталог меню «Пуск» доступен",
        start_menu_shortcut_path().parent.is_dir(),
        str(start_menu_shortcut_path()),
    )

    try:
        from ui.main_window import PAGES, MainWindow  # noqa: F401
        from ui.widgets.cleaner_view import CleanerView  # noqa: F401
        from ui.widgets.disk_analyzer_view import DiskAnalyzerView  # noqa: F401
        from ui.widgets.precise_cleaner_view import PreciseCleanerView  # noqa: F401

        check("Все 7 вкладок UI импортируются без ошибок", len(PAGES) == 7, f"вкладок: {len(PAGES)}")
    except Exception as exc:
        check("Все 7 вкладок UI импортируются без ошибок", False, str(exc))

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
