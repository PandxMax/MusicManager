@echo off
cd /d "%~dp0"
echo.
echo  MUSIC MANAGER - Crear e instalar el programa
echo  ============================================
echo  Esto crea MusicManager.exe, lo instala y crea accesos directos.
echo  La primera vez necesita internet y puede tardar unos minutos.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_programa.ps1"
echo.
pause
