"""Автозагрузка: реестр, папки «Автозагрузка», автоматические службы."""

from __future__ import annotations

import os
import re
import winreg
from pathlib import Path
from typing import Any

import psutil

from .config_manager import config
from .i18n import tr
from .utils import run_hidden

HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}

RUN_LOCATIONS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run", "Пользователь · Run"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "Пользователь · RunOnce"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run", "Система · Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "Система · RunOnce"),
    (
        "HKLM",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
        "Система x86 · Run",
    ),
]

STARTUP_DIRS = [
    (
        "Пользователь",
        Path(os.environ.get("APPDATA", ""))
        / r"Microsoft\Windows\Start Menu\Programs\Startup",
    ),
    (
        "Все пользователи",
        Path(os.environ.get("PROGRAMDATA", ""))
        / r"Microsoft\Windows\Start Menu\Programs\Startup",
    ),
]


def extract_target(command: str) -> str:
    """Вытащить путь к исполняемому файлу из командной строки."""
    if not command:
        return ""
    text = os.path.expandvars(command.strip())
    match = re.match(r'^"([^"]+)"', text)
    if match:
        return match.group(1)
    match = re.match(r"^([A-Za-z]:\\[^\s]+?\.(?:exe|com|bat|cmd|scr|lnk))", text, re.I)
    if match:
        return match.group(1)
    token = text.split(" ", 1)[0].strip('"')
    return token


class AutorunManager:
    """Чтение и переключение элементов автозапуска."""

    def list_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        entries.extend(self._registry_entries())
        entries.extend(self._startup_folder_entries())
        entries.extend(self._service_entries())
        entries.extend(self._disabled_registry_entries())
        entries.sort(key=lambda item: (not item["enabled"], item["type"], item["name"].lower()))
        return entries

    # ------------------------------------------------------------------
    # Реестр
    # ------------------------------------------------------------------
    def _registry_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for hive_name, key_path, label in RUN_LOCATIONS:
            hive = HIVES[hive_name]
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _value_type = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        command = str(value)
                        entries.append(
                            {
                                "id": f"reg:{hive_name}:{key_path}:{name}",
                                "type": "Реестр",
                                "name": name,
                                "command": command,
                                "location": f"{hive_name}\\{key_path}",
                                "location_label": label,
                                "enabled": True,
                                "can_toggle": True,
                                "target": extract_target(command),
                                "note": "",
                                "extra": {
                                    "hive": hive_name,
                                    "key": key_path,
                                    "value_name": name,
                                    "command": command,
                                },
                            }
                        )
            except FileNotFoundError:
                continue
            except OSError:
                continue
        return entries

    def _disabled_registry_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for record in config.disabled_autoruns():
            if record.get("type") != "Реестр":
                continue
            extra = record.get("extra", {})
            entries.append(
                {
                    "id": record.get("id", ""),
                    "type": "Реестр",
                    "name": record.get("name", "—"),
                    "command": extra.get("command", record.get("command", "")),
                    "location": f"{extra.get('hive', '')}\\{extra.get('key', '')}",
                    "location_label": record.get("location_label", "Отключено"),
                    "enabled": False,
                    "can_toggle": True,
                    "target": extract_target(extra.get("command", "")),
                    "note": "отключено монитором",
                    "extra": extra,
                }
            )
        return entries

    # ------------------------------------------------------------------
    # Папки автозагрузки
    # ------------------------------------------------------------------
    def _startup_folder_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        skip = {"desktop.ini", "thumbs.db"}
        for scope, directory in STARTUP_DIRS:
            try:
                if not directory or not directory.is_dir():
                    continue
                for item in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
                    if not item.is_file() or item.name.lower() in skip:
                        continue
                    disabled = item.name.lower().endswith(".disabled")
                    display_name = item.name[:-9] if disabled else item.name
                    entries.append(
                        {
                            "id": f"folder:{str(item).lower()}",
                            "type": "Папка",
                            "name": display_name,
                            "command": str(item),
                            "location": f"{scope}: {directory}",
                            "location_label": "Автозагрузка",
                            "enabled": not disabled,
                            "can_toggle": True,
                            "target": str(item),
                            "note": "отключено монитором" if disabled else "",
                            "extra": {"path": str(item), "disabled": disabled},
                        }
                    )
            except OSError:
                continue
        return entries

    # ------------------------------------------------------------------
    # Службы
    # ------------------------------------------------------------------
    def _service_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            services = psutil.win_service_iter()
        except Exception:
            return entries
        for service in services:
            try:
                info = service.as_dict()
            except Exception:
                continue
            if info.get("start_type") != "automatic":
                continue
            name = info.get("name") or "—"
            entries.append(
                {
                    "id": f"service:{name}",
                    "type": "Служба",
                    "name": info.get("display_name") or name,
                    "command": info.get("binpath") or "",
                    "location": "Службы Windows · автозапуск",
                    "location_label": f"sc: {name}",
                    "enabled": True,
                    "can_toggle": True,
                    "target": extract_target(info.get("binpath") or ""),
                    "note": info.get("status") or "",
                    "extra": {"service": name},
                }
            )
        return entries

    # ------------------------------------------------------------------
    # Переключение
    # ------------------------------------------------------------------
    def toggle(self, entry: dict[str, Any]) -> tuple[bool, str]:
        if not entry.get("can_toggle"):
            return False, tr("Этот элемент нельзя изменить")
        entry_type = entry.get("type")
        if entry_type == "Реестр":
            return self._toggle_registry(entry)
        if entry_type == "Папка":
            return self._toggle_folder(entry)
        if entry_type == "Служба":
            return self._toggle_service(entry)
        return False, tr("Неизвестный тип элемента")

    @staticmethod
    def _open_key_for_write(hive, key_path: str):
        try:
            return winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            return winreg.CreateKeyEx(hive, key_path, 0, winreg.KEY_SET_VALUE)

    def _toggle_registry(self, entry: dict[str, Any]) -> tuple[bool, str]:
        extra = entry.get("extra", {})
        hive_name = extra.get("hive", "")
        key_path = extra.get("key", "")
        value_name = extra.get("value_name", "")
        hive = HIVES.get(hive_name)
        if hive is None or not key_path or not value_name:
            return False, tr("Недостаточно данных о записи реестра")

        if entry.get("enabled", True):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
            except PermissionError:
                return False, tr(
                    "Нужны права администратора для изменения этого ключа"
                )
            except OSError as exc:
                return False, tr("Не удалось отключить: {error}", error=exc)
            config.add_disabled_autorun(
                {
                    "id": entry["id"],
                    "type": "Реестр",
                    "name": entry["name"],
                    "location_label": entry.get("location_label", ""),
                    "command": entry.get("command", ""),
                    "extra": {
                        "hive": hive_name,
                        "key": key_path,
                        "value_name": value_name,
                        "command": entry.get("command", ""),
                    },
                }
            )
            return True, tr(
                "Элемент отключён. Значение сохранено в настройках монитора."
            )

        command = extra.get("command") or entry.get("command", "")
        try:
            with self._open_key_for_write(hive, key_path) as key:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
        except PermissionError:
            return False, tr(
                "Нужны права администратора для изменения этого ключа"
            )
        except OSError as exc:
            return False, tr("Не удалось включить: {error}", error=exc)
        config.remove_disabled_autorun(entry["id"])
        return True, tr("Элемент снова включён в автозагрузку")

    def _toggle_folder(self, entry: dict[str, Any]) -> tuple[bool, str]:
        path = Path(entry.get("extra", {}).get("path", ""))
        if not path or not path.exists():
            return False, tr("Файл автозагрузки не найден")
        try:
            if entry.get("enabled", True):
                if not path.name.lower().endswith(".disabled"):
                    path.rename(path.with_name(path.name + ".disabled"))
                return True, tr(
                    "Элемент отключён (файл переименован в .disabled)"
                )
            if path.name.lower().endswith(".disabled"):
                path.rename(path.with_name(path.name[:-9]))
            return True, tr("Элемент снова включён в автозагрузку")
        except PermissionError:
            return False, tr("Недостаточно прав для переименования файла")
        except OSError as exc:
            return False, tr("Не удалось изменить файл: {error}", error=exc)

    def _toggle_service(self, entry: dict[str, Any]) -> tuple[bool, str]:
        service_name = entry.get("extra", {}).get("service", "")
        if not service_name:
            return False, tr("Не найдено имя службы")
        action = "disabled" if entry.get("enabled", True) else "auto"
        code, out, err = run_hidden(["sc", "config", service_name, "start=", action])
        if code == 0:
            state = tr("отключена") if action == "disabled" else tr("включена")
            return True, tr(
                "Служба {state}. Изменения вступят в силу после перезагрузки.",
                state=state,
            )
        message = (err or out).strip()
        lowered = message.lower()
        if "отказано" in lowered or "access is denied" in lowered:
            return False, tr(
                "Нужны права администратора для изменения службы"
            )
        return False, message or tr("Не удалось изменить службу")


