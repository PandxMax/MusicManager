@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Instala Python desde https://www.python.org marcando "Add Python to PATH"
  pause
  exit /b
)
if not exist .venv\Scripts\activate.bat python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name MusicManager --icon MusicManager.ico --hidden-import logo_data music_manager.py
echo.
echo Listo: tu ejecutable esta en la carpeta dist\MusicManager.exe
pause
