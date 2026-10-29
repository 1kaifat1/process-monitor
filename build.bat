@echo off
rem Сборка PulseMonitor.exe (portable, один файл)
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден в PATH. Установите Python 3.10+ с python.org
    pause
    exit /b 1
)

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller не найден — устанавливаю...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo Не удалось установить PyInstaller.
        pause
        exit /b 1
    )
)

if not exist "assets\pulse.ico" (
    echo Создаю иконку приложения...
    python tools\make_icon.py
)

python -m PyInstaller --noconfirm --clean PulseMonitor.spec
if errorlevel 1 (
    echo.
    echo Сборка не удалась. Подробности выше.
    pause
    exit /b 1
)

echo.
echo Готово: "%~dp0dist\PulseMonitor.exe"
pause
