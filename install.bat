@echo off
rem Установка зависимостей Pulse Monitor
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден в PATH. Установите Python 3.10+ с python.org
    pause
    exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Не удалось установить зависимости.
) else (
    echo.
    echo Готово! Запускайте run.bat
)
pause
