@echo off
rem Runs the userbot and starts it again if it stops or crashes.
rem Close this window (or press Ctrl+C twice) to stop for good.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set USERBOT_SUPERVISED=1
:loop
echo [%date% %time%] starting userbot...
python main.py
echo [%date% %time%] userbot stopped (code %errorlevel%), restarting in 10 seconds...
timeout /t 10 /nobreak >nul
goto loop
