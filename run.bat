@echo off
rem Запуск без консольного окна (фоновый режим с иконкой в трее)
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
    echo Python не найден в PATH. Установите Python 3.10+ и повторите.
    pause
    exit /b 1
)
start "" pythonw "%~dp0main.py"
