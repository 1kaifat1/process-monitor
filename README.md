# Pulse Monitor

**English** · [Русский](README.ru.md)

A lightweight Windows monitor: processes (including hidden and background ones),
network, startup entries, load charts and flexible customization. It works as a
regular window or as a background tray app. Built with Python + PyQt6 + psutil.

## Taskbar icon

Windows identifies a taskbar "application" by its AppUserModelID (AUMID), not by
the window icon. On start Pulse Monitor therefore:

- assigns the process the AUMID `PulseMonitor.1.0`;
- creates (or refreshes) the **Pulse Monitor** shortcut in the Start menu —
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Pulse Monitor.lnk` — with the
  same AUMID and the `assets/pulse.ico` icon (for the EXE build, the EXE icon).

As a result the taskbar button, pinning, Alt+Tab and notifications show the pulse
icon instead of the generic `pythonw.exe` icon that Windows uses for Python
scripts by default.

The app runs as a single instance: launching it again does not create a second
window or a second taskbar button — it brings the running instance to the front
(including from the tray). This also matters for the icon: two processes with the
same AUMID merge into one button and Windows may show the icon of the wrong
executable.

## Languages

Pulse Monitor ships with a built-in localization layer:

- **Russian** and **English** interface
- **Settings → Appearance → Interface language** switches the language instantly
  (the main window is recreated, no application restart)
- the default interface language is Russian; English and “System (auto)” are
  available in the same menu
- the choice is stored in `config/settings.json` and survives updates

## Quick start

**Ready-made EXE (recommended):** `PulseMonitor.exe` — a single file, Python is
not required. It is built from this repository with `build.bat` and published by
GitHub Actions as the `PulseMonitor-windows` artifact.

- Portable settings live in the `config` folder next to the EXE. If the folder
  is not writable (for example `C:\Program Files`),
  `%APPDATA%\PulseMonitor\config` is used instead.
- The binary is not code-signed, so SmartScreen may warn about an unknown
  publisher — this is normal for GitHub builds.

**From source:**

```bat
install.bat      :: install dependencies
run.bat          :: run without a console (pythonw), tray mode
run-console.bat  :: run with a console for diagnostics
```

Or manually:

```bat
python -m pip install -r requirements.txt
python main.py
```

## How to find the app in Task Manager

| Where | What to look for |
|---|---|
| **Details** (`Ctrl+Shift+Esc` → Details) | `PulseMonitor.exe` — start typing `Pulse` in the search box |
| **Processes** (Apps) | **Pulse Monitor** group when the window is open |
| **Startup** | `PulseMonitor` if autostart is enabled in the settings |
| **Notification area** | pulse icon: double-click to open, right-click for the menu |

In a onefile build Task Manager may show **two** `PulseMonitor.exe` processes:
the bootloader unpacks the app into a temporary folder and starts the child
process. This is normal; close both (or use **Quit** in the tray menu).

If you run from source via `run.bat`, Task Manager shows `pythonw.exe`; enable
the **Command line** column to see `main.py`.

> Pulse Monitor does not install a Windows service and does not modify the
> system: it is a regular process that exits with the window (or stays in the
> tray when “Close to tray” is enabled).

## Features

- **Processes** — PID, name, CPU, memory, threads, handles, user, session,
  window, path, command line, start time and flags
  “system / service / hidden / suspicious”.
  - Search by name, PID, path, user or window title.
  - Modes “hidden only” and “suspicious only”, hiding system processes.
  - Sorting by any column, multi-row selection.
  - Terminate (normal and forced), suspend/resume, change priority, open the
    file location, copy details, detailed card, CSV export.
- **Hidden applications** — user-session processes without a visible window
  (tray apps, background app services) are marked as “hidden”. System
  processes and services are shown separately (flags “system” and “service”).
- **Suspicious processes** — heuristics: running from TEMP, system name outside
  System32/Windows, missing file, system name in a user folder, inaccessible
  path for a process with a system name.
- **Network** — receive/send speed, charts, interface table, all TCP/UDP
  connections mapped to processes, filters “established only” and “hide
  loopback”, terminate the owning process, CSV export.
- **Startup** — registry (HKCU/HKLM, Run/RunOnce, WOW6432Node), user and
  all-users Startup folders, automatic services. Enable/disable entries
  without third-party tools.
- **Overview** — CPU/RAM/disk/network/uptime, three history charts, top
  processes by CPU and memory, system information.
- **Customization** — dark/light theme, any accent color, font size, column
  set, refresh intervals, tray/autostart behavior, JSON settings export/import.
- **Background mode** — closing the window hides it to the tray and polling
  continues. Inactive tabs are polled 3× slower automatically.

## Requirements

- Windows 10/11 (x64)
- For the EXE: nothing but Windows
- For source: Python 3.10+ (tested on 3.15), `PyQt6`, `psutil`

## Self-check

Validates the core without opening a window: processes, hidden/suspicious
flags, network, startup entries, metrics and configuration.

```bat
python selfcheck.py
```

## Building the EXE

```bat
build.bat
```

The script installs PyInstaller if needed, generates the icon when missing and
produces `dist\PulseMonitor.exe` — a single windowed file.

Manually:

```bat
python -m pip install -r requirements-dev.txt
python tools\make_icon.py
python -m PyInstaller --noconfirm --clean PulseMonitor.spec
```

Build details: `PulseMonitor.spec` (onefile, windowed, `assets/pulse.ico`,
version resources from `packaging/version_info.txt`). The EXE is ~35–40 MB
(mostly Qt6) and starts 1–2 seconds slower than the sources because onefile is
unpacked into a temporary folder.

## Hotkeys

| Keys | Action |
|---|---|
| `F5` | Refresh the current tab |
| `Ctrl+F` | Focus the process search |
| `Ctrl+1…4` | Switch tabs |
| `Ctrl+,` | Settings |
| `Ctrl+Q` | Quit |

## Administrator rights

Without elevation only part of the data is available: paths and command lines
of protected processes, system registry keys, service changes. The sidebar has
a **Run as administrator** button (UAC). Elevated mode also exposes all network
connections.

## Settings and files

- `config/settings.json` — all settings (language, theme, accent, intervals,
  columns, window geometry, disabled startup entries).
- `config/settings.backup.json` — backup created when the JSON is corrupted.
- `config/error.log` — stack trace if the app crashes.
- Export/import of settings is available in the settings dialog.
- `config` location:
  - from source — next to the project;
  - from the EXE — next to `PulseMonitor.exe` (portable), otherwise
    `%APPDATA%\PulseMonitor\config`.
- Application autostart — a checkbox in the settings (written to
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). Sources use
  `pythonw.exe`, the EXE uses `PulseMonitor.exe` itself.

## Privacy

- No telemetry, ads, analytics or outbound requests.
- The repository contains no personal data, tokens or user-specific paths:
  every path is resolved at runtime.
- Only settings and, on a crash, `config/error.log` are stored locally. They
  are excluded via `.gitignore`.
- Protected processes may require administrator rights — the app never asks
  for passwords and does not install drivers.

## Why it stays lightweight

- Process snapshots use **one** `NtQuerySystemInformation` call
  (`core/sysinfo.py`): ~5–20 ms for ~300 processes instead of ~2 seconds when
  querying psutil per process. On failure it falls back to psutil automatically.
- Expensive data (path, command line, user) is fetched in small batches with a
  ~40 ms per-cycle budget and cached until the process exits.
- Tables are based on `QAbstractTableModel` instead of `QTableWidget`, so
  refreshing hundreds of rows does not recreate widgets.
- Polling threads slow down when the tab is inactive or the window is hidden.
- No heavy dependencies: only PyQt6 and psutil; charts are drawn with QPainter
  instead of QtCharts.

## Project structure

```
process-monitor/
├── main.py                    entry point
├── selfcheck.py               core self-check
├── build.bat                  EXE build
├── PulseMonitor.spec          PyInstaller configuration
├── requirements.txt           runtime dependencies
├── requirements-dev.txt       build dependencies
├── assets/pulse.ico           application icon
├── packaging/version_info.txt EXE version resources
├── tools/make_icon.py         icon generator
├── .github/workflows/build.yml CI artifact build
├── install.bat / run.bat / run-console.bat
├── core/
│   ├── app_identity.py        AUMID + Start menu shortcut (taskbar icon)
│   ├── single_instance.py     one running instance, show window on relaunch
│   ├── sysinfo.py             fast process snapshot (WinAPI)
│   ├── process_collector.py
│   ├── net_collector.py
│   ├── autorun_manager.py
│   ├── system_stats.py
│   ├── winapi.py              windows, sessions, file versions, autostart
│   ├── i18n.py                localization runtime
│   ├── translations_en.py     English dictionary
│   ├── config_manager.py
│   └── workers.py             background polling threads
├── ui/
│   ├── main_window.py         window, tray, navigation
│   ├── theme.py               dark/light themes
│   └── widgets/               overview, processes, network, startup, settings
└── config/                    created automatically (not committed)
```

## Limitations

- Windows only: WinAPI is used (`NtQuerySystemInformation`, `EnumWindows`,
  registry, `sc`).
- Closing an individual TCP connection without a driver/filter is impossible —
  you can terminate the owning process instead.
- Changing services (`sc config`) and system registry keys requires
  administrator rights.
- Service startup changes take effect after a reboot.
- “Suspicious” detection is a heuristic, not an antivirus.
- The `SYSTEM_PROCESS_INFORMATION` layout targets x64 Windows 10/11; on
  incompatibility the app automatically switches to psutil.

## Roadmap

- Temperature and SMART sensors (require drivers/rights).
- Metric history in SQLite and reports.
- Notifications when CPU/RAM thresholds are exceeded.
- Plugins and custom display profiles.
- More UI languages — the dictionary is easy to extend
  (`core/translations_en.py`).

## Publishing to GitHub

The repository is prepared: `.gitignore` excludes settings, logs, builds and
caches; the source contains no personal paths or secrets.

```bat
git add .
git commit -m "Initial commit: Pulse Monitor"
git branch -M main
git remote add origin https://github.com/<your-account>/pulse-monitor.git
git push -u origin main
```

Run `git init` first if the repository is not initialized yet.

After pushing, GitHub Actions (`.github/workflows/build.yml`) builds the EXE
and attaches it to the run as the `PulseMonitor-windows` artifact. For a
release, create a `v1.0.0` tag and attach `dist\PulseMonitor.exe` to the GitHub
Release.

## License

MIT — see [LICENSE](LICENSE). The project uses PyQt6 (GPLv3 / commercial
license from Riverbank) and psutil (BSD-3-Clause); when distributing the EXE,
comply with the dependency licenses.
