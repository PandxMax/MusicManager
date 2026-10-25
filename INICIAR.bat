@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python no esta instalado. Se abrira la pagina de descarga.
  echo IMPORTANTE: marca la casilla "Add Python to PATH" al instalar.
  start https://www.python.org/downloads/
  pause
  exit /b
)
if not exist .venv\Scripts\activate.bat (
  echo Preparando por primera vez, espera un momento...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
start "" pythonw music_manager.py
