@echo off
rem Builds dist\AusTree Atlas.exe (a single portable file).
rem First-time setup:  python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
cd /d "%~dp0"
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name "AusTree Atlas" --icon icon.ico --add-data "app;app" main.py
echo.
echo Done: dist\AusTree Atlas.exe
