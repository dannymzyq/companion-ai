# Arranca el companion y abre su ventana.   Doble clic en Companion.bat, o:
#   powershell -ExecutionPolicy Bypass -File iniciar.ps1
param([switch]$SinVentana)      # solo arranca el servidor, sin abrir la ventana
$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
Set-Location $raiz

if (-not (Test-Path ".venv\Scripts\python.exe") -or -not (Test-Path "web\vendor\three\build\three.module.min.js")) {
    Write-Host "Primera vez: preparando el entorno (tarda unos minutos)..."
    & "$raiz\instalar.ps1"
}

# Servicios: el cerebro local (Ollama) se arranca aqui si no esta abierto; la voz completa (voz\servidor.py,
# puerto 8210) la arranca y la para el propio companion segun la voz elegida.
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if ($ollama -and -not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

$puerto = 8200
$linea = Get-Content ".env" | Where-Object { $_ -match '^\s*PORT\s*=\s*(\d+)' } | Select-Object -First 1
if ($linea -and $linea -match '(\d+)') { $puerto = [int]$matches[1] }
$url = "http://127.0.0.1:$puerto"

function Test-Vivo {
    try { Invoke-WebRequest "$url/api/config" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

# ¿El servidor que ya está en marcha es anterior al código o a los ajustes actuales? (se cambió .env, se
# actualizó el companion...). Entonces hay que reiniciarlo para que los cambios tengan efecto.
function Test-Anticuado {
    try {
        $config = Invoke-RestMethod "$url/api/config" -TimeoutSec 3
        if (-not $config.started) { return $true }          # servidor de una versión que aún no lo decía
        $archivos = @(Get-ChildItem "$raiz\companion\*.py") + @(Get-Item "$raiz\.env") + @(Get-ChildItem "$raiz\personas\*.json")
        $nuevo = ($archivos | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
        return ([DateTimeOffset]::new($nuevo).ToUnixTimeSeconds() -gt [int64]$config.started)
    } catch { return $false }                               # ante la duda, se deja como está
}

if ((Test-Vivo) -and (Test-Anticuado)) {
    Write-Host "Reiniciando el companion para aplicar los cambios..."
    & "$raiz\detener.ps1" | Out-Null
    foreach ($i in 1..20) { if (-not (Test-Vivo)) { break }; Start-Sleep -Milliseconds 250 }
}

if (-not (Test-Vivo)) {
    New-Item -ItemType Directory -Force "data" | Out-Null
    Start-Process -FilePath "$raiz\.venv\Scripts\python.exe" -ArgumentList "-m", "companion" -WorkingDirectory $raiz `
        -WindowStyle Hidden -RedirectStandardOutput "$raiz\data\companion.out.log" -RedirectStandardError "$raiz\data\companion.log"
    $listo = $false
    foreach ($i in 1..40) { Start-Sleep -Milliseconds 500; if (Test-Vivo) { $listo = $true; break } }
    if (-not $listo) {
        Write-Host "El companion no arrancó. Últimas líneas del registro:" -ForegroundColor Red
        Get-Content "data\companion.log" -Tail 15
        Read-Host "Pulsa Enter para salir"
        exit 1
    }
}


if ($SinVentana) { Write-Host "Companion en $url"; exit 0 }

# App de escritorio (Electron): ventana propia y modo flotante sobre las demás ventanas.
# Al cerrarla se apaga también el servidor, para liberar la GPU.
$electron = Join-Path $raiz "desktop\electron\electron.exe"
if (Test-Path $electron) {
    $env:COMPANION_URL = $url
    $env:COMPANION_STOP_ON_EXIT = "1"
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Start-Process -FilePath $electron -ArgumentList "`"$raiz\desktop`"" -WorkingDirectory $raiz
    exit 0
}

# Sin la app de escritorio (scripts\instalar_escritorio.ps1): ventana de Chrome o Edge en modo aplicación.
# Ahí no hay modo flotante y el servidor sigue encendido hasta ejecutar detener.ps1.
$navegador = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
               "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
               "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
               "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($navegador) { Start-Process $navegador -ArgumentList "--app=$url", "--window-size=520,880" }
else { Start-Process $url }
