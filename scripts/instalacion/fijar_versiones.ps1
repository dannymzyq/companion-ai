# Rehace requirements.lock y voz\requirements.lock con las versiones EXACTAS instaladas en .venv y voz\.venv.
# Úsalo después de actualizar dependencias y probar que todo funciona: el instalador instala lo que diga el lock.
#   powershell -ExecutionPolicy Bypass -File scripts\instalacion\fijar_versiones.ps1
$ErrorActionPreference = "Stop"
$raiz = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
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
    @("# Versiones exactas de voz\.venv (scripts\instalacion\fijar_versiones.ps1). torch y torchaudio los instala instalar.ps1.") + $lineas |
        Set-Content -Encoding ascii "voz\requirements.lock"
}
# macOS con Apple Silicon (14 o posterior): las mismas versiones, resueltas para ese sistema (instalar.sh las usa).
$env:MACOSX_DEPLOYMENT_TARGET = "14.0"
$req = Join-Path $env:TEMP "companion_req_mac.txt"; $con = Join-Path $env:TEMP "companion_con_mac.txt"
$mac = Join-Path $env:TEMP "companion_mac.lock"
Get-Content requirements.txt | Where-Object { $_ -notmatch '^nvidia' } | Set-Content -Encoding ascii $req
Get-Content requirements.lock | Where-Object { $_ -notmatch '^nvidia' } | Set-Content -Encoding ascii $con
& $uv pip compile $req -c $con --python-platform aarch64-apple-darwin --python-version 3.13 --no-header --no-annotate -o $mac
if ($LASTEXITCODE -ne 0) { throw "No pude rehacer requirements-mac.lock" }
@("# Versiones exactas para macOS con Apple Silicon (14 o posterior), sacadas de requirements.lock (scripts\instalacion\fijar_versiones.ps1).") +
    (Get-Content $mac) | Set-Content -Encoding ascii "requirements-mac.lock"
$torch = (Get-Content instalar.ps1 | Select-String -Pattern 'torch==[\d.]+ torchaudio==[\d.]+' | Select-Object -First 1).Matches[0].Value -split ' '
(Get-Content voz\requirements.txt | Where-Object { $_ -notmatch '^#' }) + $torch | Set-Content -Encoding ascii $req
Get-Content voz\requirements.lock | Where-Object { $_ -notmatch '^#' } | Set-Content -Encoding ascii $con
& $uv pip compile $req -c $con --python-platform aarch64-apple-darwin --python-version 3.13 --no-header --no-annotate -o $mac
if ($LASTEXITCODE -ne 0) { throw "No pude rehacer voz\requirements-mac.lock" }
@("# Versiones exactas de la voz completa en macOS con Apple Silicon, torch incluido (scripts\instalacion\fijar_versiones.ps1).") +
    (Get-Content $mac) | Set-Content -Encoding ascii "voz\requirements-mac.lock"
Remove-Item $tmp, $req, $con, $mac -ErrorAction SilentlyContinue
Write-Host "Listo: requirements.lock, voz\requirements.lock y sus versiones para macOS."
