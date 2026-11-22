param(
    [switch]$Lite,
    [switch]$Flotante,
    [switch]$Navegador,
    [switch]$SinVentana,
    [switch]$Compilar,
    [int]$Puerto = 0
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$relDir = Join-Path $root 'rust-live\target\release'
$exe = Join-Path $relDir 'companion-live.exe'
$dllDst = Join-Path $relDir 'WebView2Loader.dll'

if ($Compilar -or -not (Test-Path $exe)) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $machPath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $env:PATH = "$userPath;$machPath;$env:USERPROFILE\.cargo\bin"
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        Write-Error 'No se encontró cargo (Rust). Instálalo desde https://rustup.rs y vuelve a intentarlo.'
        exit 1
    }
    Write-Host 'Compilando Companion Live (Rust) en modo release...'
    Push-Location (Join-Path $root 'rust-live')
    try {
        cargo build --release
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $dllDst)) {
    $dllSrc = Get-ChildItem -Path (Join-Path $relDir 'build') -Recurse -Filter 'WebView2Loader.dll' -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1
    if ($dllSrc) { Copy-Item $dllSrc.FullName $dllDst -Force }
}

$argsList = @('--root', $root)
if ($Lite)       { $argsList += '--lite' }
if ($Flotante)   { $argsList += '--float' }
if ($Navegador)  { $argsList += '--browser' }
if ($SinVentana) { $argsList += '--no-window' }
if ($Puerto -gt 0) { $argsList += @('--port', "$Puerto") }

& $exe @argsList