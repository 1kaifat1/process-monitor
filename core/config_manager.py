"""Хранение и применение пользовательских настроек (JSON)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]


def _config_dir() -> Path:
    """Папка настроек.

    В исходниках — ``config/`` рядом с проектом. В собранном EXE — ``config/``
    рядом с исполняемым файлом (portable-режим), а если папка недоступна для
    записи (например, Program Files) — ``%APPDATA%\\PulseMonitor\\config``.
    """
    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).resolve().parent / "config"
        try:
            portable.mkdir(parents=True, exist_ok=True)
            probe = portable / ".write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            return portable
        except OSError:
            base = Path(os.environ.get("APPDATA") or Path.home())
            return base / "PulseMonitor" / "config"
    return APP_DIR / "config"


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "settings.json"
BACKUP_FILE = CONFIG_DIR / "settings.backup.json"

PROCESS_COLUMNS = [
    ("pid", "PID", 70, True),
    ("name", "Имя", 230, True),
    ("flags", "Флаги", 140, True),
    ("cpu", "CPU %", 80, True),
    ("mem", "Память", 110, True),
    ("mem_pct", "Память %", 90, True),
    ("threads", "Потоки", 80, False),
    ("handles", "Дескрипторы", 100, False),
    ("user", "Пользователь", 170, False),
    ("status", "Статус", 120, True),
    ("session", "Сессия", 80, False),
    ("ppid", "PPID", 70, False),
    ("started", "Запущен", 150, False),
    ("window", "Окно", 220, False),
    ("exe", "Путь", 380, False),
]

DEFAULTS: dict[str, Any] = {
    "language": "ru",
    "theme": "dark",
    "accent": "#00f0ff",
    "font_size": 13,
    "intervals": {
        "processes": 2000,
        "network": 2500,
        "dashboard": 1200,
    },
    "processes": {
        "columns": {key: visible for key, _title, _width, visible in PROCESS_COLUMNS},
        "show_system": True,
        "mode": "all",
        "confirm_kill": True,
        "sort_column": "cpu",
        "sort_order": "desc",
    },
    "network": {
        "only_established": False,
        "hide_loopback": True,
    },
    "behavior": {
        "close_to_tray": True,
        "start_minimized": False,
        "autostart_app": False,
        "remember_geometry": True,
        "slow_when_inactive": True,
        "explorer_integration": False,
    },
    "window": {
        "width": 1320,
        "height": 840,
        "x": None,
        "y": None,
        "maximized": False,
        "last_page": 0,
    },
    "disabled_autoruns": [],
}


def _deep_merge(base: dict, incoming: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ConfigManager:
    """Простой менеджер настроек с доступом по точечному пути."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            self.save()
            return
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            self._data = _deep_merge(DEFAULTS, raw if isinstance(raw, dict) else {})
        except (OSError, json.JSONDecodeError):
            self._data = copy.deepcopy(DEFAULTS)
            try:
                shutil.copy2(CONFIG_FILE, BACKUP_FILE)
            except OSError:
                pass

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            temp = CONFIG_FILE.with_suffix(".tmp")
            temp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp.replace(CONFIG_FILE)
            return True
        except OSError:
            return False

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, path: str, value: Any, *, save: bool = True) -> None:
        parts = path.split(".")
        node = self._data
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        if save:
            self.save()

    def update(self, values: dict[str, Any], *, save: bool = True) -> None:
        self._data = _deep_merge(self._data, values)
        if save:
            self.save()

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def reset(self) -> None:
        self._data = copy.deepcopy(DEFAULTS)
        self.save()

    # ------------------------------------------------------------------
    # Экспорт / импорт
    # ------------------------------------------------------------------
    def export_to(self, path: str) -> bool:
        try:
            Path(path).write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except OSError:
            return False

    def import_from(self, path: str) -> bool:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return False
            self._data = _deep_merge(DEFAULTS, raw)
            self.save()
            return True
        except (OSError, json.JSONDecodeError):
            return False

    # ------------------------------------------------------------------
    # Отключённые элементы автозагрузки
    # ------------------------------------------------------------------
    def disabled_autoruns(self) -> list[dict]:
        value = self.get("disabled_autoruns", [])
        return value if isinstance(value, list) else []

    def add_disabled_autorun(self, entry: dict) -> None:
        entries = self.disabled_autoruns()
        entries = [item for item in entries if item.get("id") != entry.get("id")]
        entries.append(entry)
        self.set("disabled_autoruns", entries)

    def remove_disabled_autorun(self, entry_id: str) -> dict | None:
        entries = self.disabled_autoruns()
        found = None
        rest = []
        for item in entries:
            if item.get("id") == entry_id:
                found = item
            else:
                rest.append(item)
        if found is not None:
            self.set("disabled_autoruns", rest)
        return found


config = ConfigManager()

