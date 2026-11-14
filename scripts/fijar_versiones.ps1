# Rehace requirements.lock y voz\requirements.lock con las versiones EXACTAS instaladas en .venv y voz\.venv.
# Úsalo después de actualizar dependencias y probar que todo funciona: el instalador instala lo que diga el lock.
#   powershell -ExecutionPolicy Bypass -File scripts\fijar_versiones.ps1
$ErrorActionPreference = "Stop"
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$uv = Join-Path $raiz "runtime\uv.exe"
$env:UV_CACHE_DIR = Join-Path $raiz "runtime\cache"
$tmp = Join-Path $env:TEMP "companion_freeze.txt"

# El companion: lo que pide requirements.txt (y sus dependencias), con la versión que hay en .venv.
& $uv pip freeze --python ".venv\Scripts\python.exe" | Set-Content -Encoding ascii $tmp
& $uv pip compile requirements.txt -c $tmp --python-platform x86_64-pc-windows-msvc --python-version 3.13 `
    --no-header --no-annotate -o requirements.lock
if ($LASTEXITCODE -ne 0) { throw "No pude rehacer requirements.lock" }

# La voz completa: todo voz\.venv menos PyTorch, que el instalador trae de su propio índice (CUDA 13).
if (Test-Path "voz\.venv\Scripts\python.exe") {
    $lineas = & $uv pip freeze --python "voz\.venv\Scripts\python.exe" | Where-Object { $_ -notmatch '^(torch|torchaudio)==' }
    @("# Versiones exactas de voz\.venv (scripts\fijar_versiones.ps1). torch y torchaudio los instala instalar.ps1.") + $lineas |
        Set-Content -Encoding ascii "voz\requirements.lock"
}
Remove-Item $tmp -ErrorAction SilentlyContinue
Write-Host "Listo: requirements.lock y voz\requirements.lock."
