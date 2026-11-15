# Copia el programa de un paquete de instalación (el .exe de un Release) a la carpeta donde se instala, solo con
# lo que cambió: cada archivo del paquete viene en manifest.json con su huella SHA-256. Se copian los nuevos o
# distintos y se borran los que la versión anterior instaló y la nueva ya no trae. Lo que no viene en ningún
# paquete (data\, .env, los entornos, los modelos descargados, los VRM propios) no se toca nunca.
#   copiar_programa.ps1 -Origen <paquete> -Destino <carpeta>
param(
    [Parameter(Mandatory = $true)][string]$Origen,
    [Parameter(Mandatory = $true)][string]$Destino
)
$ErrorActionPreference = "Stop"
. (Join-Path $Origen "scripts\comun_instalacion.ps1")

function Leer-Manifiesto([string]$ruta) {
    if (-not (Test-Path $ruta)) { return $null }
    return [IO.File]::ReadAllText($ruta) | ConvertFrom-Json
}

$nuevo = Leer-Manifiesto (Join-Path $Origen "manifest.json")
if (-not $nuevo) { throw "El paquete no trae manifest.json: no sé qué copiar." }
if (Test-Path (Join-Path $Destino ".git")) { throw "$Destino es una copia de desarrollo (git): actualízala con git pull, no con el instalador." }
New-Item -ItemType Directory -Force $Destino | Out-Null
$viejo = Leer-Manifiesto (Join-Path $Destino "manifest.json")
$antes = @{}
if ($viejo) { foreach ($f in $viejo.files) { $antes[$f.p] = $f.h } }
$desde = if ($viejo) { "la versión $($viejo.version)" } else { "nada instalado con el instalador" }
Write-Host "Programa: de $desde a la versión $($nuevo.version) en $Destino"

$total = @($nuevo.files).Count
$copiados = 0; $iguales = 0; $i = 0
$ahora = @{}
foreach ($f in $nuevo.files) {
    $i++
    $ahora[$f.p] = $true
    $dst = Join-Path $Destino $f.p
    $igual = $false
    if (Test-Path -LiteralPath $dst -PathType Leaf) {
        $largo = (Get-Item -LiteralPath $dst).Length
        if ($largo -eq [long]$f.s) {
            # Si la versión anterior instaló este mismo archivo y sigue del mismo tamaño, no hace falta leerlo entero.
            $igual = ($antes[$f.p] -eq $f.h) -or ((Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash -eq $f.h)
        }
    }
    if ($igual) { $iguales++ }
    else {
        New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
        Copy-Item -LiteralPath (Join-Path $Origen $f.p) -Destination $dst -Force
        $copiados++
    }
    if ($i % 25 -eq 0 -or $i -eq $total) { Marca progreso ([int](100 * $i / $total)) "Copiando el programa… $i de $total archivos" }
}

# Lo que instaló la versión anterior y la nueva ya no trae.
$quitados = 0
foreach ($p in $antes.Keys) {
    if ($ahora[$p]) { continue }
    $dst = Join-Path $Destino $p
    if (Test-Path -LiteralPath $dst -PathType Leaf) { Remove-Item -LiteralPath $dst -Force; $quitados++ }
}

# El manifiesto, lo último: si algo falla antes, la próxima vez se vuelve a comparar todo.
Copy-Item -LiteralPath (Join-Path $Origen "manifest.json") -Destination (Join-Path $Destino "manifest.json") -Force
Write-Host "Programa al día: $copiados archivos nuevos o cambiados, $quitados quitados, $iguales iguales."
