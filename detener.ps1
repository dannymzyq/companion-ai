# Apaga todo lo que arrancó el companion. Lo ejecuta la app al cerrarse (y se puede ejecutar a mano):
#   1. le pide al servidor un apagado ordenado (/api/shutdown: para la voz completa y saca el modelo local)
#   2. cierra lo que quede con su árbol de procesos: el servidor (el python.exe del entorno es un lanzador con
#      otro proceso debajo) y la voz completa (puerto 8210), aunque esta siga cargando y aún no escuche
#   3. saca de la memoria los modelos locales del companion y cierra Ollama si lo abrió iniciar.ps1
# Solo toca procesos de esta carpeta (y el Ollama que anotó iniciar.ps1 en data\ollama.pid).
# Pruebas: -PuertoPrueba 8201 -SoloServidor apaga solo el servidor de prueba (ni la voz del 8210 ni Ollama).
# (PowerShell no distingue mayúsculas: el parámetro y el puerto que se usa NO pueden llamarse igual. Con
# $Puerto/$puerto, «-Puerto 8201» se pisaba con el 8200 de .env y apagó el companion real, 15 nov 2026.)
param([int]$PuertoPrueba = 0, [switch]$SoloServidor)
$raiz = $PSScriptRoot
$servidorPuerto = 8200
if ($PuertoPrueba) {
    if ($PuertoPrueba -eq 8200) { Write-Host "-PuertoPrueba es para el servidor de prueba, nunca el 8200."; exit 1 }
    $servidorPuerto = $PuertoPrueba
} elseif (Test-Path "$raiz\.env") {
    $linea = Get-Content "$raiz\.env" | Where-Object { $_ -match '^\s*PORT\s*=\s*(\d+)' } | Select-Object -First 1
    if ($linea -and $linea -match '(\d+)') { $servidorPuerto = [int]$matches[1] }
}
function Escucha($p) { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique }
function Info($id) { Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue }
function Es-Nuestro($proc) { $proc -and $proc.ExecutablePath -and $proc.ExecutablePath.StartsWith($raiz, [StringComparison]::OrdinalIgnoreCase) }
# El proceso más alto del árbol que sigue siendo de esta carpeta (el lanzador del entorno), para cerrarlo todo.
function Raiz-Arbol($id) {
    $p = Info $id
    while ($p) {
        $padre = Info $p.ParentProcessId
        if (-not (Es-Nuestro $padre) -or $padre.Name -notmatch '^python' -or $padre.CommandLine -notmatch '-m companion|servidor:app') { break }
        $p = $padre
    }
    return $p
}
function Cerrar-Arbol($id) {
    $top = Raiz-Arbol $id
    if (Es-Nuestro $top) { & taskkill.exe /F /T /PID $top.ProcessId 2>&1 | Out-Null; return $true }
    return $false
}

# 1. apagado ordenado
$estaba = [bool](Escucha $servidorPuerto)
if ($estaba) {
    try {
        Invoke-RestMethod -Method Post "http://127.0.0.1:$servidorPuerto/api/shutdown" -TimeoutSec 4 | Out-Null
        foreach ($i in 1..40) { if (-not (Escucha $servidorPuerto)) { break }; Start-Sleep -Milliseconds 250 }
    } catch { }
}

# 2. lo que quede: el servidor, sus hijos y la voz completa (por puerto y, si aún carga, por su orden)
foreach ($id in @(Escucha $servidorPuerto)) {
    # Si el entorno usa un Python de fuera de esta carpeta, se cierra al menos el que escucha (como antes).
    if ($id -and -not (Cerrar-Arbol $id)) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
}
if ($SoloServidor) { if ($estaba) { Write-Host "Companion detenido." }; exit 0 }
foreach ($id in @(Escucha 8210)) { if ($id) { [void](Cerrar-Arbol $id) } }
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { (Es-Nuestro $_) -and $_.CommandLine -match 'servidor:app' -and $_.CommandLine -match '--port 8210' } |
    ForEach-Object { [void](Cerrar-Arbol $_.ProcessId) }
if ($estaba) { Write-Host "Companion detenido." } else { Write-Host "El companion no estaba en marcha." }

# 3. Ollama: los modelos del companion fuera de la memoria de vídeo y, si lo abrió el companion, Ollama también.
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if ($ollama -and (Escucha 11434)) {
    $modelos = @('gemma4:12b', 'gemma4:e4b-it-qat', 'gemma4:e2b-it-qat', 'qwen3:1.7b', 'gemma3:1b-it-qat')
    if (Test-Path "$raiz\data\settings.json") {
        try { $m = (Get-Content "$raiz\data\settings.json" -Raw -Encoding UTF8 | ConvertFrom-Json).local_model; if ($m) { $modelos += $m } } catch { }
    }
    if (Test-Path "$raiz\.env") {
        Get-Content "$raiz\.env" | Where-Object { $_ -match '^\s*OLLAMA_(MODEL|FALLBACK)\s*=\s*(.+)$' } |
            ForEach-Object { $modelos += ($_ -replace '^[^=]*=', '').Split(',') | ForEach-Object { $_.Trim() } }
    }
    $cargados = (& $ollama ps 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
    $modelos | Select-Object -Unique | Where-Object { $_ -and ($cargados -contains $_) } | ForEach-Object { & $ollama stop $_ 2>$null | Out-Null }
}
$pidOllama = "$raiz\data\ollama.pid"
if (Test-Path $pidOllama) {
    $id = [int]((Get-Content $pidOllama -Raw).Trim())
    $p = Info $id
    if ($p -and $p.Name -like 'ollama*') { & taskkill.exe /F /T /PID $id 2>&1 | Out-Null; Write-Host "Ollama cerrado (lo había abierto el companion)." }
    Remove-Item $pidOllama -ErrorAction SilentlyContinue
}
