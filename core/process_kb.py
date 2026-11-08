"""База знаний о процессах Windows и популярных программах: «Что делает процесс» и можно ли его завершать."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.winapi import file_version_info

# Уровни безопасности завершения:
# - "critical": Завершать НЕЛЬЗЯ (приведёт к BSOD, зависанию или перезагрузке Windows)
# - "caution":  Системная служба или важный компонент (завершать не рекомендуется без причины)
# - "safe":     Обычное приложение или фоновый агент (можно безопасно закрыть)
# - "bloatware": Телеметрия, фоновый апдейтер или необязательный агент (можно смело завершить для освобождения ОЗУ)

SAFETY_LABELS: dict[str, str] = {
    "critical": "⛔ Критический системный процесс — завершение вызовет сбой Windows (BSOD) или потерю экрана.",
    "caution": "⚠️ Системный компонент или драйвер — завершать только при зависании.",
    "safe": "✅ Безопасно для завершения — обычное приложение (несохранённые данные в нём могут быть потеряны).",
    "bloatware": "🧹 Необязательный фоновый процесс / телеметрия — можно смело завершить для ускорения ПК.",
}

# (summary, details, category, safety)
PROCESS_KNOWLEDGE: dict[str, tuple[str, str, str, str]] = {
    # --- Ядро и критические компоненты Windows ---
    "system": (
        "Ядро Windows (NT Kernel & System)",
        "Системные потоки ядра Windows и драйверов устройств. Отвечает за работу файловой системы, памяти и оборудования.",
        "Ядро Windows",
        "critical",
    ),
    "system idle process": (
        "Бездействие системы (свободный ресурс CPU)",
        "Показывает долю процессорного времени, которое сейчас свободно и не занято другими задачами.",
        "Ядро Windows",
        "critical",
    ),
    "registry": (
        "Подсистема системного реестра Windows",
        "Хранит в оперативной памяти кусты реестра Windows для быстрого доступа ядра и служб.",
        "Ядро Windows",
        "critical",
    ),
    "memory compression": (
        "Сжатие оперативной памяти Windows",
        "Сжимает редко используемые страницы в ОЗУ вместо сброса на диск (файл подкачки), ускоряя систему.",
        "Ядро Windows",
        "critical",
    ),
    "memcompression": (
        "Сжатие оперативной памяти Windows",
        "Сжимает редко используемые страницы в ОЗУ вместо сброса на диск (файл подкачки), ускоряя систему.",
        "Ядро Windows",
        "critical",
    ),
    "secure system": (
        "Защищённое ядро Windows (Virtual Secure Mode / VBS)",
        "Изолированная область ядра Windows для защиты учётных данных и криптографии.",
        "Ядро Windows",
        "critical",
    ),
    "pulsemonitor.exe": (
        "Это само приложение Pulse Monitor (мониторинг и очистка системы)",
        "Текущее запущенное приложение Pulse Monitor 2.0 для контроля процессов, сети, автозагрузки и анализа диска WizTree.",
        "Мониторинг системы",
        "safe",
    ),
    "pulsemonitor": (
        "Это само приложение Pulse Monitor (мониторинг и очистка системы)",
        "Текущее запущенное приложение Pulse Monitor 2.0 для контроля процессов, сети, автозагрузки и анализа диска WizTree.",
        "Мониторинг системы",
        "safe",
    ),
    "smss.exe": (
        "Диспетчер сеансов Windows (Session Manager)",
        "Запускает пользовательские и системные сеансы, инициализирует переменные среды и подсистему Win32.",
        "Ядро Windows",
        "critical",
    ),
    "csrss.exe": (
        "Подсистема клиент-сервер времени выполнения",
        "Управляет консолями, потоками и графической подсистемой Win32. Принудительное завершение вызовет синий экран (BSOD).",
        "Ядро Windows",
        "critical",
    ),
    "wininit.exe": (
        "Инициализация запуска Windows",
        "Запускает ключевые фоновые службы (SCM, LSASS) при старте системы.",
        "Ядро Windows",
        "critical",
    ),
    "services.exe": (
        "Диспетчер управления службами (Service Control Manager)",
        "Запускает, останавливает и контролирует все системные службы Windows.",
        "Ядро Windows",
        "critical",
    ),
    "lsass.exe": (
        "Служба проверки подлинности и безопасности (LSASS)",
        "Отвечает за вход пользователей в систему, политики безопасности и токены доступа.",
        "Ядро Windows",
        "critical",
    ),
    "lsaiso.exe": (
        "Изоляция учётных данных (Credential Guard)",
        "Защищённый контейнер безопасности для хранения хэшей паролей и ключей.",
        "Ядро Windows",
        "critical",
    ),
    "winlogon.exe": (
        "Вход в систему Windows (Winlogon)",
        "Обрабатывает вход/выход пользователя, экран блокировки (Win+L) и сочетание Ctrl+Alt+Del.",
        "Ядро Windows",
        "critical",
    ),
    "fontdrvhost.exe": (
        "Хост драйвера пользовательских шрифтов",
        "Рендерит шрифты в изолированном песочнице-процессе для безопасности системы.",
        "Ядро Windows",
        "critical",
    ),
    "dwm.exe": (
        "Диспетчер окон рабочего стола (Desktop Window Manager)",
        "Отрисовывает все окна на экране, эффекты прозрачности, анимации и буферизацию через видеокарту.",
        "Интерфейс Windows",
        "critical",
    ),

    # --- Системные службы и оболочка Windows ---
    "svchost.exe": (
        "Хост-процесс для служб Windows (Service Host)",
        "Универсальный контейнер, внутри которого работают системные службы Windows (сеть, звук, обновления, питание и др.).",
        "Системная служба",
        "caution",
    ),
    "explorer.exe": (
        "Проводник Windows и рабочий стол",
        "Отвечает за панель задач, меню «Пуск», рабочий стол и окна папок. При зависании его можно перезапустить.",
        "Интерфейс Windows",
        "caution",
    ),
    "sihost.exe": (
        "Хост инфраструктуры оболочки (Shell Infrastructure Host)",
        "Обеспечивает работу панели задач, центра уведомлений, современных меню и прозрачности интерфейса.",
        "Интерфейс Windows",
        "caution",
    ),
    "taskhostw.exe": (
        "Хост-процесс для фоновых задач Windows",
        "Выполняет плановые системные задачи из Планировщика заданий Windows.",
        "Системная служба",
        "caution",
    ),
    "runtimebroker.exe": (
        "Посредник среды выполнения (Runtime Broker)",
        "Контролирует разрешения и доступ к файлам/устройствам для приложений из Microsoft Store и меню «Пуск».",
        "Интерфейс Windows",
        "caution",
    ),
    "applicationframehost.exe": (
        "Окно-контейнер для UWP-приложений Windows",
        "Отображает заголовки и рамки окон современных приложений Windows (Калькулятор, Параметры, Фотографии).",
        "Интерфейс Windows",
        "caution",
    ),
    "startmenuexperiencehost.exe": (
        "Меню «Пуск» Windows",
        "Отвечает за отрисовку и мгновенное открытие меню «Пуск». При перезапуске восстанавливается автоматически.",
        "Интерфейс Windows",
        "safe",
    ),
    "searchhost.exe": (
        "Окно поиска Windows на панели задач",
        "Интерфейс поиска по компьютеру в меню «Пуск». Можно завершить для освобождения памяти (перезапустится при поиске).",
        "Интерфейс Windows",
        "bloatware",
    ),
    "searchapp.exe": (
        "Приложение поиска Windows",
        "Фоновый интерфейс поиска Windows 10. Часто держит в памяти WebView, можно безопасно завершить.",
        "Интерфейс Windows",
        "bloatware",
    ),
    "searchindexer.exe": (
        "Индексатор поиска Microsoft Windows",
        "Сканирует файлы на диске для быстрого поиска в Проводнике. Если сильно грузит диск — можно временно остановить.",
        "Системная служба",
        "caution",
    ),
    "searchprotocolhost.exe": (
        "Обработчик протоколов индексации поиска",
        "Вспомогательный процесс SearchIndexer для чтения содержимого индексируемых файлов.",
        "Системная служба",
        "safe",
    ),
    "searchfilterhost.exe": (
        "Фильтр извлечения текста для поиска Windows",
        "Извлекает текст из документов (PDF, Office, TXT) во время индексации диска.",
        "Системная служба",
        "safe",
    ),
    "shellexperiencehost.exe": (
        "Элементы интерфейса оболочки Windows",
        "Отображает календарь на панели задач, быстрые настройки, центр уведомлений и всплывающие панели.",
        "Интерфейс Windows",
        "safe",
    ),
    "textinputhost.exe": (
        "Панель ввода текста, эмодзи и буфера обмена (Win+V)",
        "Обеспечивает работу экранной клавиатуры, панели эмодзи (Win+.) и истории буфера обмена.",
        "Интерфейс Windows",
        "safe",
    ),
    "ctfmon.exe": (
        "Загрузчик языковой панели и переключения раскладки",
        "Отвечает за переключение языка ввода (Alt+Shift / Win+Пробел) и рукописный ввод. Завершать не рекомендуется.",
        "Интерфейс Windows",
        "caution",
    ),
    "conhost.exe": (
        "Хост консольного окна (Console Window Host)",
        "Обеспечивает работу текстовых консолей для командной строки (cmd), PowerShell и фоновых консольных утилит.",
        "Системная служба",
        "caution",
    ),
    "openconsole.exe": (
        "Движок Windows Terminal",
        "Современный хост консоли для Windows Terminal.",
        "Разработка",
        "safe",
    ),
    "windowsterminal.exe": (
        "Приложение Терминал Windows",
        "Многовкладочный терминал для PowerShell, CMD и WSL.",
        "Разработка",
        "safe",
    ),
    "dllhost.exe": (
        "Суррогатный хост COM-объектов (COM Surrogate)",
        "Запускает внешние DLL и генераторы миниатюр картинок/видео в отдельном процессе, чтобы не уронить Проводник.",
        "Системная служба",
        "safe",
    ),
    "wmiprvse.exe": (
        "Хост поставщика WMI (Windows Management Instrumentation)",
        "Предоставляет программам информацию о системе, оборудовании и процессах через запросы WMI.",
        "Системная служба",
        "caution",
    ),
    "audiodg.exe": (
        "Изоляция графов аудиоустройств Windows",
        "Системный звуковой движок Windows: микширует звук всех программ и применяет аудиоэффекты.",
        "Графика и звук",
        "caution",
    ),
    "spoolsv.exe": (
        "Диспетчер очереди печати (Print Spooler)",
        "Управляет принтерами и очередью заданий печати. Если принтера нет — не требуется.",
        "Системная служба",
        "safe",
    ),
    "systemsettings.exe": (
        "Окно «Параметры Windows»",
        "Приложение настройки системы Windows (Win+I).",
        "Интерфейс Windows",
        "safe",
    ),
    "taskmgr.exe": (
        "Стандартный Диспетчер задач Windows",
        "Системная утилита просмотра процессов Windows.",
        "Интерфейс Windows",
        "safe",
    ),
    "smartscreen.exe": (
        "Фильтр безопасности Windows SmartScreen",
        "Проверяет скачанные из интернета программы по базе репутации Microsoft перед запуском.",
        "Защитник Windows",
        "safe",
    ),
    "msmpeng.exe": (
        "Антивирусный движок Защитника Windows (Microsoft Defender)",
        "Сканирует файлы и процессы в реальном времени на вирусы. Защищён системой от обычного завершения.",
        "Защитник Windows",
        "caution",
    ),
    "nissrv.exe": (
        "Служба сетевой инспекции Защитника Windows",
        "Анализирует сетевой трафик на предмет известных сетевых атак и эксплойтов.",
        "Защитник Windows",
        "caution",
    ),
    "securityhealthservice.exe": (
        "Служба центра безопасности Windows",
        "Отслеживает состояние антивируса, брандмауэра и защиты системы.",
        "Защитник Windows",
        "caution",
    ),
    "securityhealthsystray.exe": (
        "Значок «Безопасность Windows» в трее",
        "Отображает иконку щита Защитника Windows возле часов.",
        "Защитник Windows",
        "safe",
    ),
    "mpdefendercoreservice.exe": (
        "Ядро службы Microsoft Defender",
        "Координирует модули защиты Microsoft Defender.",
        "Защитник Windows",
        "caution",
    ),
    "aggregatorhost.exe": (
        "Агрегатор телеметрии Защитника Windows",
        "Собирает диагностическую статистику безопасности.",
        "Защитник Windows",
        "safe",
    ),
    "vmmem": (
        "Виртуальная машина WSL2 / Docker / Hyper-V",
        "Оперативная память и ресурсы процессора, выделенные подсистеме Linux (WSL2), Docker или песочнице Windows.",
        "Разработка",
        "caution",
    ),
    "vmmemwsl": (
        "Виртуальная машина подсистемы Linux (WSL2)",
        "Потребление памяти контейнерами и окружением Linux в WSL2 (можно выгрузить командой wsl --shutdown).",
        "Разработка",
        "safe",
    ),

    # --- Телеметрия, виджеты и необязательный фоновый мусор Windows ---
    "widgets.exe": (
        "Панель виджетов и новостей Windows 11",
        "Фоновая панель погоды и новостей (Win+W). Часто держит WebView2 и занимает 150–300 МБ ОЗУ.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "widgetservice.exe": (
        "Служба панели виджетов Windows",
        "Поддерживает работу виджетов Windows 11 в фоне. Можно смело завершить.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "compattelrunner.exe": (
        "Сборщик телеметрии совместимости Microsoft",
        "Сканирует диск и отправляет диагностику в Microsoft. Часто нагружает CPU и диск — можно смело завершать.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "gamebar.exe": (
        "Игровая панель Xbox Game Bar (Win+G)",
        "Оверлей для записи экрана и статистики в играх. Если не пользуетесь — можно завершить.",
        "Игры",
        "bloatware",
    ),
    "gamebarftserver.exe": (
        "Фоновый сервер Xbox Game Bar",
        "Фоновый компонент игровой панели Xbox.",
        "Игры",
        "bloatware",
    ),
    "xboxpcappft.exe": (
        "Фоновый агент приложения Xbox",
        "Поддерживает синхронизацию приложения Xbox в фоне.",
        "Игры",
        "bloatware",
    ),
    "yourphone.exe": (
        "Связь с телефоном (Phone Link)",
        "Синхронизация уведомлений и фото со смартфоном в фоне.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "phoneexperiencehost.exe": (
        "Связь с телефоном (Phone Link)",
        "Синхронизация со смартфоном Android/iOS в фоне. Если не используете — можно завершить.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "onedrive.exe": (
        "Облачная синхронизация Microsoft OneDrive",
        "Синхронизирует папки рабочего стола и документов с облаком Microsoft.",
        "Телеметрия и фон",
        "safe",
    ),
    "CrossDeviceService.exe".lower(): (
        "Служба межустройственной синхронизации Windows",
        "Отвечает за связь ПК с мобильными устройствами.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "lockapp.exe": (
        "Экран блокировки Windows",
        "Отображает заставку на экране блокировки. В обычной работе спит.",
        "Интерфейс Windows",
        "safe",
    ),
    "wermgr.exe": (
        "Отправка отчётов об ошибках Windows (Error Reporting)",
        "Отправляет дампы сбоев программ в Microsoft. Можно безопасно завершить.",
        "Телеметрия и фон",
        "bloatware",
    ),
    "werfault.exe": (
        "Обработчик сбоя программы (Windows Error Reporting)",
        "Запускается, когда какая-то программа зависла или упала, чтобы собрать дамп памяти.",
        "Телеметрия и фон",
        "safe",
    ),
    "tiworker.exe": (
        "Установщик обновлений Windows (Windows Modules Installer Worker)",
        "Устанавливает или проверяет обновления системы и сжимает хранилище WinSxS. Нагружает CPU во время обновлений.",
        "Системная служба",
        "caution",
    ),
    "trustedinstaller.exe": (
        "Установщик модулей Windows (TrustedInstaller)",
        "Системная служба установки обновлений и компонентов Windows.",
        "Системная служба",
        "caution",
    ),
    "mousocoreworker.exe": (
        "Оркестратор Центра обновления Windows (USO Worker)",
        "Проверяет наличие новых обновлений Windows в фоновом режиме.",
        "Системная служба",
        "safe",
    ),

    # --- Драйверы видеокарт (NVIDIA, AMD, Intel) ---
    "nvcontainer.exe": (
        "Контейнер служб драйвера NVIDIA",
        "Управляет телеметрией, настройками дисплея и оверлеем NVIDIA GeForce Experience / NVIDIA App.",
        "Графика и звук",
        "caution",
    ),
    "nvdisplay.container.exe": (
        "Драйвер дисплея NVIDIA (Display Container)",
        "Обеспечивает работу панели управления NVIDIA и цветовых профилей монитора.",
        "Графика и звук",
        "caution",
    ),
    "nvidia share.exe": (
        "Внутриигровой оверлей NVIDIA ShadowPlay",
        "Отвечает за запись видео в играх (Alt+Z) и счётчик FPS.",
        "Графика и звук",
        "safe",
    ),
    "nvidia web helper.exe": (
        "Веб-помощник NVIDIA GeForce Experience",
        "Отрисовывает интерфейс GeForce Experience.",
        "Графика и звук",
        "safe",
    ),
    "radeonsoftware.exe": (
        "Панель управления AMD Radeon Software (Adrenalin)",
        "Управляет настройками видеокарты AMD, профилями игр и записью экрана.",
        "Графика и звук",
        "safe",
    ),
    "amdrsserv.exe": (
        "Служба настроек и горячих клавиш AMD Radeon",
        "Фоновый сервис драйвера AMD Radeon.",
        "Графика и звук",
        "caution",
    ),
    "igfxem.exe": (
        "Модуль горячих клавиш и управления графикой Intel",
        "Фоновая утилита встроенной видеокарты Intel.",
        "Графика и звук",
        "safe",
    ),
    "igfxcuiservice.exe": (
        "Служба панели управления графикой Intel",
        "Поддерживает настройки дисплея для графики Intel.",
        "Графика и звук",
        "caution",
    ),

    # --- Браузеры и WebView ---
    "chrome.exe": (
        "Браузер Google Chrome (вкладка, расширение или GPU-процесс)",
        "Каждая вкладка, расширение и рендерер видеокарты в Chrome запускаются как отдельный процесс для изоляции.",
        "Браузер",
        "safe",
    ),
    "msedge.exe": (
        "Браузер Microsoft Edge",
        "Процесс браузера Edge (вкладки, расширения или предзагрузка в фоне).",
        "Браузер",
        "safe",
    ),
    "msedgewebview2.exe": (
        "Движок WebView2 (встроенный браузер для виджетов и приложений)",
        "Используется поиском Windows, виджетами и современными программами для отображения веб-интерфейсов.",
        "Браузер",
        "safe",
    ),
    "firefox.exe": (
        "Браузер Mozilla Firefox",
        "Основной процесс или изолированная вкладка браузера Firefox.",
        "Браузер",
        "safe",
    ),
    "opera.exe": (
        "Браузер Opera / Opera GX",
        "Процесс браузера Opera (интерфейс, вкладки или встроенные мессенджеры).",
        "Браузер",
        "safe",
    ),
    "brave.exe": (
        "Браузер Brave",
        "Процесс браузера Brave со встроенным блокировщиком рекламы.",
        "Браузер",
        "safe",
    ),
    "browser.exe": (
        "Яндекс Браузер",
        "Процесс Яндекс Браузера (вкладка, GPU-ускоритель или фоновый сервис).",
        "Браузер",
        "safe",
    ),

    # --- Мессенджеры и связь ---
    "telegram.exe": (
        "Мессенджер Telegram Desktop",
        "Клиент Telegram для ПК. Хранит скачанные фото и видео в папке кэша (можно очистить во вкладке «Точечная очистка»).",
        "Мессенджер",
        "safe",
    ),
    "discord.exe": (
        "Мессенджер и голосовой чат Discord",
        "Клиент Discord на базе Electron (обычно запускает 4–6 процессов: интерфейс, звук, GPU и оверлей для игр).",
        "Мессенджер",
        "safe",
    ),
    "viber.exe": (
        "Мессенджер Rakuten Viber",
        "Десктопный клиент Viber.",
        "Мессенджер",
        "safe",
    ),
    "whatsapp.exe": (
        "Мессенджер WhatsApp Desktop",
        "Клиент WhatsApp для Windows.",
        "Мессенджер",
        "safe",
    ),
    "skype.exe": (
        "Мессенджер Skype",
        "Клиент голосовой и видеосвязи Skype.",
        "Мессенджер",
        "safe",
    ),
    "ms-teams.exe": (
        "Корпоративный мессенджер Microsoft Teams",
        "Приложение для видеозвонков и рабочих чатов Microsoft Teams.",
        "Мессенджер",
        "safe",
    ),

    # --- Игры и лаунчеры ---
    "steam.exe": (
        "Игровой клиент Steam",
        "Основной процесс магазина и библиотеки игр Steam.",
        "Игры",
        "safe",
    ),
    "steamwebhelper.exe": (
        "Интерфейс и встроенный браузер Steam",
        "Отрисовывает магазин, сообщество, список друзей и игровой оверлей Steam (Shift+Tab) на базе Chromium.",
        "Игры",
        "safe",
    ),
    "steamservice.exe": (
        "Клиентская служба Steam",
        "Устанавливает обновления Steam и античиты для игр с правами администратора.",
        "Игры",
        "safe",
    ),
    "epicgameslauncher.exe": (
        "Лаунчер Epic Games Store",
        "Клиент магазина и библиотеки игр Epic Games.",
        "Игры",
        "safe",
    ),
    "epicwebhelper.exe": (
        "Веб-интерфейс Epic Games Launcher",
        "Отрисовывает страницы магазина внутри лаунчера Epic Games.",
        "Игры",
        "safe",
    ),
    "riotclientservices.exe": (
        "Фоновый клиент Riot Games (Valorant / LoL)",
        "Служба запуска и обновления игр Riot Games.",
        "Игры",
        "safe",
    ),
    "vgtray.exe": (
        "Значок античита Riot Vanguard в трее",
        "Уведомления античита Valorant. Если не играете прямо сейчас — можно закрыть.",
        "Игры",
        "safe",
    ),
    "battle.net.exe": (
        "Игровой лаунчер Blizzard Battle.net",
        "Клиент запуска и обновления игр Blizzard.",
        "Игры",
        "safe",
    ),

    # --- Разработка и инструменты ---
    "code.exe": (
        "Редактор кода Visual Studio Code",
        "Процесс интерфейса, расширений или языкового сервера VS Code.",
        "Разработка",
        "safe",
    ),
    "devenv.exe": (
        "Среда разработки Microsoft Visual Studio IDE",
        "Основной процесс Visual Studio.",
        "Разработка",
        "safe",
    ),
    "node.exe": (
        "Среда выполнения JavaScript (Node.js)",
        "Выполняет серверные скрипты JS/TS, сборщики (Vite/Webpack) или фоновые инструменты разработки.",
        "Разработка",
        "safe",
    ),
    "python.exe": (
        "Интерпретатор языка Python",
        "Выполняет Python-скрипт или приложение (включая сам Pulse Monitor).",
        "Разработка",
        "safe",
    ),
    "pythonw.exe": (
        "Интерпретатор Python (оконный режим без консоли)",
        "Выполняет графическое или фоновое приложение на Python.",
        "Разработка",
        "safe",
    ),
    "git.exe": (
        "Система контроля версий Git",
        "Выполняет операции с репозиториями кода (status, fetch, commit).",
        "Разработка",
        "safe",
    ),
    "docker desktop.exe": (
        "Графический интерфейс Docker Desktop",
        "Управление контейнерами Docker.",
        "Разработка",
        "safe",
    ),
    "powershell.exe": (
        "Оболочка Windows PowerShell",
        "Выполняет сценарии автоматизации и системные команды.",
        "Разработка",
        "safe",
    ),
    "pwsh.exe": (
        "Оболочка PowerShell 7+",
        "Современная кроссплатформенная версия PowerShell.",
        "Разработка",
        "safe",
    ),
    "cmd.exe": (
        "Командная строка Windows (Command Prompt)",
        "Выполняет пакетные файлы (.bat/.cmd) и консольные команды.",
        "Разработка",
        "safe",
    ),
}


def describe_process(
    name: str,
    exe: str = "",
    pid: int = 0,
    session: int = 1,
    services: list[str] | None = None,
) -> dict[str, Any]:
    """
    Возвращает человекопонятное описание процесса:
    - summary: краткое объяснение для таблицы («Что делает процесс»)
    - details: развёрнутая справка о назначении процесса
    - category: категория процесса
    - safety: "critical" | "caution" | "safe" | "bloatware"
    - safety_text: пояснение, безопасно ли завершать процесс
    - company: разработчик/издатель файла
    - product: название продукта из метаданных EXE
    - services: список служб Windows внутри процесса
    """
    low_name = (name or "").strip().lower()
    services = services or []
    ver_info = file_version_info(exe) if exe else {}
    company = ver_info.get("company", "")
    file_desc = ver_info.get("description", "")
    product = ver_info.get("product", "")

    if low_name in PROCESS_KNOWLEDGE:
        summary, details, category, safety = PROCESS_KNOWLEDGE[low_name]
        if low_name == "svchost.exe" and services:
            svc_preview = ", ".join(services[:4])
            if len(services) > 4:
                svc_preview += f" (+{len(services) - 4})"
            summary = f"Службы Windows ({svc_preview})"
            details = (
                f"{details}\nАктивные службы в этом процессе ({len(services)}): "
                + ", ".join(services[:12])
            )
    else:
        # Автоматическая классификация по пути, сессии и метаданным version.dll
        exe_low = (exe or "").lower()
        is_windows_dir = exe_low.startswith("c:\\windows\\")
        if pid in (0, 4):
            summary = "Системное ядро Windows"
            details = "Критический компонент операционной системы Windows."
            category = "Ядро Windows"
            safety = "critical"
        elif services:
            svc_preview = ", ".join(services[:3])
            base_desc = file_desc or product or name
            summary = f"Служба: {base_desc} [{svc_preview}]"
            details = (
                f"Процесс обслуживает службы Windows: {', '.join(services)}. "
                f"Описание файла: {file_desc or 'нет данных'}."
            )
            category = "Системная служба"
            safety = "caution" if is_windows_dir else "safe"
        elif is_windows_dir:
            summary = file_desc or product or "Системный компонент Windows"
            details = (
                f"Расположен в системном каталоге Windows ({exe}). "
                f"Разработчик: {company or 'Microsoft Corporation'}."
            )
            category = "Системная служба" if session == 0 else "Интерфейс Windows"
            safety = "caution"
        else:
            if file_desc and product and file_desc.lower() != product.lower():
                summary = f"{file_desc} ({product})"
            elif file_desc:
                summary = file_desc
            elif product:
                summary = f"Приложение {product}"
            elif exe:
                folder_name = Path(exe).parent.name
                summary = f"Приложение из папки «{folder_name}»"
            else:
                summary = "Фоновый или пользовательский процесс"

            if "updater" in low_name or "update" in low_name or "telemetry" in low_name or "crashhandler" in low_name:
                category = "Телеметрия и фон"
                safety = "bloatware"
                details = (
                    f"Фоновый модуль обновления или отчётов об ошибках ({summary}). "
                    "Не требуется для постоянной работы, можно безопасно завершить."
                )
            else:
                category = "Системная служба" if session == 0 else "Приложение"
                safety = "caution" if session == 0 else "safe"
                details = (
                    f"Назначение: {summary}. "
                    + (f"Издатель: {company}. " if company else "")
                    + (f"Путь: {exe}" if exe else "")
                )

    if not company and (low_name in PROCESS_KNOWLEDGE and ("Windows" in category or "Защитник" in category)):
        company = "Microsoft Corporation"

    return {
        "summary": summary,
        "details": details,
        "category": category,
        "safety": safety,
        "safety_text": SAFETY_LABELS.get(safety, SAFETY_LABELS["safe"]),
        "company": company,
        "product": product or file_desc,
        "services": services,
    }
