# Apaga el servidor del companion (la ventana se cierra a mano).
$puerto = 8200
if (Test-Path "$PSScriptRoot\.env") {
    $linea = Get-Content "$PSScriptRoot\.env" | Where-Object { $_ -match '^\s*PORT\s*=\s*(\d+)' } | Select-Object -First 1
    if ($linea -and $linea -match '(\d+)') { $puerto = [int]$matches[1] }
}
# y el servidor de la voz completa (puerto 8210), por si el companion no pudo cerrarlo
Get-NetTCPConnection -LocalPort 8210 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { $p = Get-Process -Id $_ -ErrorAction SilentlyContinue; if ($p -and $p.Path -like "$PSScriptRoot\*") { Stop-Process -Id $_ -Force } }
$procesos = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($procesos) { $procesos | ForEach-Object { Stop-Process -Id $_ -Force }; Write-Host "Companion detenido." }
else { Write-Host "El companion no estaba en marcha." }

# Libera la memoria de vídeo de los modelos locales del companion (Ollama los deja cargados unos minutos).
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $modelos = @('gemma4:e4b-it-qat', 'gemma4:e2b-it-qat', 'qwen3:1.7b', 'gemma3:1b-it-qat')
    if (Test-Path "$PSScriptRoot\.env") {
        Get-Content "$PSScriptRoot\.env" | Where-Object { $_ -match '^\s*OLLAMA_(MODEL|FALLBACK)\s*=\s*(.+)$' } |
            ForEach-Object { $modelos += ($_ -replace '^[^=]*=', '').Split(',') | ForEach-Object { $_.Trim() } }
    }
    $cargados = (& ollama ps 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
    $modelos | Select-Object -Unique | Where-Object { $_ -and ($cargados -contains $_) } | ForEach-Object { & ollama stop $_ 2>$null | Out-Null }
}
