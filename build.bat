@echo off
rem Builds dist\ArborID.exe (a single portable file).
rem First-time setup:  python -m venv .venv  then  .venv\Scripts\python -m pip install -r requirements.txt
rem ("python -m" keeps working if the project folder is renamed or moved; pip.exe/pyinstaller.exe don't)
cd /d "%~dp0"
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name "ArborID" --icon icon.ico --add-data "app;app" --add-data "model;model" main.py
echo.
echo Done: dist\ArborID.exe
