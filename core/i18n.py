"""Лёгкая локализация интерфейса без внешних файлов и Qt Linguist.

Исходные строки — русские; для английского используется словарь
``core.translations_en.EN``. Перевод применяется при создании виджетов,
поэтому смена языка пересоздаёт главное окно (см. MainWindow.apply_language).

Использование::

    from core.i18n import tr
    label.setText(tr("Процессы"))
    label.setText(tr("Скрытых: {count}", count=5))
"""

from __future__ import annotations

import ctypes
import os

from core.translations_en import EN

SUPPORTED = ("ru", "en")
LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}

_current = "auto"


def system_language() -> str:
    """Язык системы: русский для русской локали Windows, иначе английский."""
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return "ru" if lang_id == 0x19 else "en"
    except Exception:
        locale = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
        return "ru" if locale.startswith("ru") else "en"


def set_language(code: str) -> None:
    global _current
    code = (code or "auto").lower()
    _current = code if code in (*SUPPORTED, "auto") else "auto"


def language() -> str:
    """Выбранный режим: ``auto``, ``ru`` или ``en``."""
    return _current


def active_language() -> str:
    """Фактический язык с учётом автоопределения."""
    return system_language() if _current == "auto" else _current


def apply_config_language() -> None:
    from core.config_manager import config

    set_language(str(config.get("language", "auto")))


def tr(text: str, **params) -> str:
    """Перевести строку и подставить параметры ``{name}``."""
    translated = EN.get(text, text) if active_language() == "en" else text
    if params:
        try:
            return translated.format(**params)
        except (KeyError, IndexError, ValueError):
            return translated
    return translated
