# Instalador del companion (Windows). Deja TODO dentro de esta carpeta: Python, entornos, modelos y la app.
#   powershell -ExecutionPolicy Bypass -File instalar.ps1 [-Voz auto|completa|ligera|ambas] [-SinOllama] [-SinModeloLocal]
#
# Que instala (lo que ya esta, se salta):
#   runtime\uv.exe, runtime\python   uv (gestor de Python) y Python 3.13 propios
#   .venv                            dependencias del companion (requirements.txt)
#   web\vendor, desktop\electron     librerias 3D de la interfaz y la app de escritorio
#   models\whisper                   el oido (Whisper large-v3-turbo, 1,5 GB)
#   models\piper                     la voz ligera (Piper, 380 MB, corre en el procesador)
#   voz\.venv, voz\modelos           la voz completa (PyTorch + F5-TTS, ~6 GB; necesita tarjeta NVIDIA)
#   Ollama + un modelo local         el cerebro local (lo unico que queda fuera de la carpeta: es un programa
#                                    del sistema; sus modelos viven en su propia carpeta)
param(
    [ValidateSet("auto", "completa", "ligera", "ambas")][string]$Voz = "auto",
    [switch]$SinOllama,            # no instala Ollama ni descarga un modelo local (solo cerebro en la nube)
    [switch]$SinModeloLocal,       # instala Ollama pero no descarga ningun modelo
    [switch]$NoRehacer             # conserva un .venv hecho con un Python de fuera (rehacerlo detiene el companion)
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$raiz = $PSScriptRoot
Set-Location $raiz
function Paso($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Comprobar($que) { if ($LASTEXITCODE -ne 0) { throw "Fallo: $que" } }

# ---------------------------------------------------------------- 1. uv y Python propios
Paso "Python propio (runtime\)"
$uv = Join-Path $raiz "runtime\uv.exe"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $raiz "runtime\python"
$env:UV_CACHE_DIR = Join-Path $raiz "runtime\cache"
if (-not (Test-Path $uv)) {
    New-Item -ItemType Directory -Force "runtime" | Out-Null
    $zip = Join-Path $raiz "runtime\uv.zip"
    Write-Host "Descargando uv (gestor de Python, ~20 MB) de github.com/astral-sh/uv..."
    Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $raiz "runtime") -Force
    Remove-Item $zip -Force
}
& $uv python install 3.13; Comprobar "instalar Python 3.13"

function Entorno($carpeta) {
    # Crea el entorno con el Python de runtime\. Si existe uno hecho con un Python de fuera, se rehace.
    $cfg = Join-Path $carpeta "pyvenv.cfg"
    # solo cuenta la linea «home»: la linea «command» lleva la ruta del proyecto aunque el Python sea de fuera
    $propio = (Test-Path $cfg) -and [bool](Get-Content $cfg | Where-Object { $_ -match '^\s*home\s*=' -and $_.ToLower().Contains($raiz.ToLower()) })
    if ((Test-Path "$carpeta\Scripts\python.exe") -and ($propio -or $NoRehacer)) { return }
    if (Test-Path $carpeta) {
        Write-Host "Rehaciendo $carpeta con el Python del proyecto..."
        # El companion en marcha tiene abiertos los archivos del entorno. En otro proceso: lo que «ollama stop»
        # escribe por su salida de error no debe cortar el instalador.
        Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$raiz\detener.ps1`"" -WindowStyle Hidden -Wait
        Start-Sleep -Seconds 1
        Remove-Item $carpeta -Recurse -Force
    }
    & $uv venv --python 3.13 $carpeta; Comprobar "crear $carpeta"
}

# ---------------------------------------------------------------- 2. el companion
Paso "Entorno del companion (.venv)"
Entorno (Join-Path $raiz ".venv")
$py = Join-Path $raiz ".venv\Scripts\python.exe"
& $uv pip install --python $py -r requirements.txt; Comprobar "dependencias del companion"

Paso "Interfaz y app de escritorio"
& "$raiz\scripts\setup.ps1" -SoloWeb

# ---------------------------------------------------------------- 3. modelos segun la tarjeta
Paso "Recursos segun tu PC"
$rec = (& $py scripts\preparar_recursos.py --recomendar) -split '\s+'
$vozRec, $modeloRec, $gb = $rec[0], $rec[1], $rec[2]
if ($gb -eq "0.0" -or $gb -eq "0") { Write-Host "Sin tarjeta NVIDIA: voz ligera y el modelo local mas pequeno." }
else { Write-Host "Tarjeta de $gb GB -> voz recomendada: $vozRec, modelo local recomendado: $modeloRec" }
if ($Voz -eq "auto") { $Voz = if ($vozRec -eq "completa") { "ambas" } else { "ligera" } }

& $py scripts\preparar_recursos.py --oido; Comprobar "descargar el oido"
if ($Voz -in "ligera", "ambas") { & $py scripts\preparar_recursos.py --ligera; Comprobar "descargar la voz ligera" }

if ($Voz -in "completa", "ambas") {
    Paso "Voz completa (voz\): PyTorch + F5-TTS, varios GB"
    Entorno (Join-Path $raiz "voz\.venv")
    $pyVoz = Join-Path $raiz "voz\.venv\Scripts\python.exe"
    & $uv pip install --python $pyVoz torch==2.12.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130; Comprobar "PyTorch"
    & $uv pip install --python $pyVoz -r voz\requirements.txt; Comprobar "F5-TTS"
    & $py scripts\preparar_recursos.py --completa; Comprobar "descargar el modelo de la voz completa"
}

# ---------------------------------------------------------------- 4. cerebro local (Ollama)
if (-not $SinOllama) {
    Paso "Cerebro local (Ollama)"
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"; if (-not (Test-Path $ollama)) { $ollama = $null } }
    if (-not $ollama) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host "Instalando Ollama con winget..."
            winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
            $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        }
        if (-not $ollama -or -not (Test-Path $ollama)) { Write-Warning "No pude instalar Ollama. Instalalo desde https://ollama.com/download y vuelve a ejecutar instalar.ps1 (o usa solo el cerebro en la nube)."; $ollama = $null }
    }
    if ($ollama -and -not $SinModeloLocal) {
        try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null }
        catch { Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep -Seconds 4 }
        $tiene = (& $ollama list 2>$null) -join "`n"
        if ($tiene -match [regex]::Escape($modeloRec)) { Write-Host "El modelo $modeloRec ya esta descargado." }
        else { Write-Host "Descargando el modelo local $modeloRec..."; & $ollama pull $modeloRec }
    }
}

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
New-Item -ItemType Directory -Force "data" | Out-Null
Paso "Listo"
Write-Host "Abre el companion con Companion.bat (o:  powershell -ExecutionPolicy Bypass -File iniciar.ps1)."
Write-Host "La primera vez te pedira tus datos, el cerebro (clave de API o modelo local), el personaje y la voz."
