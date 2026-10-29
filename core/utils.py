"""Вспомогательные функции: форматирование, CSV, запуск процессов."""

from __future__ import annotations

import csv
import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Форматирование значений
# ---------------------------------------------------------------------------
_BYTE_UNITS = ("Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ")


def format_bytes(value, per_second: bool = False) -> str:
    """Человекочитаемый размер: 1024 -> '1.0 КБ'."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number < 0:
        number = 0.0
    index = 0
    while number >= 1024 and index < len(_BYTE_UNITS) - 1:
        number /= 1024.0
        index += 1
    if index == 0:
        text = f"{number:.0f} {_BYTE_UNITS[index]}"
    elif number >= 100:
        text = f"{number:.0f} {_BYTE_UNITS[index]}"
    else:
        text = f"{number:.1f} {_BYTE_UNITS[index]}"
    return text + ("/с" if per_second else "")


def format_percent(value) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def format_duration(seconds) -> str:
    """Длительность в формате '2д 03:04:05'."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds < 0:
        seconds = 0
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}д {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_timestamp(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%d.%m.%Y %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "—"


def format_number(value) -> str:
    try:
        return f"{float(value):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# Системные операции
# ---------------------------------------------------------------------------
def is_admin() -> bool:
    """Запущено ли приложение с правами администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Перезапуск приложения с UAC-повышением прав.

    В собранном EXE ``sys.executable`` уже указывает на PulseMonitor.exe,
    поэтому аргументы не нужны; в исходниках передаём путь к main.py.
    """
    try:
        executable = sys.executable
        if getattr(sys, "frozen", False):
            params = ""
        else:
            params = " ".join(f'"{arg}"' for arg in sys.argv)
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, str(Path.cwd()), 1
        )
        return int(result) > 32
    except Exception:
        return False


def open_in_explorer(path: str) -> bool:
    """Открыть проводник с выделением файла."""
    if not path:
        return False
    target = Path(path)
    try:
        if target.exists():
            subprocess.Popen(["explorer", "/select,", str(target)])
            return True
        if target.parent.exists():
            os.startfile(str(target.parent))  # noqa: S606 - Windows shell
            return True
    except Exception:
        return False
    return False


def open_path(path: str) -> bool:
    try:
        if path and Path(path).exists():
            os.startfile(str(path))  # noqa: S606 - Windows shell
            return True
    except Exception:
        return False
    return False


def run_hidden(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Запуск консольной утилиты без мигающего окна."""
    creation_flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=creation_flags,
            check=False,
        )
        encoding = "cp866" if os.name == "nt" else "utf-8"
        out = completed.stdout.decode(encoding, errors="replace")
        err = completed.stderr.decode(encoding, errors="replace")
        return completed.returncode, out, err
    except FileNotFoundError:
        return 1, "", "Утилита не найдена"
    except subprocess.TimeoutExpired:
        return 1, "", "Превышено время ожидания"
    except Exception as exc:  # pragma: no cover - редкие системные ошибки
        return 1, "", str(exc)


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------
def export_csv(path: str, headers: list[str], rows: list[list]) -> bool:
    """Сохранить таблицу в CSV (UTF-8 с BOM — корректно открывается в Excel)."""
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(headers)
            writer.writerows(rows)
        return True
    except OSError:
        return False


def now_ms() -> int:
    return int(time.time() * 1000)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def shorten(text: str, limit: int = 80) -> str:
    if text is None:
        return ""
    text = str(text)
    if limit and len(text) > limit:
        return text[: limit - 1] + "…"
    return text
