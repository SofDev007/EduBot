@echo off
REM EduBot Flask Application Launcher for Windows
REM Usage: run.bat

cd /d "%~dp0"
call venv\Scripts\activate.bat
python start.py
pause
