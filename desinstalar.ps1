# Desinstalador del companion. Lo normal es Desinstalar.bat (o Configuración › Aplicaciones), que abre una
# ventana para elegir qué quitar. Desde una terminal:
#   powershell -ExecutionPolicy Bypass -File desinstalar.ps1 [-Programa] [-Oido] [-VozLigera] [-VozCompleta]
#              [-Accesos] [-ModelosOllama] [-Datos] [-Carpeta]
#   -Programa       Python propio, librerías, app de escritorio y librerías 3D (se vuelven a bajar al instalar)
#   -Oido           models\whisper              -VozLigera  models\piper
#   -VozCompleta    voz\.venv y voz\modelos      -Accesos    escritorio, menú Inicio y Aplicaciones instaladas
#   -ModelosOllama  los modelos locales del catálogo del companion (Ollama, el programa, se queda)
#   -Datos          data (conversación, recuerdos, ajustes, voces propias), .env y models\custom: a la Papelera
#   -Carpeta        la carpeta entera, unos segundos después de terminar (no en una copia con git)
param([switch]$Programa, [switch]$Oido, [switch]$VozLigera, [switch]$VozCompleta, [switch]$Accesos,
      [switch]$ModelosOllama, [switch]$Datos, [switch]$Carpeta)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$raiz = $PSScriptRoot
. "$raiz\scripts\comun_instalacion.ps1"
trap { Marca error $_.Exception.Message; break }
# COMPANION_PRUEBA (solo las pruebas, en una copia): no se para el companion real ni se toca Ollama, el registro
# ni la Papelera; los accesos directos se buscan en COMPANION_PRUEBA_ACCESOS.
$prueba = $env:COMPANION_PRUEBA -eq "1"
Set-Location $env:TEMP                    # para poder borrar la carpeta del companion sin tenerla abierta
[Environment]::CurrentDirectory = $env:TEMP

function Quitar([string[]]$rutas) {
    foreach ($r in $rutas) {
        $p = Join-Path $raiz $r
        if (-not (Test-Path $p)) { continue }
        Write-Host "Borrando $r"
        if ((Get-Item $p) -is [IO.DirectoryInfo]) { cmd /c rmdir /s /q "`"$p`"" 2>$null }   # mucho más rápido con miles de archivos
        if (Test-Path $p) { Remove-Item $p -Recurse -Force }
    }
}

# ---------------------------------------------------------------- antes: cerrar lo que tenga archivos abiertos
Marca paso detener
if (-not $prueba) {
    & "$raiz\detener.ps1" 2>$null | Out-Null
}
# La app de escritorio y los Python de esta carpeta (si quedara alguno abierto, no se podría borrar).
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith("$raiz\", [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Write-Host "Cerrando $($_.ProcessName) ($($_.Id))"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

if ($ModelosOllama) {
    Marca paso ollama
    $catalogo = @('gemma4:12b', 'gemma4:e4b-it-qat', 'gemma4:e2b-it-qat', 'qwen3:1.7b', 'gemma3:1b-it-qat')
    if (Test-Path "$raiz\data\settings.json") {
        try { $s = Get-Content "$raiz\data\settings.json" -Raw -Encoding UTF8 | ConvertFrom-Json; if ($s.local_model) { $catalogo += $s.local_model } } catch { }
    }
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    if ($ollama) {
        $tiene = @(& $ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
        foreach ($m in ($catalogo | Select-Object -Unique)) {
            if ($tiene -notcontains $m) { continue }
            if ($prueba) { Write-Host "(prueba) quitaría el modelo $m"; continue }
            Write-Host "Quitando el modelo local $m"
            & $ollama rm $m 2>$null | Out-Null
        }
    } else { Write-Host "Ollama no está instalado: no hay modelos que quitar." }
} else { Marca omitido ollama }

if ($Accesos) {
    Marca paso accesos
    $base = $env:COMPANION_PRUEBA_ACCESOS
    $escritorio = if ($base) { Join-Path $base "Escritorio" } else { [Environment]::GetFolderPath("Desktop") }
    $menu = if ($base) { Join-Path $base "Menu" } else { Join-Path ([Environment]::GetFolderPath("Programs")) "Companion" }
    Remove-Item (Join-Path $escritorio "Companion.lnk") -Force -ErrorAction SilentlyContinue
    Remove-Item $menu -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $base -and -not $prueba) {
        $clave = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CompanionPC"
        $actual = Get-ItemProperty $clave -ErrorAction SilentlyContinue
        if ($actual -and $actual.InstallLocation -eq $raiz) { Remove-Item $clave -Recurse -Force }   # solo si es de esta carpeta
    }
    Write-Host "Accesos directos quitados."
} else { Marca omitido accesos }

if ($Programa) { Marca paso programa; Quitar "runtime", ".venv", "desktop\electron", "web\vendor"
    Get-ChildItem $raiz -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notlike "*\.venv\*" } | ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue } }
else { Marca omitido programa }
if ($Oido) { Marca paso oido; Quitar "models\whisper" } else { Marca omitido oido }
if ($VozLigera) { Marca paso ligera; Quitar "models\piper" } else { Marca omitido ligera }
if ($VozCompleta) { Marca paso completa; Quitar "voz\.venv", "voz\modelos" } else { Marca omitido completa }

if ($Datos) {
    Marca paso datos
    Add-Type -AssemblyName Microsoft.VisualBasic
    foreach ($r in "data", ".env", "models\custom") {
        $p = Join-Path $raiz $r
        if (-not (Test-Path $p)) { continue }
        if ($prueba) { Remove-Item $p -Recurse -Force; Write-Host "Borrado $r"; continue }
        # A la Papelera: si fue sin querer, se puede recuperar
        if ((Get-Item $p) -is [IO.DirectoryInfo]) {
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, "OnlyErrorDialogs", "SendToRecycleBin")
        } else {
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, "OnlyErrorDialogs", "SendToRecycleBin")
        }
        Write-Host "$r enviado a la Papelera"
    }
} else { Marca omitido datos }

if ($Carpeta) {
    Marca paso carpeta
    if (Test-Path "$raiz\.git") { throw "Es una copia con git: no la borro entera (bórrala a mano si quieres)." }
    # Cuando esta ventana ya se haya cerrado: nada puede tener abierta la carpeta mientras se borra.
    # Se reintenta cada 2 s durante un minuto, por si la ventana sigue abierta un rato.
    $orden = "for /l %i in (1,1,30) do (timeout /t 2 /nobreak >nul & rmdir /s /q `"$raiz`" 2>nul & if not exist `"$raiz`" exit)"
    Start-Process cmd.exe -ArgumentList "/c", $orden -WindowStyle Hidden -WorkingDirectory $env:TEMP
    Write-Host "La carpeta se borrará en unos segundos."
} else { Marca omitido carpeta }
Marca fin
Write-Host "Desinstalación terminada."
