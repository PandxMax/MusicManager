# Crea Music Manager como un programa normal de Windows (MusicManager.exe),
# lo instala en tu equipo y crea accesos directos.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
$log = Join-Path $PSScriptRoot "crear_programa_log.txt"
try { Start-Transcript -Path $log -Force | Out-Null } catch {}

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Fail($t) {
    Write-Host ""
    Write-Host "ERROR: $t" -ForegroundColor Red
    Write-Host "Se guardo un registro en: $log (puedes mandarmelo para ayudarte)."
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

if (-not (Test-Path (Join-Path $PSScriptRoot "music_manager.py"))) {
    Fail "No encuentro music_manager.py. Extrae el ZIP completo en una carpeta antes de ejecutar este archivo."
}

# ---------- 1) Buscar Python (o instalarlo)
function Test-Python($c) {
    try {
        $a = $c.Args
        $out = (& $c.Exe @a --version 2>&1 | Out-String)
        if ($out -match "Python 3\.(\d+)") { return ([int]$Matches[1] -ge 9) }
    } catch {}
    return $false
}
function Find-Python {
    $cands = New-Object System.Collections.ArrayList
    [void]$cands.Add(@{ Exe = "py"; Args = @("-3") })
    [void]$cands.Add(@{ Exe = "python"; Args = @() })
    $dirs = Get-ChildItem "$env:LocalAppData\Programs\Python" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
    foreach ($d in $dirs) { [void]$cands.Add(@{ Exe = (Join-Path $d.FullName "python.exe"); Args = @() }) }
    foreach ($c in $cands) { if (Test-Python $c) { return $c } }
    return $null
}

Step "Buscando Python..."
$py = Find-Python
if (-not $py) {
    Step "Python no esta instalado. Intentando instalarlo automaticamente..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $py = Find-Python
    }
}
if (-not $py) {
    Start-Process "https://www.python.org/downloads/"
    Fail "Instala Python 3.12 desde python.org (marca la casilla 'Add Python to PATH') y vuelve a ejecutar CREAR_PROGRAMA.bat."
}

# ---------- 2) Entorno y componentes
$venv = Join-Path $PSScriptRoot ".venv"
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Step "Preparando entorno de Python..."
    $a = $py.Args
    & $py.Exe @a -m venv $venv
    if (-not (Test-Path $vpy)) { Fail "No se pudo crear el entorno de Python." }
}
Step "Instalando componentes (la primera vez puede tardar unos minutos)..."
& $vpy -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { Fail "No se pudieron instalar los componentes. Revisa tu conexion a internet." }

# ---------- 3) Crear el .exe
Step "Creando MusicManager.exe (de 1 a 3 minutos)..."
if (Test-Path "build") { Remove-Item "build" -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force -ErrorAction SilentlyContinue }
& $vpy -m PyInstaller --noconfirm --clean --windowed --name MusicManager --icon MusicManager.ico --hidden-import logo_data --hidden-import spectro --hidden-import ytview --hidden-import i18n --collect-all imageio_ffmpeg music_manager.py
if (-not (Test-Path "dist\MusicManager\MusicManager.exe")) { Fail "No se pudo crear MusicManager.exe." }

# ---------- 4) Instalar como programa normal
Step "Instalando en tu equipo..."
$dest = Join-Path $env:LocalAppData "Programs\Music Manager"
Get-Process -Name MusicManager -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Copy-Item "dist\MusicManager\*" $dest -Recurse -Force
Copy-Item "MusicManager.ico" $dest -Force
$exe = Join-Path $dest "MusicManager.exe"
if (-not (Test-Path $exe)) { Fail "No se pudo copiar el programa a $dest." }

# Desinstalador
$u = @'
Add-Type -AssemblyName System.Windows.Forms
$r = [System.Windows.Forms.MessageBox]::Show("Quieres desinstalar Music Manager?`n(Tu musica no se toca.)", "Music Manager", "YesNo", "Question")
if ($r -ne "Yes") { exit }
$dest = $PSScriptRoot
Get-Process -Name MusicManager -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Music Manager.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Music Manager.lnk") -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicManager" -Recurse -ErrorAction SilentlyContinue
Start-Process cmd.exe -WindowStyle Hidden -ArgumentList "/c ping 127.0.0.1 -n 3 >nul & rmdir /s /q `"$dest`""
'@
Set-Content -Path (Join-Path $dest "desinstalar.ps1") -Value $u -Encoding UTF8

# Accesos directos (escritorio y menu Inicio)
function New-Shortcut($path) {
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $exe
    $s.WorkingDirectory = $dest
    $s.IconLocation = "$exe,0"
    $s.Description = "Music Manager"
    $s.Save()
}
try {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "Music Manager.lnk")
    New-Shortcut (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Music Manager.lnk")
} catch { Write-Host "No se pudieron crear los accesos directos: $_" -ForegroundColor Yellow }

# Aparece en Configuracion > Aplicaciones (para desinstalar)
try {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicManager"
    New-Item -Path $key -Force | Out-Null
    $un = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"" + (Join-Path $dest "desinstalar.ps1") + "`""
    $vals = [ordered]@{
        DisplayName = "Music Manager"; DisplayVersion = "1.0"; Publisher = "Music Manager"
        DisplayIcon = (Join-Path $dest "MusicManager.ico"); InstallLocation = $dest; UninstallString = $un
    }
    foreach ($k in $vals.Keys) { New-ItemProperty -Path $key -Name $k -Value $vals[$k] -PropertyType String -Force | Out-Null }
    New-ItemProperty -Path $key -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $key -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
} catch { Write-Host "No se pudo registrar el desinstalador: $_" -ForegroundColor Yellow }

# Version portatil (opcional, para copiar a un USB u otro PC)
try {
    Compress-Archive -Path "dist\MusicManager\*" -DestinationPath "MusicManager_portable.zip" -Force
} catch {}

Write-Host ""
Write-Host "LISTO. Music Manager quedo instalado." -ForegroundColor Green
Write-Host "  - Acceso directo en el Escritorio y en el menu Inicio."
Write-Host "  - Programa: $exe"
Write-Host "  - Version portatil: MusicManager_portable.zip (en esta carpeta)"
Write-Host "  - Para desinstalar: Configuracion > Aplicaciones > Music Manager."
try { Stop-Transcript | Out-Null } catch {}
Start-Process $exe
