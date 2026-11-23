# Prepara el companion: entorno Python, dependencias y librerías 3D de la interfaz.
#   powershell -ExecutionPolicy Bypass -File scripts\instalacion\setup.ps1
param(
    [string]$Python = "",          # ruta a un Python 3.11–3.13 (por defecto, el de ComfyUI)
    [switch]$SoloWeb               # solo descarga las librerías de la interfaz
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $raiz
. "$PSScriptRoot\comun_instalacion.ps1"

if (-not $SoloWeb -and -not $Python) { & "$raiz\instalar.ps1"; exit $LASTEXITCODE }   # el instalador completo trae su propio Python
if (-not $SoloWeb) {
    if (-not $Python) {
        $candidatos = @("C:\ComfyUI\ComfyUI\standalone-env\python.exe")
        $Python = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $Python) { throw "No encontré Python 3.13. Pasa -Python <ruta a python.exe>." }
    }
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Host "Creando entorno .venv con $Python"
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual" }
    }
    & .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    & .venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de dependencias" }
}

# Librerías de la interfaz (versiones fijas), servidas localmente desde web\vendor
$three = "0.180.0"
$vrm = "3.5.5"
$cdn = "https://cdn.jsdelivr.net/npm"
$archivos = @(
    @{ url = "$cdn/three@$three/build/three.module.min.js";                   dst = "web\vendor\three\build\three.module.min.js" },
    @{ url = "$cdn/three@$three/build/three.core.min.js";                     dst = "web\vendor\three\build\three.core.min.js" },
    @{ url = "$cdn/three@$three/examples/jsm/loaders/GLTFLoader.js";          dst = "web\vendor\three\examples\jsm\loaders\GLTFLoader.js" },
    @{ url = "$cdn/three@$three/examples/jsm/utils/BufferGeometryUtils.js";   dst = "web\vendor\three\examples\jsm\utils\BufferGeometryUtils.js" },
    @{ url = "$cdn/three@$three/examples/jsm/controls/OrbitControls.js";      dst = "web\vendor\three\examples\jsm\controls\OrbitControls.js" },
    @{ url = "$cdn/@pixiv/three-vrm@$vrm/lib/three-vrm.module.min.js";        dst = "web\vendor\three-vrm\three-vrm.module.min.js" }
)
# Si una versión nueva cambia las librerías, se vuelven a bajar (web\vendor\version guarda cuáles hay).
$marcaVendor = Join-Path $raiz "web\vendor\version"
$versionesVendor = "three $three · three-vrm $vrm"
$cambio = -not (Test-Path $marcaVendor) -or ((Get-Content $marcaVendor -Raw).Trim() -ne $versionesVendor)
foreach ($a in $archivos) {
    $dst = Join-Path $raiz $a.dst
    if ((Test-Path $dst) -and -not ($cambio -and (Test-Path $marcaVendor))) { continue }
    New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
    Write-Host "Descargando $($a.url)"
    Descargar $a.url $dst "Librerías 3D: $(Split-Path -Leaf $a.dst)"
}
Set-Content -LiteralPath $marcaVendor -Value $versionesVendor -Encoding UTF8

# App de escritorio (ventana propia y avatar flotante)
& "$PSScriptRoot\instalar_escritorio.ps1"

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Creado .env (pon tu GEMINI_API_KEY)" }
New-Item -ItemType Directory -Force "models", "data" | Out-Null
Write-Host "Listo."
