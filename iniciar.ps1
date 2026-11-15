# Arranca el companion y abre su ventana.   Doble clic en Companion.bat, o:
#   powershell -ExecutionPolicy Bypass -File iniciar.ps1
param([switch]$SinVentana)      # solo arranca el servidor, sin abrir la ventana
$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
Set-Location $raiz

if (-not (Test-Path ".venv\Scripts\python.exe") -or -not (Test-Path "web\vendor\three\build\three.module.min.js")) {
    # Falta instalar: se abre la ventana de instalación (con su progreso) y, al terminar, ella abre el companion.
    Start-Process powershell.exe -ArgumentList "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", "`"$raiz\scripts\ventana_instalar.ps1`"" -WindowStyle Hidden
    exit 0
}

# Servicios: el cerebro local (Ollama) se arranca aqui si no esta abierto; la voz completa (voz\servidor.py,
# puerto 8210) la arranca y la para el propio companion segun la voz elegida.
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if ($ollama -and -not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
. "$raiz\scripts\comun_instalacion.ps1"

# Dos arranques a la vez (doble clic dos veces, o el instalador y el acceso directo) lanzaban dos servidores y el
# segundo fallaba con «solo se permite un uso de cada dirección de socket». Uno espera a que termine el otro, y
# solo después lee el puerto (el primero puede haberlo cambiado).
$candado = New-Object System.Threading.Mutex($false, "Local\CompanionPC-iniciar")
try { [void]$candado.WaitOne([TimeSpan]::FromMinutes(3)) } catch [System.Threading.AbandonedMutexException] { }

$puerto = Leer-Puerto
$url = "http://127.0.0.1:$puerto"

function Test-Vivo {
    try { Invoke-WebRequest "$url/api/config" -UseBasicParsing -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

if (-not (Test-Vivo)) {
    $dueno = Dueno-Puerto $puerto
    if ($dueno -and $dueno.Companion) {
        # Un companion de esta carpeta que todavía está arrancando (o colgado): se le da tiempo y, si no responde,
        # se reinicia.
        foreach ($i in 1..60) { if (Test-Vivo) { break }; Start-Sleep -Seconds 1 }
        if (-not (Test-Vivo)) { Stop-Process -Id $dueno.Id -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1 }
    } elseif ($dueno) {
        # Otro programa usa el puerto: se busca uno libre y se guarda en .env para las próximas veces.
        $libre = Puerto-Libre
        if (-not $libre) {
            Add-Type -AssemblyName PresentationFramework
            [Windows.MessageBox]::Show("El puerto $puerto lo usa otro programa ($($dueno.Nombre)) y no encontré otro libre.", "Companion", "OK", "Error") | Out-Null
            exit 1
        }
        Write-Host "El puerto $puerto lo usa otro programa ($($dueno.Nombre)): el companion pasa al $libre."
        $puerto = $libre
        $url = "http://127.0.0.1:$puerto"
        Guardar-Puerto $puerto
    }
}

# ¿El servidor que ya está en marcha es anterior al código o a los ajustes actuales? (se cambió .env, se
# actualizó el companion...). Entonces hay que reiniciarlo para que los cambios tengan efecto.
function Test-Anticuado {
    try {
        $config = Invoke-RestMethod "$url/api/config" -TimeoutSec 3
        if (-not $config.started) { return $true }          # servidor de una versión que aún no lo decía
        $archivos = @(Get-ChildItem "$raiz\companion\*.py") + @(Get-ChildItem "$raiz\voz\*.py") + @(Get-Item "$raiz\.env") + @(Get-ChildItem "$raiz\personas\*.json")
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
    # Se guardan los registros de las tres veces anteriores (companion.1.log es la última): si se cerró por un
    # error y se vuelve a abrir, el motivo no se pierde.
    foreach ($nombre in "companion", "companion.out") {
        $base = Join-Path $raiz "data\$nombre"
        foreach ($n in 3, 2, 1) {
            $antes = if ($n -eq 1) { "$base.log" } else { "$base.$($n - 1).log" }
            if (Test-Path $antes) { Move-Item -Force $antes "$base.$n.log" -ErrorAction SilentlyContinue }
        }
    }
    $env:PORT = "$puerto"
    $servidor = Start-Process -FilePath "$raiz\.venv\Scripts\python.exe" -ArgumentList "-m", "companion" -WorkingDirectory $raiz `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput "$raiz\data\companion.out.log" -RedirectStandardError "$raiz\data\companion.log"
    # La primera vez, en una PC más lenta, cargar todo puede pasar de 20 s: se espera hasta 2 minutos, salvo que
    # el servidor se cierre antes (entonces ya no va a responder).
    $listo = $false
    foreach ($i in 1..240) {
        Start-Sleep -Milliseconds 500
        if (Test-Vivo) { $listo = $true; break }
        if ($servidor.HasExited) { break }
    }
    if (-not $listo) {
        # Con el acceso directo no hay terminal: el aviso va en una ventana.
        $cola = (Get-Content "data\companion.log" -Tail 12 -ErrorAction SilentlyContinue) -join "`n"
        $pista = if ($cola -match '10048|address already in use') { "El puerto $puerto está ocupado por otro programa. Ciérralo, o pon otro puerto en .env (PORT=8202).`n`n" } else { "" }
        Add-Type -AssemblyName PresentationFramework
        [Windows.MessageBox]::Show("El companion no arrancó. $pista" + "Últimas líneas del registro (data\companion.log):`n`n$cola", "Companion", "OK", "Error") | Out-Null
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
