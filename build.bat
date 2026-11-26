@echo off
rem Builds dist\ArborID.exe (a single portable file).
rem First-time setup:  python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
cd /d "%~dp0"
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name "ArborID" --icon icon.ico --add-data "app;app" --add-data "model;model" main.py
echo.
echo Done: dist\ArborID.exe
