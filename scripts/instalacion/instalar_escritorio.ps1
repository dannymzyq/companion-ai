# Descarga Electron (el entorno de la app de escritorio: ventana propia y avatar flotante) desde su
# publicación oficial en GitHub y comprueba la suma SHA-256 antes de descomprimirlo.
#   powershell -ExecutionPolicy Bypass -File scripts\instalacion\instalar_escritorio.ps1
param([string]$Version = "45.3.0")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$destino = Join-Path $raiz "desktop\electron"
$marca = Join-Path $destino "version"
. "$PSScriptRoot\comun_instalacion.ps1"

if ((Test-Path "$destino\electron.exe") -and (Test-Path $marca) -and ((Get-Content $marca -Raw).Trim() -eq $Version)) {
    Write-Host "Electron $Version ya está instalado."
    exit 0
}

$base = "https://github.com/electron/electron/releases/download/v$Version"
$archivo = "electron-v$Version-win32-x64.zip"
$zip = Join-Path $env:TEMP $archivo

Write-Host "Descargando $archivo (~160 MB)..."
Descargar "$base/$archivo" $zip "App de escritorio (Electron)"
$sumas = (Invoke-WebRequest -Uri "$base/SHASUMS256.txt" -UseBasicParsing).Content
if ($sumas -is [byte[]]) { $sumas = [System.Text.Encoding]::ASCII.GetString($sumas) }
$linea = ($sumas -split "`n") | Where-Object { $_ -match "\*?$([regex]::Escape($archivo))\s*$" } | Select-Object -First 1
if (-not $linea) { Remove-Item $zip -Force; throw "No encontré la suma de $archivo en SHASUMS256.txt" }
$esperada = ($linea -split "\s+")[0].ToLower()
$real = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($real -ne $esperada) { Remove-Item $zip -Force; throw "La suma SHA-256 no coincide: se descarta la descarga." }
Write-Host "Suma SHA-256 verificada."

if (Test-Path $destino) { Remove-Item $destino -Recurse -Force }
Marca progreso 100 "Descomprimiendo la app de escritorio…"
Expand-Archive -Path $zip -DestinationPath $destino
Remove-Item $zip -Force
Set-Content -Path $marca -Value $Version -Encoding ascii
Write-Host "Electron $Version instalado en desktop\electron."
