"""English translations for Pulse Monitor.

Keys are the original Russian UI strings; values are English equivalents.
Split into ``EN.update`` blocks for readability.
"""

EN: dict[str, str] = {}

EN.update(
    {
        # Общие элементы
        "Pulse Monitor — мониторинг системы": "Pulse Monitor — system monitor",
        "Настройки": "Settings",
        "Настройки Pulse Monitor": "Pulse Monitor settings",
        "Закрыть": "Close",
        "Отмена": "Cancel",
        "Сохранить": "Save",
        "Сброс": "Reset",
        "Экспорт": "Export",
        "Импорт": "Import",
        "Экспорт…": "Export…",
        "Импорт…": "Import…",
        "Обзор": "Overview",
        "Процессы": "Processes",
        "Сеть": "Network",
        "Автозагрузка": "Startup",
        "Система": "System",
        "Процесс": "Process",
        "Значение": "Value",
        "Тип": "Type",
        "Название": "Name",
        "Команда": "Command",
        "Расположение": "Location",
        "Примечание": "Note",
        "Состояние": "Status",
        "Включено": "Enabled",
        "Отключено": "Disabled",
        "Ожидание данных…": "Waiting for data…",
        "Сбор данных…": "Collecting data…",
        "Загрузка…": "Loading…",
        "Готово": "Ready",
        "Ошибка": "Error",
        "Предупреждение": "Warning",
        "Результат": "Result",
        "Нет данных": "No data",
        "Нет данных для экспорта": "No data to export",
        "Не удалось сохранить файл": "Could not save the file",
        "Проводник": "Explorer",
        "Недоступно": "Unavailable",
        "секунд": "seconds",
        "сек": "s",
        "мин": "min",
        "час": "h",
        "д": "d",
    }
)

EN.update(
    {
        # Навигация и главное окно
        "Сводка по системе, графики и топ процессов": "System summary, charts and top processes",
        "Все процессы, включая скрытые и фоновые": "All processes, including hidden and background",
        "Скорость интерфейсов и соединения процессов": "Interface throughput and process connections",
        "Реестр, папка «Автозагрузка» и службы": "Registry, Startup folder and services",
        "Pulse Monitor — лёгкий мониторинг": "Pulse Monitor — lightweight monitoring",
        "Свернуть в трей": "Minimize to tray",
        "Показать окно": "Show window",
        "Выход": "Quit",
        "Открыть Pulse Monitor": "Open Pulse Monitor",
        "Обновить": "Refresh",
        "Обновить текущую вкладку": "Refresh current tab",
        "Настройки…": "Settings…",
        "Запустить от администратора": "Run as administrator",
        "Права администратора получены — доступны все системные данные.": (
            "Administrator rights granted — all system data is available."
        ),
        "Ограниченный доступ: часть системных данных и путей скрыта": (
            "Limited access: some system data and paths are hidden"
        ),
        "Права администратора": "Administrator rights",
        "Не удалось перезапустить приложение.": "Could not restart the application.",
        "Поиск по имени, PID, пути, пользователю или окну…": (
            "Search by name, PID, path, user or window…"
        ),
        "Поиск по процессу, PID или адресу…": "Search by process, PID or address…",
        "Готово · процессов: {count}": "Ready · processes: {count}",
        "Обновлено: {time}": "Updated: {time}",
        "Приложение свёрнуто в трей и продолжает мониторинг.": (
            "The app is minimized to tray and keeps monitoring."
        ),
        "Закрыть в трей": "Close to tray",
        # Колонки процессов
        "PID": "PID",
        "Имя": "Name",
        "Флаги": "Flags",
        "CPU %": "CPU %",
        "Память": "Memory",
        "Память %": "Memory %",
        "Потоки": "Threads",
        "Дескрипторы": "Handles",
        "Пользователь": "User",
        "Сессия": "Session",
        "PPID": "PPID",
        "Запущен": "Started",
        "Окно": "Window",
        "Путь": "Path",
        "Статус": "Status",
        # Флаги и статусы процессов
        "скрыт": "hidden",
        "системный": "system",
        "служба": "service",
        "подозрительный": "suspicious",
        "запущен из TEMP": "running from TEMP",
        "системное имя вне System32": "system name outside System32",
        "файл отсутствует": "file is missing",
        "системное имя в пользовательской папке": "system name in a user folder",
        "путь недоступен": "path unavailable",
        "Работает": "Running",
        "Ожидание": "Waiting",
        "Ожидание диска": "Disk wait",
        "Остановлен": "Stopped",
        "Отладка": "Debugging",
        "Зомби": "Zombie",
        "Завершён": "Exited",
        "Завершается": "Exiting",
        "Пробуждение": "Waking",
        "Простой": "Idle",
        "Заблокирован": "Blocked",
        "Ожидает": "Waiting",
        "Приостановлен": "Suspended",
        "Припаркован": "Parked",
    }
)

EN.update(
    {
        # Действия с процессами
        "Подробности процесса": "Process details",
        "Завершить процесс": "End process",
        "Завершить": "End process",
        "Завершение": "Termination",
        "Завершение процесса": "End process",
        "Приостановить": "Suspend",
        "Продолжить": "Resume",
        "Приоритет…": "Priority…",
        "Открыть папку файла": "Open file location",
        "Копировать сведения": "Copy details",
        "Экспорт в CSV…": "Export to CSV…",
        "Только скрытые": "Hidden only",
        "Только подозрительные": "Suspicious only",
        "Все процессы": "All processes",
        "Показывать системные": "Show system processes",
        "Завершить выбранные": "End selected",
        "Приостановить выбранные": "Suspend selected",
        "Продолжить выбранные": "Resume selected",
        "Скрыть системные": "Hide system processes",
        "Выберите процесс в списке": "Select a process in the list",
        "Выберите хотя бы один процесс": "Select at least one process",
        "Завершить {count} процесс(ов)?": "End {count} process(es)?",
        "Системный процесс защищён": "This system process is protected",
        "Завершить {name} (PID {pid})?": "End {name} (PID {pid})?",
        "Процесс завершён": "Process ended",
        "Процесс приостановлен": "Process suspended",
        "Процесс продолжен": "Process resumed",
        "Процесс уже завершён": "Process has already exited",
        "Процесс не найден": "Process not found",
        "Недостаточно прав. Запустите монитор от администратора.": (
            "Not enough permissions. Run the monitor as administrator."
        ),
        "Недостаточно прав для приостановки процесса": (
            "Not enough permissions to suspend the process"
        ),
        "Недостаточно прав для продолжения процесса": (
            "Not enough permissions to resume the process"
        ),
        "Недостаточно прав для смены приоритета": (
            "Not enough permissions to change priority"
        ),
        "Доступ запрещён (нужны права администратора)": (
            "Access denied (administrator rights required)"
        ),
        "Процесс не завершился за 2 секунды. Попробуйте принудительное завершение.": (
            "The process did not exit within 2 seconds. Try force termination."
        ),
        "Приоритет изменён: {priority}": "Priority changed: {priority}",
        "Неизвестный приоритет": "Unknown priority",
        "Низкий": "Low",
        "Ниже обычного": "Below normal",
        "Обычный": "Normal",
        "Выше обычного": "Above normal",
        "Высокий": "High",
        "Реального времени": "Realtime",
        "Приоритет процесса": "Process priority",
        "Новый приоритет для {name} ({pid}):": "New priority for {name} ({pid}):",
        "Приоритет": "Priority",
        "Расположение файла": "File location",
        "Путь к файлу процесса недоступен. Попробуйте запустить монитор от имени администратора.": (
            "The process file path is unavailable. Try running the monitor as administrator."
        ),
        "Не удалось открыть папку процесса": "Could not open the process folder",
        "Не удалось открыть файл": "Could not open the file",
        "Экспорт процессов": "Export processes",
        "Экспортировано строк: {count} → {path}": "Exported rows: {count} → {path}",
        "Скопировано строк: {count}": "Copied rows: {count}",
        "Ошибка: {error}": "Error: {error}",
        "Процессов {action}: {count}": "Processes {action}: {count}",
        "завершено": "ended",
        "приостановлено": "suspended",
        "продолжено": "resumed",
        "Путь: {path}": "Path: {path}",
        "Командная строка: {cmd}": "Command line: {cmd}",
        "Пользователь: {user}": "User: {user}",
        "Окно: {title}": "Window: {title}",
        "Статус: {status}": "Status: {status}",
        "Потоки: {threads} · дескрипторы: {handles}": (
            "Threads: {threads} · handles: {handles}"
        ),
        "Сессия: {session} · PPID: {ppid}": "Session: {session} · PPID: {ppid}",
    }
)

EN.update(
    {
        # Обзор
        "Загрузка CPU": "CPU load",
        "Оперативная память": "RAM",
        "Системный диск": "System disk",
        "Время работы": "Uptime",
        "с момента загрузки": "since boot",
        "Процессов": "Processes",
        "скрытых: 0": "hidden: 0",
        "Топ по CPU": "Top by CPU",
        "Топ по памяти": "Top by memory",
        "Компьютер": "Computer",
        "ОС": "OS",
        "Процессор": "CPU",
        "Ядра": "Cores",
        "Загрузка": "Usage",
        "Сеть (приём)": "Network (receive)",
        "физ./лог.": "phys./log.",
        "своп: {value}": "swap: {value}",
        "соединений: {count}": "connections: {count}",
        "скрытых: {hidden}: · подозрительных: {suspicious}": (
            "hidden: {hidden} · suspicious: {suspicious}"
        ),
        "скрытых: {hidden} · подозрительных: {suspicious}": (
            "hidden: {hidden} · suspicious: {suspicious}"
        ),
        "Выберите процесс в списке топ-процессов": (
            "Select a process in the top processes list"
        ),
        "Открыть подробности": "Open details",
        "Открыть папку": "Open folder",
        "Обновить данные": "Refresh data",
        # Сеть
        "Локальный адрес": "Local address",
        "Удалённый адрес": "Remote address",
        "Семейство": "Family",
        "Скорость": "Speed",
        "Приём": "Receive",
        "Передача": "Send",
        "Интерфейсы": "Interfaces",
        "Соединения": "Connections",
        "Только установленные": "Established only",
        "Скрыть локальные": "Hide loopback",
        "Скрыть локальные соединения": "Hide loopback connections",
        "Завершить процесс по соединению": "End process for connection",
        "Копировать адреса": "Copy addresses",
        "Экспорт соединений": "Export connections",
        "Нет соединений для экспорта": "No connections to export",
        "Выберите соединение в таблице": "Select a connection in the table",
        "У выбранных соединений нет PID": "Selected connections have no PID",
        "Завершить процесс(ы): {names}?": "End process(es): {names}?",
        "Экспортировано соединений: {count}": "Connections exported: {count}",
        "Нет прав на чтение всех соединений (нужен администратор)": (
            "No permission to read all connections (administrator required)"
        ),
        "Соединений: {count}": "Connections: {count}",
        "Установленных: {count}": "Established: {count}",
        "Слушающих: {count}": "Listening: {count}",
        "Процессов: {count}": "Processes: {count}",
        "Адрес: {address}": "Address: {address}",
        "Скорость: {speed}": "Speed: {speed}",
        "Принято: {received} · отправлено: {sent}": (
            "Received: {received} · sent: {sent}"
        ),
    }
)

EN.update(
    {
        # Автозагрузка
        "Тип:": "Type:",
        "Все типы": "All types",
        "Реестр": "Registry",
        "Папка": "Folder",
        "Служба": "Service",
        "Службы Windows · автозапуск": "Windows services · automatic start",
        "Пользователь · Run": "User · Run",
        "Пользователь · RunOnce": "User · RunOnce",
        "Система · Run": "System · Run",
        "Система · RunOnce": "System · RunOnce",
        "Система x86 · Run": "System x86 · Run",
        "Пользователь": "User",
        "Все пользователи": "All users",
        "отключено монитором": "disabled by the monitor",
        "Включить": "Enable",
        "Отключить": "Disable",
        "Открыть файл": "Open file",
        "Открыть расположение": "Open location",
        "Обновить список": "Refresh list",
        "Элементов: {total} · включено: {enabled} · отключено: {disabled}": (
            "Entries: {total} · enabled: {enabled} · disabled: {disabled}"
        ),
        "· показано: {shown}": "· shown: {shown}",
        "Выберите элемент автозагрузки": "Select a startup entry",
        "Ошибка чтения автозагрузки: {error}": "Could not read startup entries: {error}",
        "Команда отсутствует": "Command is missing",
        "Не удалось открыть файл.\n\n{error}": "Could not open the file.\n\n{error}",
        "Права администратора получены — доступны все элементы автозагрузки.": (
            "Administrator rights granted — all startup entries are available."
        ),
        "Без прав администратора нельзя менять системные ключи реестра и службы. Запись пользователя и папка «Автозагрузка» доступны.": (
            "Without administrator rights you cannot modify system registry keys or services. "
            "User entries and the Startup folder are available."
        ),
        "Этот элемент нельзя изменить": "This entry cannot be changed",
        "Недостаточно данных о записи реестра": "Not enough registry entry data",
        "Элемент отключён. Значение сохранено в настройках монитора.": (
            "Entry disabled. The value was saved in the monitor settings."
        ),
        "Элемент снова включён в автозагрузку": "Entry enabled again",
        "Файл автозагрузки не найден": "Startup file not found",
        "Элемент отключён (файл переименован в .disabled)": (
            "Entry disabled (file renamed to .disabled)"
        ),
        "Не найдено имя службы": "Service name not found",
        "Нужны права администратора для изменения службы": (
            "Administrator rights are required to change the service"
        ),
        "Не удалось изменить службу": "Could not change the service",
        "Служба {state}. Изменения вступят в силу после перезагрузки.": (
            "Service {state}. Changes take effect after a reboot."
        ),
        "отключена": "disabled",
        "включена": "enabled",
        "Нужны права администратора для изменения этого ключа": (
            "Administrator rights are required to change this key"
        ),
        "Не удалось отключить: {error}": "Could not disable: {error}",
        "Не удалось включить: {error}": "Could not enable: {error}",
        "Не удалось изменить файл: {error}": "Could not modify the file: {error}",
        "Недостаточно прав для переименования файла": (
            "Not enough permissions to rename the file"
        ),
        "Не удалось изменить автозапуск Windows. Проверьте права доступа к реестру.": (
            "Could not change Windows autostart. Check registry permissions."
        ),
        # Подробности процесса
        "Основное": "General",
        "Файл": "File",
        "Командная строка": "Command line",
        "Рабочая папка": "Working directory",
        "Владелец": "Owner",
        "Версия файла": "File version",
        "Описание": "Description",
        "Компания": "Company",
        "Дочерние процессы": "Child processes",
        "Действия": "Actions",
        "Не удалось получить сведения о процессе": "Could not get process details",
        "Процесс недоступен": "Process unavailable",
        "Нет дочерних процессов": "No child processes",
        "Скопировать": "Copy",
        "Обновить": "Refresh",
    }
)

EN.update(
    {
        # Настройки
        "Внешний вид": "Appearance",
        "Интервалы": "Intervals",
        "Поведение": "Behavior",
        "Язык": "Language",
        "Язык интерфейса:": "Interface language:",
        "Системный (авто)": "System (auto)",
        "Русский": "Russian",
        "Тёмная": "Dark",
        "Светлая": "Light",
        "Тема оформления:": "Theme:",
        "Акцентный цвет:": "Accent color:",
        "Выбрать цвет…": "Choose color…",
        "Размер шрифта:": "Font size:",
        "Тема и акцент применяются ко всем элементам: таблицам, графикам, кнопкам, меню и боковой панели.": (
            "The theme and accent color apply to every element: tables, charts, "
            "buttons, menus and the sidebar."
        ),
        "Интервал обновления процессов:": "Process refresh interval:",
        "Интервал обновления сети:": "Network refresh interval:",
        "Интервал обновления обзора:": "Dashboard refresh interval:",
        "Показывать системные процессы": "Show system processes",
        "Подтверждать завершение процессов": "Confirm process termination",
        "Столбцы таблицы процессов": "Process table columns",
        "Выберите отображаемые столбцы.": "Select the columns to display.",
        "Нужен хотя бы один отображаемый столбец.": (
            "At least one column must be visible."
        ),
        "Закрывать окно в трей": "Close window to tray",
        "Запускать свёрнутым в трей": "Start minimized to tray",
        "Запускать вместе с Windows": "Start with Windows",
        "Запоминать размер и позицию окна": "Remember window size and position",
        "Снижать частоту опроса в неактивных вкладках": (
            "Reduce polling rate on inactive tabs"
        ),
        "Сброс настроек": "Reset settings",
        "Вернуть все настройки к значениям по умолчанию?": (
            "Reset all settings to their default values?"
        ),
        "Экспорт настроек": "Export settings",
        "Импорт настроек": "Import settings",
        "Не удалось сохранить настройки": "Could not save the settings",
        "Настройки загружены. Нажмите «Сохранить».": "Settings loaded. Click “Save”.",
        "Не удалось прочитать файл настроек": "Could not read the settings file",
        "Настройки": "Settings",
        "Настройки сохранены": "Settings saved",
        "Для смены языка приложение перезапустит окно.": (
            "The window will be recreated to apply the new language."
        ),
        # Единицы измерения
        "Б": "B",
        "КБ": "KB",
        "МБ": "MB",
        "ГБ": "GB",
        "ТБ": "TB",
        "ПБ": "PB",
        "/с": "/s",
        "Мбит/с": "Mbit/s",
        "Неизвестный процессор": "Unknown CPU",
    }
)

EN.update(
    {
        "MONITOR · все процессы": "MONITOR · all processes",
        "Ошибка мониторинга — {message}": "Monitoring error — {message}",
        "Процессов: {total} · скрытых: {hidden} · подозрительных: {suspicious} · опрос: {ms:.0f} мс": (
            "Processes: {total} · hidden: {hidden} · suspicious: {suspicious} · "
            "sampled in {ms:.0f} ms"
        ),
        "Светлая тема": "Light theme",
        "Тёмная тема": "Dark theme",
        "Приложение продолжает работать в фоне. Двойной клик по иконке — открыть.": (
            "The app keeps running in the background. Double-click the icon to open."
        ),
        "Время загрузки": "Boot time",
        "{physical} физ. / {logical} лог.": "{physical} physical / {logical} logical",
        "мс": "ms",
        "Обновление": "Refresh",
        "Процессы:": "Processes:",
        "Сеть:": "Network:",
        "Обзор (графики):": "Dashboard (charts):",
        "Чем больше интервал, тем ниже нагрузка. При неактивной вкладке опрос автоматически замедляется в 3 раза. Рекомендуемые значения: 2000 мс для процессов и сети, 1200 мс для обзора.": (
            "A larger interval means lower load. Inactive tabs are polled 3× slower "
            "automatically. Recommended values: 2000 ms for processes and network, "
            "1200 ms for the dashboard."
        ),
        "Показывать системные процессы и службы": "Show system processes and services",
        "Спрашивать подтверждение перед завершением": (
            "Ask for confirmation before terminating"
        ),
        "Отображаемые столбцы": "Visible columns",
        "Скрывать окно в трей при закрытии (работа в фоне)": (
            "Hide the window to tray on close (run in background)"
        ),
        "Добавить Pulse Monitor в автозапуск Windows": (
            "Add Pulse Monitor to Windows startup"
        ),
        "Запоминать размер и положение окна": "Remember window size and position",
        "Снижать частоту опроса, когда вкладка неактивна": (
            "Reduce polling rate when the tab is inactive"
        ),
        "Фоновый режим использует те же потоки опроса. Без прав администратора часть системных данных и путей процессов будет недоступна.": (
            "Background mode uses the same polling threads. Without administrator "
            "rights some system data and process paths are unavailable."
        ),
        "Сбросить всё": "Reset all",
        "Столбцы": "Columns",
        "Должен быть выбран хотя бы один отображаемый столбец.": (
            "At least one column must be visible."
        ),
        "Признаки: {reasons}": "Indicators: {reasons}",
        "Флаги: {flags}": "Flags: {flags}",
        "Системные": "System",
        "Ещё": "More",
        "Поиск: имя, PID, путь, пользователь, окно…": (
            "Search: name, PID, path, user, window…"
        ),
        "Подробная информация": "Detailed information",
        "Приостановить процесс": "Suspend process",
        "Продолжить процесс": "Resume process",
        "Открыть расположение файла": "Open file location",
        "Завершить принудительно": "Force terminate",
        "Сначала выберите процесс в таблице": (
            "Select a process in the table first"
        ),
        "Завершение процессов": "Terminate processes",
        "Завершить: {names}?": "Terminate: {names}?",
        "и ещё {count}": "and {count} more",
        "системный процесс защищён": "system process is protected",
        "Результат завершения": "Termination result",
        "Завершено процессов: {count}\n\n{errors}": (
            "Processes terminated: {count}\n\n{errors}"
        ),
        "Завершено процессов: {count}": "Processes terminated: {count}",
        "Показано {shown} из {total} · скрытых {hidden} · подозрительных {suspicious}": (
            "Showing {shown} of {total} · hidden {hidden} · suspicious {suspicious}"
        ),
        "опрос {ms:.0f} мс": "sample {ms:.0f} ms",
        "Ошибка опроса процессов: {error}": "Process polling error: {error}",
    }
)

EN.update(
    {
        "Отдача": "Upload",
        "ожидание": "waiting",
        "из них установлено: 0": "established: 0",
        "Процессов в сети": "Networked processes",
        "слушающих портов: 0": "listening ports: 0",
        "Входящий трафик": "Inbound traffic",
        "Исходящий трафик": "Outbound traffic",
        "Сетевые интерфейсы": "Network interfaces",
        "Интерфейс": "Interface",
        "IP-адрес": "IP address",
        "Активные соединения": "Active connections",
        "Поиск: процесс, PID, адрес, порт…": "Search: process, PID, address, port…",
        "Копировать": "Copy",
        "обновлено: {count} соединений": "updated: {count} connections",
        "Показано {shown} из {total} соединений": (
            "Showing {shown} of {total} connections"
        ),
        "всего принято {value}": "total received {value}",
        "всего отправлено {value}": "total sent {value}",
        "установлено: {count}": "established: {count}",
        "слушающих портов: {count}": "listening ports: {count}",
        "Подключён": "Connected",
        "Отключён": "Disconnected",
        "Соединений": "Connections",
        "Ошибка опроса сети: {error}": "Network polling error: {error}",
        "Не удалось получить соединения: {error}": (
            "Could not read connections: {error}"
        ),
        "Перезапустить от администратора": "Restart as administrator",
        "Включить / Отключить": "Enable / Disable",
        "Поиск: название, команда, расположение…": (
            "Search: name, command, location…"
        ),
        "Неизвестный тип элемента": "Unknown entry type",
        "Родительский PID": "Parent PID",
        "Память (RSS)": "Memory (RSS)",
        "Виртуальная память": "Virtual memory",
        "Доля памяти": "Memory share",
        "Скопировать сведения": "Copy details",
        "Потоков": "Threads",
        "Дескрипторов": "Handles",
        "Открытых файлов": "Open files",
        "Соединения": "Connections",
        "Нет активных соединений": "No active connections",
        "Процесс {pid} — подробности": "Process {pid} — details",
        "Pulse Monitor — ошибка": "Pulse Monitor — error",
        "Неизвестная ошибка": "Unknown error",
        "Неизвестный тип элемента": "Unknown entry type",
        "Утилита не найдена": "Utility not found",
        "Превышено время ожидания": "Timed out",
    }
)
