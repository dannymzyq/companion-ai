# Crea el instalador de un Release: dist\Companion-Setup-<versión>.exe. Lo usa GitHub Actions al publicar una
# etiqueta vX.Y.Z (.github\workflows\release.yml), y se puede ejecutar aquí para probarlo.
#
# El paquete es lo que está en git (git ls-files; también lo nuevo aún sin confirmar que no esté en .gitignore), más manifest.json: la huella SHA-256 y el tamaño
# de cada archivo, con la que el instalador copia solo lo que cambió respecto a la versión instalada. El .exe es
# un lanzador pequeño (instalador\Lanzador.cs, compilado con el csc.exe de .NET Framework que trae Windows) que
# lleva el paquete dentro.
#   powershell -ExecutionPolicy Bypass -File scripts\instalacion\crear_instalador.ps1 [-Version 0.3.0] [-Salida dist]
param(
    [string]$Version = "",              # por defecto, la del archivo VERSION
    [string]$Salida = "dist"
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $raiz
if (-not $Version) { $Version = (Get-Content "$raiz\VERSION" -Raw).Trim() }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Versión no válida: $Version (se espera X.Y.Z)" }
$salida = if ([IO.Path]::IsPathRooted($Salida)) { $Salida } else { Join-Path $raiz $Salida }
New-Item -ItemType Directory -Force $salida | Out-Null

# Lo que va en el paquete: lo que está en git, menos lo que solo sirve al repositorio (y las otras ediciones:
# movil/, rust-live/ y la web de presentación docs/).
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$lista = @(git -c core.quotepath=off ls-files --cached --others --exclude-standard) | Where-Object {
    $_ -and $_ -notlike ".github/*" -and $_ -notlike "movil/*" -and $_ -notlike "rust-live/*" -and $_ -notlike "docs/*" -and $_ -notin ".gitignore", ".gitattributes"
}
if ($LASTEXITCODE -ne 0 -or $lista.Count -lt 20) { throw "git ls-files no devolvió la lista del proyecto." }

$tmp = Join-Path $env:TEMP ("companion_paquete_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$carpeta = Join-Path $tmp "paquete"
New-Item -ItemType Directory -Force $carpeta | Out-Null
try {
    $archivos = New-Object System.Collections.Generic.List[object]
    foreach ($rel in $lista) {
        $src = Join-Path $raiz $rel
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }      # borrado y aún sin confirmar
        $dst = Join-Path $carpeta $rel
        New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst
        $archivos.Add([ordered]@{ p = $rel; h = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash; s = (Get-Item -LiteralPath $dst).Length })
    }
    Set-Content -LiteralPath (Join-Path $carpeta "VERSION") -Value $Version -NoNewline -Encoding ASCII
    # VERSION se reescribe con la versión pedida: su huella, la del archivo final.
    $v = $archivos | Where-Object { $_.p -eq "VERSION" }
    if ($v) { $v.h = (Get-FileHash -LiteralPath (Join-Path $carpeta "VERSION") -Algorithm SHA256).Hash; $v.s = (Get-Item (Join-Path $carpeta "VERSION")).Length }
    $manifiesto = [ordered]@{ version = $Version; files = $archivos.ToArray() }
    [IO.File]::WriteAllText((Join-Path $carpeta "manifest.json"), ($manifiesto | ConvertTo-Json -Depth 4 -Compress),
                            (New-Object Text.UTF8Encoding $false))

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = Join-Path $tmp "paquete.zip"
    [IO.Compression.ZipFile]::CreateFromDirectory($carpeta, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)

    $csc = Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) "csc.exe"
    if (-not (Test-Path $csc)) { $csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" }
    $exe = Join-Path $salida "Companion-Setup-$Version.exe"
    # Datos de versión y manifiesto (asInvoker, Windows 10/11): un .exe sin ellos parece más un virus para el
    # antivirus (la 0.8.6 salió como Trojan:Win32/Wacatac.B!ml al descargarla, 18 nov 2026).
    $versionCs = Join-Path $tmp "Version.cs"
    [IO.File]::WriteAllText($versionCs, "using System.Reflection;`n[assembly: AssemblyVersion(""$Version.0"")]`n" +
        "[assembly: AssemblyFileVersion(""$Version.0"")]`n[assembly: AssemblyInformationalVersion(""$Version"")]`n",
        (New-Object Text.UTF8Encoding $false))
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ "/out:$exe" "/win32icon:$raiz\desktop\icono.ico" `
        "/win32manifest:$raiz\instalador\app.manifest" `
        "/resource:$zip,paquete.zip" /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
        /r:System.Windows.Forms.dll "$raiz\instalador\Lanzador.cs" $versionCs
    if ($LASTEXITCODE -ne 0) { throw "csc no pudo compilar el instalador." }
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "Instalador listo: $exe ($mb MB, $($archivos.Count) archivos, versión $Version)"
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
