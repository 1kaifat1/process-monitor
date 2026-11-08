"""Движок очистки системы, точечного поиска мусора, разблокировки, SSD TRIM и анализа диска."""

from __future__ import annotations

import ctypes
import fnmatch
import hashlib
import heapq
import os
import shutil
import stat
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .file_unlocker import find_locking_processes, force_unlock
from .utils import is_admin, run_hidden

APP_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# WinAPI для Корзины Windows (shell32)
# ---------------------------------------------------------------------------
SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


if os.name == "nt":
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _shell32.SHQueryRecycleBinW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(_SHQUERYRBINFO),
    ]
    _shell32.SHQueryRecycleBinW.restype = ctypes.c_long
    _shell32.SHEmptyRecycleBinW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    _shell32.SHEmptyRecycleBinW.restype = ctypes.c_long
    _shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
    _shell32.SHFileOperationW.restype = ctypes.c_int
else:
    _shell32 = None


def send_to_recycle_bin(target_path: str | Path) -> dict[str, Any]:
    """Отправляет файл или папку в Корзину Windows (с проверкой безопасности HARDBLOCK)."""
    raw = str(target_path or "").strip().strip('"')
    safe, reason = is_safe_delete_path(raw)
    if not safe:
        return {"ok": False, "freed_bytes": 0, "error": reason}
    if not os.path.exists(raw):
        return {"ok": False, "freed_bytes": 0, "error": "Файл или папка уже не существует"}
    if _shell32 is None:
        return {"ok": False, "freed_bytes": 0, "error": "Корзина Windows недоступна"}

    est_size = 0
    try:
        if os.path.isfile(raw):
            est_size = int(os.path.getsize(raw))
    except OSError:
        pass

    abs_path = os.path.abspath(raw).rstrip("\\/")
    # pFrom требует двойной нулевой терминатор \0\0
    buf = ctypes.create_unicode_buffer(abs_path + "\0\0")
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None
    try:
        res = int(_shell32.SHFileOperationW(ctypes.byref(op)))
        if res == 0 and not op.fAnyOperationsAborted and not os.path.exists(abs_path):
            return {"ok": True, "freed_bytes": est_size, "error": ""}
        return {
            "ok": False,
            "freed_bytes": 0,
            "error": (
                f"Не удалось переместить в Корзину (код {res}). "
                "Возможно, файл занят процессом — используйте «Удалить навсегда (с авто-завершением процессов)»."
            ),
        }
    except Exception as exc:
        return {"ok": False, "freed_bytes": 0, "error": str(exc)}


def query_recycle_bin() -> tuple[int, int]:
    """Возвращает (размер_в_байтах, количество_элементов) в Корзине Windows."""
    if _shell32 is None:
        return 0, 0
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
    try:
        res = _shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if res == 0:
            return max(0, int(info.i64Size)), max(0, int(info.i64NumItems))
    except Exception:
        pass
    return 0, 0


def empty_recycle_bin() -> tuple[bool, int, int]:
    """Очищает Корзину Windows без диалогов и возвращает (ok, freed_bytes, count)."""
    size_before, count_before = query_recycle_bin()
    if count_before == 0 and size_before == 0:
        return True, 0, 0
    if _shell32 is None:
        return False, 0, 0
    try:
        flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        res = _shell32.SHEmptyRecycleBinW(None, None, flags)
        # S_OK (0) или E_UNEXPECTED (-2147418113 когда корзина уже пуста)
        if res == 0 or size_before == 0:
            return True, size_before, count_before
        size_after, _ = query_recycle_bin()
        freed = max(0, size_before - size_after)
        return freed > 0, freed, count_before
    except Exception:
        return False, 0, 0


# ---------------------------------------------------------------------------
# Защита критических путей (HARDBLOCK)
# ---------------------------------------------------------------------------
WINDIR = os.path.normcase(os.path.normpath(os.environ.get("SystemRoot", r"C:\Windows")))
SAFE_WINDIR_SUBDIRS = tuple(
    os.path.normcase(os.path.join(WINDIR, sub))
    for sub in (
        "Temp",
        "Prefetch",
        r"SoftwareDistribution\Download",
        "LiveKernelReports",
        "Minidump",
    )
)

PROTECTED_EXACT_DIRS: set[str] = {
    WINDIR,
    os.path.normcase(os.path.normpath(os.environ.get("ProgramFiles", r"C:\Program Files"))),
    os.path.normcase(os.path.normpath(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))),
    os.path.normcase(os.path.normpath(os.environ.get("ProgramData", r"C:\ProgramData"))),
    os.path.normcase(os.path.normpath(str(Path.home()))),
    os.path.normcase(os.path.normpath(str(Path.home().parent))),
    os.path.normcase(os.path.normpath(str(Path.home() / "Desktop"))),
    os.path.normcase(os.path.normpath(str(Path.home() / "Documents"))),
    os.path.normcase(os.path.normpath(str(Path.home() / "Downloads"))),
    os.path.normcase(os.path.normpath(str(APP_ROOT))),
}

CRITICAL_WINDIR_SUBDIRS = tuple(
    os.path.normcase(os.path.join(WINDIR, sub))
    for sub in (
        "System32",
        "SysWOW64",
        "WinSxS",
        "Boot",
        "Fonts",
        "INF",
        "servicing",
        "SystemApps",
        "immersivecontrolpanel",
    )
)


def is_safe_delete_path(path: str | Path) -> tuple[bool, str]:
    """
    Проверяет, безопасно ли удалять указанный файл или папку.
    Блокирует корни дисков, системные папки Windows (кроме Temp/Prefetch/Download),
    корни профилей и папку самого приложения Pulse Monitor.
    """
    raw = str(path or "").strip().strip('"')
    if not raw:
        return False, "Путь не указан"
    try:
        resolved = Path(raw).resolve()
    except OSError:
        resolved = Path(os.path.abspath(raw))

    norm = os.path.normcase(os.path.normpath(str(resolved)))

    # 1. Корень диска (C:\, D:\)
    drive, tail = os.path.splitdrive(norm)
    if not tail or tail in ("\\", "/"):
        return False, f"Запрещено удалять корень диска ({drive}\\)"

    # 2. Точное совпадение с защищёнными корневыми каталогами
    if norm in PROTECTED_EXACT_DIRS:
        return False, f"Защищённый системный каталог ({resolved})"

    # 3. Защита самого запущенного приложения Pulse Monitor
    app_norm = os.path.normcase(os.path.normpath(str(APP_ROOT)))
    if norm == app_norm or norm.startswith(app_norm + "\\"):
        return False, "Нельзя удалить файлы запущенного приложения Pulse Monitor"
    if getattr(sys, "frozen", False):
        exe_dir = os.path.normcase(os.path.normpath(str(Path(sys.executable).resolve().parent)))
        if norm == exe_dir or norm.startswith(exe_dir + "\\"):
            return False, "Нельзя удалить папку запущенного PulseMonitor.exe"

    # 4. Внутри C:\Windows разрешены только безопасные временные подпапки
    if norm == WINDIR or norm.startswith(WINDIR + "\\"):
        for safe_sub in SAFE_WINDIR_SUBDIRS:
            if norm == safe_sub or norm.startswith(safe_sub + "\\"):
                return True, "OK"
        for crit_sub in CRITICAL_WINDIR_SUBDIRS:
            if norm == crit_sub or norm.startswith(crit_sub + "\\"):
                return False, f"Защищённый системный компонент Windows ({resolved})"
        return False, f"Защита системной папки Windows ({resolved})"

    return True, "OK"


# ---------------------------------------------------------------------------
# Безопасное и принудительное удаление файлов/папок (с разблокировкой и шредером)
# ---------------------------------------------------------------------------
def _clear_readonly(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _shred_file(path: str, passes: int = 1) -> None:
    """Перезаписывает содержимое файла нулями перед удалением (для HDD)."""
    if passes <= 0:
        return
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > 512 * 1024 * 1024:
            return
        _clear_readonly(path)
        chunk = b"\x00" * min(1024 * 1024, size)
        with open(path, "r+b", buffering=0) as fh:
            for _ in range(passes):
                fh.seek(0)
                remaining = size
                while remaining > 0:
                    write_len = min(len(chunk), remaining)
                    fh.write(chunk[:write_len])
                    remaining -= write_len
                fh.flush()
    except OSError:
        pass


def delete_single_file(
    file_path: str,
    *,
    shred_passes: int = 0,
    unlock_if_locked: bool = False,
) -> tuple[bool, int, list[int], str]:
    """Удаляет один файл, при необходимости разблокируя его через Restart Manager."""
    safe, reason = is_safe_delete_path(file_path)
    if not safe:
        return False, 0, [], reason

    unlocked_pids: list[int] = []
    try:
        st = os.lstat(file_path)
        size = int(st.st_size)
    except FileNotFoundError:
        return True, 0, [], ""
    except OSError as exc:
        return False, 0, [], str(exc)

    _clear_readonly(file_path)
    if shred_passes > 0:
        _shred_file(file_path, passes=shred_passes)

    try:
        os.unlink(file_path)
        return True, size, unlocked_pids, ""
    except FileNotFoundError:
        return True, 0, unlocked_pids, ""
    except PermissionError as exc:
        if not unlock_if_locked:
            return False, 0, unlocked_pids, f"Файл занят другим процессом ({exc})"
        unlock_res = force_unlock(file_path)
        unlocked_pids = [p.pid for p in unlock_res.terminated]
        try:
            _clear_readonly(file_path)
            os.unlink(file_path)
            return True, size, unlocked_pids, ""
        except OSError as retry_exc:
            return False, 0, unlocked_pids, str(retry_exc)
    except OSError as exc:
        return False, 0, unlocked_pids, str(exc)


def delete_path_forced(
    target_path: str | Path,
    *,
    keep_root_dir: bool = False,
    shred_passes: int = 0,
    unlock_if_locked: bool = True,
) -> dict[str, Any]:
    """
    Удаляет файл или папку целиком (или только содержимое папки при keep_root_dir=True).
    При блокировке процессами автоматически снимает блокировку через Restart Manager.
    """
    raw = str(target_path or "").strip().strip('"')
    safe, reason = is_safe_delete_path(raw)
    if not safe:
        return {
            "ok": False,
            "freed_bytes": 0,
            "deleted_files": 0,
            "failed_files": 1,
            "unlocked_pids": [],
            "error": reason,
        }

    if not os.path.exists(raw):
        return {
            "ok": True,
            "freed_bytes": 0,
            "deleted_files": 0,
            "failed_files": 0,
            "unlocked_pids": [],
            "error": "",
        }

    if os.path.isfile(raw) or os.path.islink(raw):
        ok, freed, pids, err = delete_single_file(
            raw, shred_passes=shred_passes, unlock_if_locked=unlock_if_locked
        )
        return {
            "ok": ok,
            "freed_bytes": freed,
            "deleted_files": 1 if ok else 0,
            "failed_files": 0 if ok else 1,
            "unlocked_pids": pids,
            "error": err,
        }

    # Папка: если нужен принудительный анлок всей папки сразу
    unlocked_pids: list[int] = []
    if unlock_if_locked:
        try:
            holders = find_locking_processes(raw)
            if holders:
                res = force_unlock(raw, holders)
                unlocked_pids.extend(p.pid for p in res.terminated)
        except Exception:
            pass

    freed_bytes = 0
    deleted_files = 0
    failed_files = 0
    last_error = ""

    for root, dirs, files in os.walk(raw, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            ok, sz, pids, err = delete_single_file(
                fpath, shred_passes=shred_passes, unlock_if_locked=unlock_if_locked
            )
            if pids:
                for p in pids:
                    if p not in unlocked_pids:
                        unlocked_pids.append(p)
            if ok:
                freed_bytes += sz
                deleted_files += 1
            else:
                failed_files += 1
                last_error = err

        for dname in dirs:
            dpath = os.path.join(root, dname)
            try:
                _clear_readonly(dpath)
                os.rmdir(dpath)
            except OSError:
                pass

    if not keep_root_dir:
        try:
            _clear_readonly(raw)
            os.rmdir(raw)
        except OSError as exc:
            if failed_files == 0:
                last_error = str(exc)

    return {
        "ok": failed_files == 0,
        "freed_bytes": freed_bytes,
        "deleted_files": deleted_files,
        "failed_files": failed_files,
        "unlocked_pids": unlocked_pids,
        "error": last_error,
    }


# ---------------------------------------------------------------------------
# 1. БЫСТРАЯ ОЧИСТКА СИСТЕМЫ (Quick Cleaner)
# ---------------------------------------------------------------------------
def _expand_existing_dirs(patterns: list[str]) -> list[str]:
    """Раскрывает переменные окружения и '*' в путях (например профили браузеров)."""
    result: list[str] = []
    for raw in patterns:
        try:
            expanded = os.path.expandvars(raw)
            if "*" in expanded:
                base_parts = expanded.split("*")
                parent = Path(base_parts[0]).parent
                if parent.is_dir():
                    for match in parent.parent.glob(
                        os.path.relpath(expanded, str(parent.parent))
                    ):
                        try:
                            if match.exists():
                                result.append(str(match))
                        except OSError:
                            continue
            elif os.path.exists(expanded):
                result.append(expanded)
        except Exception:
            continue
    # Убираем дубликаты
    seen: set[str] = set()
    unique: list[str] = []
    for p in result:
        norm = os.path.normcase(os.path.normpath(p))
        if norm not in seen:
            seen.add(norm)
            unique.append(p)
    return unique


def get_quick_clean_definitions() -> list[dict[str, Any]]:
    """Категории быстрой очистки системы."""
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    roaming = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    progdata = os.environ.get("ProgramData", r"C:\ProgramData")
    user_temp = os.environ.get("TEMP") or os.path.join(local, "Temp")

    return [
        {
            "id": "user_temp",
            "title": "Временные файлы пользователя (%TEMP%)",
            "description": "Кэш установщиков, временные файлы открытых программ и распакованных архивов",
            "group": "Система Windows",
            "default_checked": True,
            "paths": [user_temp],
        },
        {
            "id": "win_temp",
            "title": "Системные временные файлы (Windows\\Temp)",
            "description": "Временные файлы системных служб и установщика Windows",
            "group": "Система Windows",
            "default_checked": True,
            "paths": [os.path.join(WINDIR, "Temp")],
        },
        {
            "id": "win_updates",
            "title": "Кэш скачанных обновлений Windows (SoftwareDistribution)",
            "description": "Уже установленные пакеты Центра обновления Windows",
            "group": "Система Windows",
            "default_checked": True,
            "paths": [os.path.join(WINDIR, "SoftwareDistribution", "Download")],
        },
        {
            "id": "wer_dumps",
            "title": "Отчёты об ошибках и дампы сбоев (WER & CrashDumps)",
            "description": "Дампы памяти упавших программ и отчёты Windows Error Reporting",
            "group": "Система Windows",
            "default_checked": True,
            "paths": [
                os.path.join(local, "CrashDumps"),
                os.path.join(local, "Microsoft", "Windows", "WER", "ReportArchive"),
                os.path.join(local, "Microsoft", "Windows", "WER", "ReportQueue"),
                os.path.join(local, "Microsoft", "Windows", "WER", "Temp"),
                os.path.join(progdata, "Microsoft", "Windows", "WER", "ReportArchive"),
                os.path.join(progdata, "Microsoft", "Windows", "WER", "ReportQueue"),
                os.path.join(progdata, "Microsoft", "Windows", "WER", "Temp"),
                os.path.join(WINDIR, "Minidump"),
                os.path.join(WINDIR, "LiveKernelReports"),
            ],
        },
        {
            "id": "wininet_cache",
            "title": "Временные файлы интернета (INetCache)",
            "description": "Системный сетевой кэш Windows и встроенных компонентов",
            "group": "Система Windows",
            "default_checked": True,
            "paths": [
                os.path.join(local, "Microsoft", "Windows", "INetCache"),
            ],
        },
        {
            "id": "shader_cache",
            "title": "Кэш шейдеров видеокарты (DirectX / NVIDIA / AMD)",
            "description": "Скомпилированные шейдеры игр и графики (безопасно пересоздаются при необходимости)",
            "group": "Графика и Проводник",
            "default_checked": True,
            "paths": [
                os.path.join(local, "D3DSCache"),
                os.path.join(local, "NVIDIA", "DXCache"),
                os.path.join(local, "NVIDIA", "GLCache"),
                os.path.join(local, "AMD", "DxCache"),
                os.path.join(local, "AMD", "GLCache"),
            ],
        },
        {
            "id": "thumbnails",
            "title": "Кэш миниатюр Проводника (thumbcache_*.db)",
            "description": "Базы эскизов изображений и видео в папках Windows",
            "group": "Графика и Проводник",
            "default_checked": False,
            "paths": [os.path.join(local, "Microsoft", "Windows", "Explorer")],
            "file_glob": "thumbcache_*.db",
        },
        {
            "id": "browser_chrome",
            "title": "Кэш Google Chrome (без удаления паролей и куки)",
            "description": "Кэш страниц, скриптов (Code Cache) и шейдеров GPU браузера Chrome",
            "group": "Браузеры",
            "default_checked": True,
            "paths": [
                os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache"),
                os.path.join(local, "Google", "Chrome", "User Data", "Default", "Code Cache"),
                os.path.join(local, "Google", "Chrome", "User Data", "Default", "GPUCache"),
                os.path.join(local, "Google", "Chrome", "User Data", "ShaderCache"),
                os.path.join(local, "Google", "Chrome", "User Data", "GrShaderCache"),
            ],
        },
        {
            "id": "browser_edge",
            "title": "Кэш Microsoft Edge и WebView2",
            "description": "Временный кэш страниц и кода Microsoft Edge (история и входы сохраняются)",
            "group": "Браузеры",
            "default_checked": True,
            "paths": [
                os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "GPUCache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "ShaderCache"),
            ],
        },
        {
            "id": "browser_other",
            "title": "Кэш Яндекс Браузера, Opera, Brave и Firefox",
            "description": "Файлы кэша страниц дополнительных браузеров без затрагивания сессий",
            "group": "Браузеры",
            "default_checked": True,
            "paths": [
                os.path.join(local, "Yandex", "YandexBrowser", "User Data", "Default", "Cache"),
                os.path.join(local, "Yandex", "YandexBrowser", "User Data", "Default", "Code Cache"),
                os.path.join(local, "Yandex", "YandexBrowser", "User Data", "Default", "GPUCache"),
                os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cache"),
                os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Code Cache"),
                os.path.join(local, "Opera Software", "Opera Stable", "Cache"),
                os.path.join(local, "Opera Software", "Opera GX Stable", "Cache"),
                os.path.join(roaming, "Opera Software", "Opera Stable", "Code Cache"),
                os.path.join(local, "Mozilla", "Firefox", "Profiles", "*", "cache2"),
            ],
        },
        {
            "id": "recycle_bin",
            "title": "Корзина Windows (Recycle Bin)",
            "description": "Окончательное удаление файлов, ранее перемещённых в Корзину на всех дисках",
            "group": "Система Windows",
            "default_checked": True,
            "is_recycle_bin": True,
            "paths": [],
        },
    ]


def _scan_dir_metrics(path: str, file_glob: str | None = None) -> tuple[int, int]:
    """Быстрый подсчёт (байты, количество_файлов) внутри папки через os.scandir."""
    total_bytes = 0
    total_files = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if not file_glob:
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if file_glob and not fnmatch.fnmatch(entry.name.lower(), file_glob.lower()):
                                continue
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            total_files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total_bytes, total_files


def scan_quick_clean() -> dict[str, Any]:
    """Сканирует все категории быстрой очистки и возвращает точный объём мусора."""
    started = time.perf_counter()
    categories: list[dict[str, Any]] = []
    total_bytes = 0
    total_files = 0

    for item in get_quick_clean_definitions():
        if item.get("is_recycle_bin"):
            rb_bytes, rb_count = query_recycle_bin()
            cat_row = {
                **item,
                "resolved_paths": ["Корзина Windows"],
                "size_bytes": rb_bytes,
                "files_count": rb_count,
            }
        else:
            existing = _expand_existing_dirs(item.get("paths", []))
            cat_bytes = 0
            cat_files = 0
            file_glob = item.get("file_glob")
            for folder in existing:
                b, f = _scan_dir_metrics(folder, file_glob=file_glob)
                cat_bytes += b
                cat_files += f
            cat_row = {
                **item,
                "resolved_paths": existing,
                "size_bytes": cat_bytes,
                "files_count": cat_files,
            }
        total_bytes += cat_row["size_bytes"]
        total_files += cat_row["files_count"]
        categories.append(cat_row)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "categories": categories,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "elapsed_ms": elapsed_ms,
    }


def run_quick_clean(
    selected_ids: list[str],
    *,
    shred_passes: int = 0,
    unlock_locked: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Выполняет очистку выбранных категорий Quick Cleaner."""
    started = time.perf_counter()
    defs_by_id = {d["id"]: d for d in get_quick_clean_definitions()}
    freed_bytes = 0
    deleted_files = 0
    skipped_files = 0
    details: list[dict[str, Any]] = []

    total_cats = max(1, len(selected_ids))
    for idx, cat_id in enumerate(selected_ids, 1):
        defn = defs_by_id.get(cat_id)
        if not defn:
            continue
        if progress_cb:
            progress_cb(defn["title"], idx, total_cats)

        if defn.get("is_recycle_bin"):
            ok, rb_freed, rb_count = empty_recycle_bin()
            freed_bytes += rb_freed
            deleted_files += rb_count
            details.append(
                {
                    "id": cat_id,
                    "title": defn["title"],
                    "freed_bytes": rb_freed,
                    "deleted_files": rb_count,
                    "skipped_files": 0 if ok else 1,
                }
            )
            continue

        existing = _expand_existing_dirs(defn.get("paths", []))
        file_glob = defn.get("file_glob")
        cat_freed = 0
        cat_deleted = 0
        cat_skipped = 0

        for folder in existing:
            safe, _ = is_safe_delete_path(folder)
            if not safe:
                continue
            if file_glob:
                try:
                    with os.scandir(folder) as it:
                        for entry in it:
                            if entry.is_file(follow_symlinks=False) and fnmatch.fnmatch(
                                entry.name.lower(), file_glob.lower()
                            ):
                                ok, sz, _, _ = delete_single_file(
                                    entry.path,
                                    shred_passes=shred_passes,
                                    unlock_if_locked=unlock_locked,
                                )
                                if ok:
                                    cat_freed += sz
                                    cat_deleted += 1
                                else:
                                    cat_skipped += 1
                except OSError:
                    pass
            else:
                res = delete_path_forced(
                    folder,
                    keep_root_dir=True,
                    shred_passes=shred_passes,
                    unlock_if_locked=unlock_locked,
                )
                cat_freed += int(res.get("freed_bytes", 0))
                cat_deleted += int(res.get("deleted_files", 0))
                cat_skipped += int(res.get("failed_files", 0))

        freed_bytes += cat_freed
        deleted_files += cat_deleted
        skipped_files += cat_skipped
        details.append(
            {
                "id": cat_id,
                "title": defn["title"],
                "freed_bytes": cat_freed,
                "deleted_files": cat_deleted,
                "skipped_files": cat_skipped,
            }
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "freed_bytes": freed_bytes,
        "deleted_files": deleted_files,
        "skipped_files": skipped_files,
        "details": details,
        "elapsed_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# 2. ТОМА И SSD TRIM
# ---------------------------------------------------------------------------
def list_volumes() -> list[dict[str, Any]]:
    """Возвращает список локальных томов с объёмом и свободным местом через WinAPI + shutil."""
    volumes: list[dict[str, Any]] = []
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        mask = int(kernel32.GetLogicalDrives())
        for i in range(26):
            if not (mask & (1 << i)):
                continue
            letter = chr(ord("A") + i)
            mountpoint = f"{letter}:\\"
            drive_type = int(kernel32.GetDriveTypeW(wintypes.LPCWSTR(mountpoint)))
            # DRIVE_FIXED = 3, DRIVE_REMOVABLE = 2
            if drive_type not in (2, 3):
                continue
            try:
                usage = shutil.disk_usage(mountpoint)
            except OSError:
                continue
            if usage.total <= 0:
                continue
            pct = round(usage.used / usage.total * 100.0, 1)
            volumes.append(
                {
                    "letter": letter,
                    "mountpoint": mountpoint,
                    "fstype": "NTFS",
                    "total": int(usage.total),
                    "used": int(usage.used),
                    "free": int(usage.free),
                    "percent": pct,
                }
            )
    return volumes


def run_ssd_trim(drive_letter: str) -> tuple[bool, str]:
    """Выполняет TRIM (Optimize-Volume -ReTrim) на указанном томе."""
    letter = (drive_letter or "C").strip().rstrip(":\\").upper()
    if not letter.isalpha() or len(letter) != 1:
        return False, "Некорректная буква диска"
    if not is_admin():
        return (
            False,
            "Для выполнения SSD TRIM требуются права администратора (нажмите «Перезапустить от админа» внизу слева).",
        )
    code, out, err = run_hidden(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Optimize-Volume -DriveLetter {letter} -ReTrim -Verbose",
        ],
        timeout=60,
    )
    if code == 0:
        return True, f"Команда SSD TRIM для диска {letter}: успешно выполнена."
    msg = (err or out or f"Код возврата {code}").strip()
    return False, f"Не удалось выполнить TRIM для {letter}: {msg}"


# ---------------------------------------------------------------------------
# 3. ТОЧЕЧНАЯ ОЧИСТКА (Precise Cleaner: профили и конструктор фильтров)
# ---------------------------------------------------------------------------
PRECISE_PROFILES: dict[str, dict[str, Any]] = {
    "old_downloads": {
        "id": "old_downloads",
        "title": "📥 Старые и крупные загрузки (Downloads)",
        "description": "Файлы в папке «Загрузки» старше 30 дней или крупнее 50 МБ (установщики, архивы, ISO)",
    },
    "logs_dumps": {
        "id": "logs_dumps",
        "title": "📄 Логи, дампы и временные хвосты (.log, .dmp, .tmp, .bak, .old)",
        "description": "Файлы журналов, резервных копий и аварийных дампов в профиле пользователя",
    },
    "app_caches": {
        "id": "app_caches",
        "title": "💬 Кэши мессенджеров и лаунчеров (Telegram, Discord, Steam, Epic)",
        "description": "Кэш скачанных медиафайлов Telegram Desktop, кэш Discord, Steam и Epic Games (без выхода из аккаунтов)",
    },
    "dev_junk": {
        "id": "dev_junk",
        "title": "🛠️ Dev-мусор (node_modules, __pycache__, .pytest_cache, target, build)",
        "description": "Тяжёлые папки зависимостей и кэшей сборки в проектах (можно выбрать рабочую папку)",
    },
}

DEV_JUNK_FOLDER_NAMES = {
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".parcel-cache",
    ".turbo",
    ".gradle",
    "target",
}


def _folder_size_fast(folder: str, cancel_event: threading.Event | None = None) -> tuple[int, int]:
    """Считает размер папки и количество файлов внутри."""
    total_size = 0
    files_count = 0
    stack = [folder]
    while stack:
        if cancel_event and cancel_event.is_set():
            break
        curr = stack.pop()
        try:
            with os.scandir(curr) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total_size += entry.stat(follow_symlinks=False).st_size
                            files_count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total_size, files_count


def scan_precise_profile(
    profile_id: str,
    custom_root: str | None = None,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Сканирует систему по одному из 4 быстрых профилей точечной очистки.
    Возвращает список найденных элементов для таблицы предпросмотра.
    """
    items: list[dict[str, Any]] = []
    now = time.time()
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    roaming = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))

    if profile_id == "old_downloads":
        dl_dir = custom_root if (custom_root and os.path.isdir(custom_root)) else str(Path.home() / "Downloads")
        if not os.path.isdir(dl_dir):
            return items
        if progress_cb:
            progress_cb(f"Сканирование {dl_dir}…")
        try:
            with os.scandir(dl_dir) as it:
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        break
                    try:
                        st = entry.stat(follow_symlinks=False)
                        age_days = max(0.0, (now - st.st_mtime) / 86400.0)
                        if entry.is_file(follow_symlinks=False):
                            size = int(st.st_size)
                            if age_days >= 14 or size >= 25 * 1024 * 1024:
                                reason = []
                                if age_days >= 14:
                                    reason.append(f"старше {int(age_days)} дн.")
                                if size >= 25 * 1024 * 1024:
                                    reason.append("крупный файл")
                                items.append(
                                    {
                                        "path": entry.path,
                                        "name": entry.name,
                                        "is_dir": False,
                                        "size": size,
                                        "mtime": st.st_mtime,
                                        "age_days": round(age_days, 1),
                                        "category": "Загрузки (" + ", ".join(reason) + ")",
                                        "checked": age_days >= 30 or entry.name.lower().endswith((".exe", ".msi", ".iso", ".zip", ".rar", ".7z")),
                                    }
                                )
                    except OSError:
                        continue
        except OSError:
            pass

    elif profile_id == "app_caches":
        candidates = [
            # Telegram Desktop
            ("Telegram: кэш фото и файлов", os.path.join(roaming, "Telegram Desktop", "tdata", "user_data", "cache")),
            ("Telegram: медиа-кэш", os.path.join(roaming, "Telegram Desktop", "tdata", "user_data", "media_cache")),
            ("Telegram Downloads", str(Path.home() / "Downloads" / "Telegram Desktop")),
            # Discord
            ("Discord: кэш медиа", os.path.join(roaming, "discord", "Cache")),
            ("Discord: кэш скриптов", os.path.join(roaming, "discord", "Code Cache")),
            ("Discord: GPU-кэш", os.path.join(roaming, "discord", "GPUCache")),
            # Steam
            ("Steam: веб-кэш браузера", os.path.join(local, "Steam", "htmlcache", "Cache")),
            ("Steam: Code Cache", os.path.join(local, "Steam", "htmlcache", "Code Cache")),
            ("Steam: GPUCache", os.path.join(local, "Steam", "htmlcache", "GPUCache")),
            # Epic Games
            ("Epic Games: веб-кэш", os.path.join(local, "EpicGamesLauncher", "Saved", "webcache")),
            ("Epic Games: логи", os.path.join(local, "EpicGamesLauncher", "Saved", "Logs")),
            # Spotify
            ("Spotify: кэш аудио", os.path.join(local, "Spotify", "Data")),
            ("Spotify: кэш браузера", os.path.join(local, "Spotify", "Browser", "Cache")),
        ]
        for label, folder in candidates:
            if cancel_event and cancel_event.is_set():
                break
            if not os.path.isdir(folder):
                continue
            if progress_cb:
                progress_cb(f"Проверка {label}…")
            sz, fcount = _folder_size_fast(folder, cancel_event=cancel_event)
            if sz > 0 and fcount > 0:
                try:
                    mtime = os.path.getmtime(folder)
                except OSError:
                    mtime = now
                items.append(
                    {
                        "path": folder,
                        "name": f"{Path(folder).name} ({fcount} файл.)",
                        "is_dir": True,
                        "keep_root_dir": True,
                        "size": sz,
                        "mtime": mtime,
                        "age_days": round(max(0.0, (now - mtime) / 86400.0), 1),
                        "category": label,
                        "checked": True,
                    }
                )

    elif profile_id == "logs_dumps":
        roots = [custom_root] if (custom_root and os.path.isdir(custom_root)) else [local, roaming]
        target_exts = {".log", ".dmp", ".tmp", ".bak", ".old", ".chk", ".wer", ".etl"}
        items = scan_custom_filter(
            root_paths=roots,
            extensions=target_exts,
            min_size_bytes=4 * 1024,
            min_age_days=0,
            name_query="",
            max_results=800,
            cancel_event=cancel_event,
            progress_cb=progress_cb,
        )

    elif profile_id == "dev_junk":
        search_root = custom_root if (custom_root and os.path.isdir(custom_root)) else str(APP_ROOT.parent)
        stack = [search_root]
        app_norm = os.path.normcase(os.path.normpath(str(APP_ROOT)))
        while stack and len(items) < 300:
            if cancel_event and cancel_event.is_set():
                break
            curr = stack.pop()
            curr_norm = os.path.normcase(os.path.normpath(curr))
            # Не сканируем саму рабочую папку Pulse Monitor, чтобы пользователь случайно не снёс её кэш во время работы
            if curr_norm == app_norm or curr_norm.startswith(app_norm + "\\"):
                continue
            if progress_cb:
                progress_cb(f"Поиск dev-кэшей: {curr[:70]}…")
            try:
                with os.scandir(curr) as it:
                    for entry in it:
                        if cancel_event and cancel_event.is_set():
                            break
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        low = entry.name.lower()
                        if low in (".git", ".hg", ".svn", ".venv", "venv", "env", "windows", "program files"):
                            continue
                        if low in DEV_JUNK_FOLDER_NAMES:
                            sz, fcount = _folder_size_fast(entry.path, cancel_event=cancel_event)
                            if sz >= 64 * 1024:
                                try:
                                    mtime = entry.stat(follow_symlinks=False).st_mtime
                                except OSError:
                                    mtime = now
                                items.append(
                                    {
                                        "path": entry.path,
                                        "name": f"{entry.name} ({Path(curr).name})",
                                        "is_dir": True,
                                        "keep_root_dir": False,
                                        "size": sz,
                                        "mtime": mtime,
                                        "age_days": round(max(0.0, (now - mtime) / 86400.0), 1),
                                        "category": f"Dev-мусор ({entry.name}, {fcount} файл.)",
                                        "checked": True,
                                    }
                                )
                        else:
                            stack.append(entry.path)
            except OSError:
                continue

    items.sort(key=lambda x: int(x.get("size", 0)), reverse=True)
    return items


def scan_custom_filter(
    *,
    root_paths: list[str],
    extensions: set[str] | None = None,
    min_size_bytes: int = 0,
    min_age_days: float = 0.0,
    name_query: str = "",
    max_results: int = 1000,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Точечный поиск файлов по пользовательским фильтрам:
    папка, расширения, минимальный размер, возраст (дней) и часть имени.
    """
    results: list[dict[str, Any]] = []
    now = time.time()
    norm_exts: set[str] = set()
    if extensions:
        for e in extensions:
            cleaned = e.strip().lower()
            if cleaned:
                norm_exts.add(cleaned if cleaned.startswith(".") else f".{cleaned}")

    query_low = (name_query or "").strip().lower()
    stack = [p for p in root_paths if p and os.path.isdir(p)]
    visited_dirs = 0

    while stack and len(results) < max_results:
        if cancel_event and cancel_event.is_set():
            break
        curr = stack.pop()
        safe_dir, _ = is_safe_delete_path(curr)
        # Разрешаем обход корня пользователя или диска, но пропускаем защищённые ветки Windows
        curr_norm = os.path.normcase(os.path.normpath(curr))
        if curr_norm.startswith(WINDIR + "\\") and not any(
            curr_norm.startswith(s) for s in SAFE_WINDIR_SUBDIRS
        ):
            continue

        visited_dirs += 1
        if progress_cb and visited_dirs % 25 == 0:
            progress_cb(f"Проверено папок: {visited_dirs} | Найдено: {len(results)} | {curr[:65]}…")

        try:
            with os.scandir(curr) as it:
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() not in ("$recycle.bin", "system volume information", ".git", "winsxs", "system32"):
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            name_low = entry.name.lower()
                            if norm_exts:
                                ext = os.path.splitext(name_low)[1]
                                if ext not in norm_exts:
                                    continue
                            if query_low and query_low not in name_low:
                                continue
                            st = entry.stat(follow_symlinks=False)
                            size = int(st.st_size)
                            if size < min_size_bytes:
                                continue
                            age_days = max(0.0, (now - st.st_mtime) / 86400.0)
                            if age_days < min_age_days:
                                continue
                            safe_file, _ = is_safe_delete_path(entry.path)
                            if not safe_file:
                                continue
                            ext_label = os.path.splitext(entry.name)[1].lower() or "файл"
                            results.append(
                                {
                                    "path": entry.path,
                                    "name": entry.name,
                                    "is_dir": False,
                                    "size": size,
                                    "mtime": st.st_mtime,
                                    "age_days": round(age_days, 1),
                                    "category": f"Фильтр ({ext_label})",
                                    "checked": True,
                                }
                            )
                            if len(results) >= max_results:
                                break
                    except OSError:
                        continue
        except OSError:
            continue

    results.sort(key=lambda x: int(x.get("size", 0)), reverse=True)
    return results


# ---------------------------------------------------------------------------
# 4. ИНТЕГРАЦИЯ WIZTREE + МОНИТОРИНГ ПРОЦЕССОВ И АНАЛИЗАТОР ДИСКА
# ---------------------------------------------------------------------------
def _norm_path(p: str) -> str:
    if not p:
        return ""
    try:
        return os.path.normcase(os.path.normpath(p)).rstrip("\\/")
    except Exception:
        return ""


def collect_active_processes_for_disk() -> list[dict[str, Any]]:
    """
    Быстро собирает все запущенные процессы вместе с их путями (.exe),
    рабочими папками (CWD) и открытыми файлами (open_files), чтобы подсвечивать
    активные папки и файлы прямо в дереве WizTree.
    """
    from .process_kb import describe_process
    from .sysinfo import query_processes
    from .utils import format_bytes
    from .winapi import query_process_image_path

    records: list[dict[str, Any]] = []
    try:
        raw_items = query_processes()
    except Exception:
        raw_items = []

    try:
        import psutil as _psutil
    except Exception:
        _psutil = None

    budget_started = time.perf_counter()
    for item in raw_items:
        pid = int(item.get("pid", 0) or 0)
        if pid <= 4:
            continue
        name = str(item.get("name") or f"PID {pid}")
        session = int(item.get("session", 0) or 0)
        rss = int(item.get("rss", 0) or 0)
        exe = query_process_image_path(pid)
        cwd = ""
        open_files_list: list[tuple[str, str]] = []

        if _psutil is not None and (time.perf_counter() - budget_started) < 0.18:
            try:
                proc = _psutil.Process(pid)
                if not exe:
                    try:
                        exe = proc.exe() or ""
                    except Exception:
                        pass
                if session > 0:
                    try:
                        cwd = proc.cwd() or ""
                    except Exception:
                        pass
                    try:
                        for of in proc.open_files()[:25]:
                            of_path = getattr(of, "path", "") or ""
                            if of_path:
                                open_files_list.append((_norm_path(of_path), of_path))
                    except Exception:
                        pass
            except Exception:
                pass

        if not exe and not cwd and not open_files_list:
            continue

        kb = describe_process(name=name, exe=exe, pid=pid, session=session)
        records.append(
            {
                "pid": pid,
                "name": name,
                "exe": exe,
                "exe_norm": _norm_path(exe),
                "cwd": cwd,
                "cwd_norm": _norm_path(cwd),
                "open_files": open_files_list,
                "description": kb.get("summary", ""),
                "safety": kb.get("safety", "safe"),
                "safety_text": kb.get("safety_text", ""),
                "rss": rss,
                "mem_text": format_bytes(rss),
            }
        )
    return records


def find_processes_for_path(
    target_path: str,
    active_procs: list[dict[str, Any]] | None = None,
    *,
    check_restart_manager: bool = False,
) -> list[dict[str, Any]]:
    """
    Возвращает список процессов, которые:
    1) Запущены из указанной папки или файла (Запущен EXE)
    2) Держат открытыми файлы внутри этой папки (Открыт файл)
    3) Используют эту папку как рабочую директорию (Рабочая папка CWD)
    4) Удерживают ядерный дескриптор через Windows Restart Manager (если check_restart_manager=True)
    """
    target_norm = _norm_path(target_path)
    if not target_norm:
        return []

    procs = active_procs if active_procs is not None else collect_active_processes_for_disk()
    prefix = target_norm + "\\"
    matched_by_pid: dict[int, dict[str, Any]] = {}

    for p in procs:
        pid = int(p["pid"])
        reasons: list[str] = []
        target_files: list[str] = []

        exe_n = p.get("exe_norm") or ""
        if exe_n and (exe_n == target_norm or exe_n.startswith(prefix)):
            reasons.append("🚀 Запущен EXE")
            target_files.append(p.get("exe") or "")

        for of_norm, of_orig in p.get("open_files") or []:
            if of_norm == target_norm or of_norm.startswith(prefix):
                if "📂 Открыт файл" not in reasons:
                    reasons.append("📂 Открыт файл")
                if len(target_files) < 4 and of_orig not in target_files:
                    target_files.append(of_orig)

        cwd_n = p.get("cwd_norm") or ""
        if cwd_n and (cwd_n == target_norm or cwd_n.startswith(prefix)):
            if not reasons:
                reasons.append("📁 Рабочая папка (CWD)")
                target_files.append(p.get("cwd") or "")

        if reasons:
            matched_by_pid[pid] = {
                "pid": pid,
                "name": p["name"],
                "exe": p.get("exe", ""),
                "description": p.get("description", ""),
                "safety": p.get("safety", "safe"),
                "safety_text": p.get("safety_text", ""),
                "mem_text": p.get("mem_text", "—"),
                "reason": ", ".join(reasons),
                "target_file": target_files[0] if target_files else (p.get("exe") or ""),
                "all_files": target_files,
            }

    if check_restart_manager and os.path.exists(target_path):
        try:
            from .process_kb import describe_process

            rm_holders = find_locking_processes(target_path)
            for holder in rm_holders:
                if holder.pid in matched_by_pid:
                    existing = matched_by_pid[holder.pid]
                    if "🔒 Дескриптор" not in existing["reason"]:
                        existing["reason"] += ", 🔒 Дескриптор"
                else:
                    kb = describe_process(
                        name=holder.name,
                        exe=holder.exe,
                        pid=holder.pid,
                        session=holder.session,
                    )
                    matched_by_pid[holder.pid] = {
                        "pid": holder.pid,
                        "name": holder.name,
                        "exe": holder.exe,
                        "description": kb.get("summary", ""),
                        "safety": kb.get("safety", "safe"),
                        "safety_text": kb.get("safety_text", ""),
                        "mem_text": "—",
                        "reason": "🔒 Удерживает дескриптор (Restart Manager)",
                        "target_file": target_path,
                        "all_files": [target_path],
                    }
        except Exception:
            pass

    result = list(matched_by_pid.values())
    result.sort(key=lambda r: (r["safety"] == "critical", r["name"].lower()))
    return result


def terminate_processes_in_path_and_delete(
    target_path: str,
    *,
    shred_passes: int = 0,
) -> dict[str, Any]:
    """
    Принудительно завершает все некритические процессы, которые запущены из target_path
    или держат открытые файлы в нём, после чего безвозвратно удаляет файл или папку.
    """
    safe, reason = is_safe_delete_path(target_path)
    if not safe:
        return {"ok": False, "error": reason, "freed_bytes": 0, "killed_pids": []}

    holders = find_processes_for_path(target_path, check_restart_manager=True)
    killed_pids: list[int] = []
    own_pid = os.getpid()

    for h in holders:
        pid = int(h["pid"])
        if pid in (0, 4, own_pid) or h.get("safety") == "critical":
            continue
        try:
            if os.name == "nt":
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                handle = k32.OpenProcess(0x0001, False, pid)
                if handle:
                    try:
                        if k32.TerminateProcess(handle, 1):
                            killed_pids.append(pid)
                    finally:
                        k32.CloseHandle(handle)
        except Exception:
            pass

    if killed_pids:
        time.sleep(0.2)

    del_res = delete_path_forced(
        target_path,
        keep_root_dir=False,
        shred_passes=shred_passes,
        unlock_if_locked=True,
    )
    for p in del_res.get("unlocked_pids") or []:
        if p not in killed_pids:
            killed_pids.append(p)
    del_res["killed_pids"] = killed_pids
    del_res["killed_processes"] = killed_pids
    return del_res


def analyze_disk_space(
    root_path: str,
    *,
    max_tree_depth: int = 4,
    top_files_limit: int = 100,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Быстрое сканирование выбранной папки или диска в стиле WizTree через os.scandir.
    Возвращает:
    - root: иерархическое дерево папок И файлов с размерами, долями %, количеством файлов
      и привязкой к запущенным процессам (proc_count, proc_names)
    - active_processes: снимок всех активных процессов с путями
    - top_files: топ-100 самых больших файлов
    - extensions: статистика по расширениям
    """
    started = time.perf_counter()
    root_clean = os.path.abspath(str(root_path or "C:\\"))

    active_procs = collect_active_processes_for_disk()
    top_files_heap: list[tuple[int, str, float, str]] = []
    ext_stats: dict[str, list[int]] = {}  # ext -> [total_size, count]
    total_files = 0
    total_dirs = 0

    def _match_procs_quick(norm_p: str, is_dir: bool) -> tuple[int, list[str]]:
        if not norm_p:
            return 0, []
        prefix = norm_p + "\\"
        names: list[str] = []
        pids_seen: set[int] = set()
        for p in active_procs:
            pid = p["pid"]
            if pid in pids_seen:
                continue
            exe_n = p.get("exe_norm") or ""
            cwd_n = p.get("cwd_norm") or ""
            matched = False
            if is_dir:
                if (exe_n and (exe_n == norm_p or exe_n.startswith(prefix))) or (
                    cwd_n and (cwd_n == norm_p or cwd_n.startswith(prefix))
                ):
                    matched = True
                else:
                    for of_n, _ in p.get("open_files") or []:
                        if of_n == norm_p or of_n.startswith(prefix):
                            matched = True
                            break
            else:
                if exe_n == norm_p:
                    matched = True
                else:
                    for of_n, _ in p.get("open_files") or []:
                        if of_n == norm_p:
                            matched = True
                            break
            if matched:
                pids_seen.add(pid)
                if p["name"] not in names:
                    names.append(p["name"])
        return len(pids_seen), names[:5]

    def _scan_node(folder: str, depth: int) -> dict[str, Any]:
        nonlocal total_files, total_dirs
        total_dirs += 1
        if progress_cb and total_dirs % 40 == 0:
            progress_cb(f"WizTree-сканирование: {total_dirs} папок, {total_files} файлов — {folder[:65]}…")

        own_files_size = 0
        own_files_count = 0
        own_dirs_count = 0
        folder_mtime = 0.0
        children: list[dict[str, Any]] = []
        direct_files: list[dict[str, Any]] = []
        sub_dirs: list[tuple[str, str, float]] = []

        try:
            folder_mtime = os.path.getmtime(folder)
        except OSError:
            pass

        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            low_name = entry.name.lower()
                            if low_name in ("$recycle.bin", "system volume information"):
                                continue
                            try:
                                d_st = entry.stat(follow_symlinks=False)
                                if int(getattr(d_st, "st_file_attributes", 0) or 0) & 0x0400:
                                    continue
                                d_mtime = d_st.st_mtime
                            except OSError:
                                d_mtime = 0.0
                            sub_dirs.append((entry.name, entry.path, d_mtime))
                            own_dirs_count += 1
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            fsize = int(st.st_size)
                            own_files_size += fsize
                            own_files_count += 1
                            total_files += 1

                            ext = os.path.splitext(entry.name)[1].lower() or "(без расш.)"
                            bucket = ext_stats.get(ext)
                            if bucket is None:
                                ext_stats[ext] = [fsize, 1]
                            else:
                                bucket[0] += fsize
                                bucket[1] += 1

                            if len(top_files_heap) < top_files_limit:
                                heapq.heappush(top_files_heap, (fsize, entry.path, st.st_mtime, entry.name))
                            elif fsize > top_files_heap[0][0]:
                                heapq.heapreplace(top_files_heap, (fsize, entry.path, st.st_mtime, entry.name))

                            if depth <= max_tree_depth:
                                f_norm = _norm_path(entry.path)
                                p_cnt, p_names = _match_procs_quick(f_norm, is_dir=False)
                                direct_files.append(
                                    {
                                        "name": entry.name,
                                        "path": entry.path,
                                        "size": fsize,
                                        "mtime": st.st_mtime,
                                        "files_count": 1,
                                        "dirs_count": 0,
                                        "is_dir": False,
                                        "proc_count": p_cnt,
                                        "proc_names": p_names,
                                        "children": [],
                                    }
                                )
                    except OSError:
                        continue
        except OSError:
            pass

        total_size = own_files_size
        total_sub_files = own_files_count
        total_sub_dirs = own_dirs_count

        for sub_name, sub_path, sub_mtime in sub_dirs:
            if cancel_event and cancel_event.is_set():
                break
            if depth < max_tree_depth:
                child_node = _scan_node(sub_path, depth + 1)
                total_size += child_node["size"]
                total_sub_files += child_node.get("files_count", 0)
                total_sub_dirs += child_node.get("dirs_count", 0)
                if child_node["size"] > 0 or child_node.get("proc_count", 0) > 0:
                    children.append(child_node)
            else:
                sub_size, sub_files, sub_dircnt = _scan_flat_subtree(sub_path)
                total_size += sub_size
                total_sub_files += sub_files
                total_sub_dirs += sub_dircnt
                if sub_size > 0:
                    s_norm = _norm_path(sub_path)
                    p_cnt, p_names = _match_procs_quick(s_norm, is_dir=True)
                    children.append(
                        {
                            "name": sub_name,
                            "path": sub_path,
                            "size": sub_size,
                            "mtime": sub_mtime,
                            "files_count": sub_files,
                            "dirs_count": sub_dircnt,
                            "is_dir": True,
                            "proc_count": p_cnt,
                            "proc_names": p_names,
                            "children": [],
                        }
                    )

        # Добавляем отдельные файлы папки (до 35 крупнейших + файлы с активными процессами)
        if direct_files:
            direct_files.sort(key=lambda f: (f.get("proc_count", 0) > 0, f["size"]), reverse=True)
            kept_files = direct_files[:35]
            rest_files = direct_files[35:]
            children.extend(kept_files)
            if rest_files:
                rest_sz = sum(f["size"] for f in rest_files)
                children.append(
                    {
                        "name": f"[Ещё мелких файлов в папке: {len(rest_files)} шт.]",
                        "path": folder,
                        "size": rest_sz,
                        "mtime": folder_mtime,
                        "files_count": len(rest_files),
                        "dirs_count": 0,
                        "is_dir": False,
                        "is_files_leaf": True,
                        "proc_count": 0,
                        "proc_names": [],
                        "children": [],
                    }
                )

        children.sort(key=lambda c: c["size"], reverse=True)
        if len(children) > 60:
            other_size = sum(c["size"] for c in children[59:])
            other_files = sum(c.get("files_count", 0) for c in children[59:])
            children = children[:59]
            children.append(
                {
                    "name": f"[Прочие элементы ({len(children) - 59})]",
                    "path": folder,
                    "size": other_size,
                    "mtime": folder_mtime,
                    "files_count": other_files,
                    "dirs_count": 0,
                    "is_dir": True,
                    "is_other": True,
                    "proc_count": 0,
                    "proc_names": [],
                    "children": [],
                }
            )

        norm_folder = _norm_path(folder)
        p_cnt, p_names = _match_procs_quick(norm_folder, is_dir=True)

        return {
            "name": Path(folder).name or folder,
            "path": folder,
            "size": total_size,
            "mtime": folder_mtime,
            "files_count": total_sub_files,
            "dirs_count": total_sub_dirs,
            "is_dir": True,
            "proc_count": p_cnt,
            "proc_names": p_names,
            "children": children,
        }

    def _scan_flat_subtree(start_dir: str) -> tuple[int, int, int]:
        nonlocal total_files, total_dirs
        sub_total = 0
        sub_fcount = 0
        sub_dcount = 0
        stack = [start_dir]
        while stack:
            if cancel_event and cancel_event.is_set():
                break
            curr = stack.pop()
            total_dirs += 1
            sub_dcount += 1
            if progress_cb and total_dirs % 60 == 0:
                progress_cb(f"WizTree-сканирование: {total_dirs} папок, {total_files} файлов — {curr[:65]}…")
            try:
                with os.scandir(curr) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                d_st = entry.stat(follow_symlinks=False)
                                if int(getattr(d_st, "st_file_attributes", 0) or 0) & 0x0400:
                                    continue
                                stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                st = entry.stat(follow_symlinks=False)
                                fsize = int(st.st_size)
                                sub_total += fsize
                                sub_fcount += 1
                                total_files += 1

                                ext = os.path.splitext(entry.name)[1].lower() or "(без расш.)"
                                bucket = ext_stats.get(ext)
                                if bucket is None:
                                    ext_stats[ext] = [fsize, 1]
                                else:
                                    bucket[0] += fsize
                                    bucket[1] += 1

                                if len(top_files_heap) < top_files_limit:
                                    heapq.heappush(top_files_heap, (fsize, entry.path, st.st_mtime, entry.name))
                                elif fsize > top_files_heap[0][0]:
                                    heapq.heapreplace(top_files_heap, (fsize, entry.path, st.st_mtime, entry.name))
                        except OSError:
                            continue
            except OSError:
                continue
        return sub_total, sub_fcount, sub_dcount

    root_tree = _scan_node(root_clean, 0)
    total_size = max(1, int(root_tree.get("size", 0)))

    top_files = [
        {
            "size": sz,
            "path": fpath,
            "mtime": mtime,
            "name": fname,
            "ext": os.path.splitext(fname)[1].lower() or "—",
        }
        for sz, fpath, mtime, fname in sorted(top_files_heap, key=lambda x: x[0], reverse=True)
    ]

    extensions = [
        {
            "ext": ext,
            "size": vals[0],
            "count": vals[1],
            "pct": round(vals[0] / total_size * 100.0, 1),
        }
        for ext, vals in sorted(ext_stats.items(), key=lambda kv: kv[1][0], reverse=True)[:40]
    ]

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "root": root_tree,
        "active_processes": active_procs,
        "top_files": top_files,
        "extensions": extensions,
        "summary": {
            "root_path": root_clean,
            "total_size": int(root_tree.get("size", 0)),
            "files_count": total_files,
            "dirs_count": total_dirs,
            "elapsed_ms": elapsed_ms,
        },
    }


# ---------------------------------------------------------------------------
# Поиск дубликатов файлов (3-этапный конвейер: размер -> краевой хэш -> SHA-1)
# ---------------------------------------------------------------------------
_SKIP_DUP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "site-packages",
    ".nuget",
    ".cargo",
    ".rustup",
    "cargo",
    "rustup",
    "puccinialin",
    "uv",
    "pip",
    "conda",
    "npm-cache",
    "pnpm",
    "yarn",
    ".gradle",
    ".m2",
    "$recycle.bin",
    "system volume information",
    "recovery",
    "perflogs",
    "windows",
    "windows.old",
    "msocache",
    "windowsapps",
    "program files",
    "program files (x86)",
    "programdata",
    "packages",
    "steamapps",
    "ebwebview",
    ".webview2",
    "webview",
    "webview2",
    "pluginsstorage",
    "autoisolate",
    "support",
    "bepinex",
    "profiles",
    "autodesk",
    "adobe",
    "shadercache",
    "d3dscache",
    "curseforge",
    "modrinth",
    "saved games",
    "saves",
    "mods",
    "instances",
    "libraries",
    "versions",
    "shaderpacks",
    "resourcepacks",
    "texturepacks",
    "extensions",
    "resources",
    "app.asar.unpacked",
    "workspacestorage",
    "unistoredb",
    "nvbackend",
    "dao",
    "recommendations",
    "translations",
}

# Внутри AppData сканер дубликатов имеет право предлагать к удалению ТОЛЬКО файлы из папок кэша,
# временных файлов, апдейтеров и крэш-дампов (чтобы никогда не задеть установленные в AppData
# программы вроде GitHubDesktop\app-*, Discord\app-*, Wand\app-* или базы данных программ).
_APPDATA_SAFE_DUP_TOKENS = (
    "\\cache\\",
    "\\cache_data\\",
    "\\browsercache\\",
    "\\htmlcache\\",
    "\\cefbrowsercache\\",
    "\\cefcache\\",
    "\\gpucache\\",
    "\\code cache\\",
    "\\webcache",
    "\\component_crx_cache\\",
    "\\dawnwebgpucache\\",
    "\\dawngraphitecache\\",
    "\\temp\\",
    "\\tmp\\",
    "-updater\\",
    "\\updater\\",
    "\\pending\\",
    "\\crashes\\",
    "\\crashpad\\",
)


def _is_allowed_dup_file_path(fpath: str) -> bool:
    """Проверяет, что файл внутри AppData находится строго в безопасной кэш/temp/updater папке."""
    low = fpath.lower()
    if "\\appdata\\" in low:
        return any(tok in low for tok in _APPDATA_SAFE_DUP_TOKENS)
    return True


# Системные и программные пути, внутри которых файлы принадлежат установленным приложениям
# и не должны предлагаться как пользовательские дубликаты к удалению
_PROTECTED_DUP_PREFIXES = tuple(
    os.path.normcase(os.path.normpath(p))
    for p in (
        os.environ.get("SystemRoot", r"C:\Windows"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramData", r"C:\ProgramData"),
        r"C:\Autodesk",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "puccinialin"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "uv"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Comms"),
    )
    if p
)

# Расширения библиотек, баз данных, модов, бэкапов сохранений и ресурсов движков программ —
# каждая программа/игра нуждается в своём экземпляре в своей папке
_SKIP_DUP_EXTENSIONS = {
    ".dll",
    ".sys",
    ".drv",
    ".ocx",
    ".pak",
    ".asar",
    ".node",
    ".pyd",
    ".so",
    ".mui",
    ".cat",
    ".manifest",
    ".tlb",
    ".nls",
    ".winmd",
    ".pri",
    ".pdb",
    ".mnr",
    ".atc",
    ".jar",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".jrs",
    ".vscdb",
    ".backup",
    ".save-backup",
    ".save",
    ".blend1",
    ".blend2",
    ".car",
    ".translation",
    ".wasm",
    ".cjs",
    ".mjs",
    ".ts",
    ".map",
}

# Атрибуты Windows для пропуска симлинков/точек соединения (Junction) и облачных файлов OneDrive
_SKIP_FILE_ATTRS = (
    0x00000400  # FILE_ATTRIBUTE_REPARSE_POINT
    | 0x00001000  # FILE_ATTRIBUTE_OFFLINE
    | 0x00040000  # FILE_ATTRIBUTE_RECALL_ON_OPEN
    | 0x00400000  # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


def _partial_hash(path: str, size: int) -> str | None:
    """Быстрый 3-точечный хэш (первые 16 КБ + середина 16 КБ + последние 16 КБ)."""
    try:
        h = hashlib.md5()
        sample = 16384
        with open(path, "rb") as fh:
            head = fh.read(sample)
            h.update(head)
            if size > sample * 3:
                fh.seek(size // 2)
                h.update(fh.read(sample))
            if size > sample * 2:
                fh.seek(max(0, size - sample))
                h.update(fh.read(sample))
        return h.hexdigest()
    except OSError:
        return None


def _full_sha1(
    path: str,
    size: int = 0,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[str], None] | None = None,
    stage_prefix: str = "",
) -> str | None:
    """
    SHA-1 файла блоками по 512 КБ.
    Для гигантских файлов (> 128 МБ) использует 32 равномерных среза по 1 МБ + точный размер,
    чтобы не зависать на многогигабайтных образах (.iso, .vhdx, .pak) на несколько минут.
    """
    try:
        if size <= 0:
            size = os.path.getsize(path)
        h = hashlib.sha1()
        h.update(f"size:{size}:".encode("ascii"))
        last_report = time.perf_counter()

        with open(path, "rb") as fh:
            if size > 128 * 1024 * 1024:
                # 32 равномерных блока по 1 МБ по всей длине крупного файла
                num_slices = 32
                slice_size = 1024 * 1024
                step = max(slice_size, (size - slice_size) // max(1, num_slices - 1))
                for i in range(num_slices):
                    if cancel_event and cancel_event.is_set():
                        return None
                    pos = min(max(0, size - slice_size), i * step)
                    fh.seek(pos)
                    chunk = fh.read(slice_size)
                    if chunk:
                        h.update(chunk)
                    now = time.perf_counter()
                    if progress_cb and stage_prefix and (now - last_report) >= 0.15:
                        last_report = now
                        pct = int((i + 1) / num_slices * 100)
                        progress_cb(f"{stage_prefix} ({pct}%)")
            else:
                read_bytes = 0
                while True:
                    if cancel_event and cancel_event.is_set():
                        return None
                    chunk = fh.read(524288)
                    if not chunk:
                        break
                    h.update(chunk)
                    read_bytes += len(chunk)
                    now = time.perf_counter()
                    if progress_cb and stage_prefix and (now - last_report) >= 0.15:
                        last_report = now
                        pct = int(read_bytes / max(1, size) * 100)
                        progress_cb(f"{stage_prefix} ({pct}%)")
        return h.hexdigest()
    except OSError:
        return None


def find_duplicates(
    root_path: str,
    *,
    min_size_bytes: int = 64 * 1024,
    max_groups: int = 250,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Ищет 100% идентичные дубликаты файлов в указанной папке:
    1) Группировка по точному размеру файла (с пропуском системных папок, симлинков и облачных заглушек)
    2) Сравнение быстрых 3-точечных хэшей (начало + середина + конец файла)
    3) Проверка SHA-1 только для совпавших кандидатов с живым прогрессом
    """
    started = time.perf_counter()
    by_size: dict[int, list[tuple[str, float]]] = {}
    seen_inodes: set[tuple[int, int]] = set()
    scanned_files = 0
    scanned_dirs = 0
    last_progress_ts = started

    root_abs = os.path.abspath(str(root_path))
    stack = [root_abs]
    visited_dirs: set[str] = set()

    if progress_cb:
        progress_cb(f"Этап 1/3 (обход папок): старт сканирования {root_abs}…")

    while stack:
        if cancel_event and cancel_event.is_set():
            break
        curr = stack.pop()
        curr_norm = os.path.normcase(os.path.normpath(curr))
        if curr_norm in visited_dirs:
            continue
        visited_dirs.add(curr_norm)

        # Пропускаем системные папки Windows и папки установленных программ (Program Files, AppData\Local\Programs и т.д.)
        if any(curr_norm == pref or curr_norm.startswith(pref + "\\") for pref in _PROTECTED_DUP_PREFIXES):
            continue

        scanned_dirs += 1
        now = time.perf_counter()
        if progress_cb and (now - last_progress_ts) >= 0.12:
            last_progress_ts = now
            short_curr = curr if len(curr) <= 55 else ("…" + curr[-52:])
            progress_cb(
                f"Этап 1/3 (обход): папок {scanned_dirs}, файлов {scanned_files} — {short_curr}"
            )

        try:
            with os.scandir(curr) as it:
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                        attrs = int(getattr(st, "st_file_attributes", 0) or 0)
                        if attrs & _SKIP_FILE_ATTRS:
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            low = entry.name.lower()
                            if (
                                low not in _SKIP_DUP_DIRS
                                and not low.startswith(".")
                                and not low.startswith("app-")
                            ):
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in _SKIP_DUP_EXTENSIONS:
                                continue
                            if not _is_allowed_dup_file_path(entry.path):
                                continue
                            sz = int(st.st_size)
                            if sz >= min_size_bytes:
                                # Защита от жёстких ссылок NTFS (Hard Links): если st_ino уже встречался,
                                # это один и тот же физический файл на диске, а не дубликат!
                                ino = int(getattr(st, "st_ino", 0) or 0)
                                dev = int(getattr(st, "st_dev", 0) or 0)
                                if ino > 0:
                                    inode_key = (dev, ino)
                                    if inode_key in seen_inodes:
                                        continue
                                    seen_inodes.add(inode_key)

                                by_size.setdefault(sz, []).append((entry.path, st.st_mtime))
                                scanned_files += 1
                                now_f = time.perf_counter()
                                if progress_cb and (now_f - last_progress_ts) >= 0.12:
                                    last_progress_ts = now_f
                                    progress_cb(
                                        f"Этап 1/3 (обход): папок {scanned_dirs}, подходящих файлов {scanned_files}…"
                                    )
                    except OSError:
                        continue
        except OSError:
            continue

    # Оставляем только размеры, где >= 2 файлов, и сортируем по потенциальной выгоде освобождения места
    sorted_size_groups = sorted(
        ((sz, paths) for sz, paths in by_size.items() if len(paths) >= 2 and len(paths) <= 500),
        key=lambda kv: kv[0] * (len(kv[1]) - 1),
        reverse=True,
    )[:1200]

    total_stage2_files = sum(len(paths) for _, paths in sorted_size_groups)
    done_stage2_files = 0

    if progress_cb:
        progress_cb(
            f"Этап 2/3 (быстрый хэш): проверка {total_stage2_files} кандидатов в {len(sorted_size_groups)} группах…"
        )

    # Этап 2: быстрый частичный хэш + точная фильтрация жёстких ссылок NTFS через os.stat()
    # (на Windows DirEntry.stat() возвращает st_ino=0, а os.stat() вызывает GetFileInformationByHandle)
    partial_groups: list[tuple[int, list[tuple[str, float]]]] = []
    stage2_inodes: set[tuple[int, int]] = set()
    for sz, items in sorted_size_groups:
        if cancel_event and cancel_event.is_set():
            break
        by_part: dict[str, list[tuple[str, float]]] = {}
        for fpath, mtime in items:
            if cancel_event and cancel_event.is_set():
                break
            done_stage2_files += 1
            now = time.perf_counter()
            if progress_cb and (now - last_progress_ts) >= 0.12:
                last_progress_ts = now
                progress_cb(
                    f"Этап 2/3 (быстрый хэш): {done_stage2_files}/{total_stage2_files} файлов "
                    f"(совпадений: {len(partial_groups)})…"
                )
            try:
                real_st = os.stat(fpath, follow_symlinks=False)
                r_ino = int(getattr(real_st, "st_ino", 0) or 0)
                r_dev = int(getattr(real_st, "st_dev", 0) or 0)
                if r_ino > 0:
                    ino_key = (r_dev, r_ino)
                    if ino_key in stage2_inodes:
                        continue
                    stage2_inodes.add(ino_key)
            except OSError:
                continue
            ph = _partial_hash(fpath, sz)
            if ph:
                by_part.setdefault(ph, []).append((fpath, mtime))
        for p_list in by_part.values():
            if len(p_list) >= 2:
                partial_groups.append((sz, p_list))

    # Этап 3: полный SHA-1
    duplicate_groups: list[dict[str, Any]] = []
    total_wasted = 0
    total_dup_files = 0
    total_p_groups = len(partial_groups)

    if progress_cb and total_p_groups > 0:
        progress_cb(f"Этап 3/3 (проверка SHA-1): старт проверки {total_p_groups} групп…")

    for idx, (sz, candidates) in enumerate(partial_groups, 1):
        if cancel_event and cancel_event.is_set():
            break
        stage_msg = (
            f"Этап 3/3 (SHA-1): группа {idx}/{total_p_groups} "
            f"(найдено дубликатов: {len(duplicate_groups)})"
        )
        now = time.perf_counter()
        if progress_cb and (idx == 1 or (now - last_progress_ts) >= 0.12):
            last_progress_ts = now
            progress_cb(stage_msg)

        by_sha: dict[str, list[tuple[str, float]]] = {}
        for fpath, mtime in candidates:
            if cancel_event and cancel_event.is_set():
                break
            fname = Path(fpath).name
            sha = _full_sha1(
                fpath,
                size=sz,
                cancel_event=cancel_event,
                progress_cb=progress_cb,
                stage_prefix=f"{stage_msg} — {fname[:35]}",
            )
            if sha:
                by_sha.setdefault(sha, []).append((fpath, mtime))
        for sha, exact_list in by_sha.items():
            if len(exact_list) < 2:
                continue

            # Умная сортировка оригинала vs копий:
            # Файлы в папках Cache/Temp/Updater или с суффиксами "(1)", "(2)", "copy", "копия"
            # всегда должны идти ПОСЛЕ оригинала и помечаться как копии к удалению!
            def _dup_sort_key(item_tuple: tuple[str, float]) -> tuple[int, int, float, int]:
                p_str, mt = item_tuple
                p_low = p_str.lower()
                fname_low = Path(p_str).stem.lower()
                is_temp_or_cache = int(
                    any(
                        tok in p_low
                        for tok in ("\\cache\\", "\\temp\\", "\\tmp\\", "-updater\\", "\\updater\\", "\\crashes\\")
                    )
                )
                is_numbered_copy = int(
                    fname_low.endswith((" (1)", "(1)", " (2)", "(2)", " (3)", "(3)", " - copy", " - копия", "_copy"))
                )
                return (is_temp_or_cache, is_numbered_copy, mt, len(p_str))

            exact_list.sort(key=_dup_sort_key)

            # Защита от multicall-бинарников (например, cargo.exe / rustc.exe / rustup.exe, которые имеют один SHA-1,
            # но разные функциональные имена в папке bin):
            orig_path, orig_mtime = exact_list[0]
            orig_stem = Path(orig_path).stem.lower()
            filtered_list = [(orig_path, orig_mtime)]
            for cand_path, cand_mtime in exact_list[1:]:
                cand_ext = os.path.splitext(cand_path)[1].lower()
                cand_low = cand_path.lower()
                cand_stem = Path(cand_path).stem.lower()
                if cand_ext in (".exe", ".com", ".bat", ".cmd"):
                    in_safe_cleanup_dir = any(
                        tok in cand_low
                        for tok in (
                            "\\downloads\\",
                            "\\desktop\\",
                            "\\temp\\",
                            "\\tmp\\",
                            "-updater\\",
                            "\\updater\\",
                            "\\cache\\",
                        )
                    ) and "\\bin\\" not in cand_low
                    same_or_numbered_stem = (
                        cand_stem == orig_stem
                        or cand_stem.startswith(orig_stem)
                        or orig_stem.startswith(cand_stem)
                    )
                    if not (in_safe_cleanup_dir or same_or_numbered_stem):
                        continue
                filtered_list.append((cand_path, cand_mtime))

            if len(filtered_list) < 2:
                continue
            exact_list = filtered_list
            wasted = sz * (len(exact_list) - 1)
            total_wasted += wasted
            total_dup_files += len(exact_list) - 1
            files_records = []
            for i, (fpath, mtime) in enumerate(exact_list):
                files_records.append(
                    {
                        "path": fpath,
                        "name": Path(fpath).name,
                        "mtime": mtime,
                        "is_original": i == 0,
                        "checked": i > 0,  # Оригинал никогда не отмечен по умолчанию!
                    }
                )
            duplicate_groups.append(
                {
                    "hash": sha[:12],
                    "size": sz,
                    "count": len(exact_list),
                    "wasted_bytes": wasted,
                    "files": files_records,
                }
            )
            if len(duplicate_groups) >= max_groups:
                break
        if len(duplicate_groups) >= max_groups:
            break

    duplicate_groups.sort(key=lambda g: g["wasted_bytes"], reverse=True)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "groups": duplicate_groups,
        "total_groups": len(duplicate_groups),
        "total_duplicate_files": total_dup_files,
        "total_wasted_bytes": total_wasted,
        "scanned_files": scanned_files,
        "elapsed_ms": elapsed_ms,
    }
