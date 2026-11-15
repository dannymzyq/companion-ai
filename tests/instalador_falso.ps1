# Instalador de mentira para probar la ventana (scripts\prueba_instalador.py): imprime las mismas marcas que
# instalar.ps1, con pausas cortas, sin descargar ni instalar nada. FALSO_FALLA=<paso> hace que falle ahí.
param([string]$Voz = "auto", [switch]$SinOllama, [switch]$AccesosDirectos)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\..\scripts\comun_instalacion.ps1"
trap { Marca error $_.Exception.Message; break }
$pausa = [int]($env:FALSO_PAUSA_MS | ForEach-Object { if ($_) { $_ } else { 120 } })
function Paso($id) {
    Marca paso $id
    Write-Host "== paso $id (acentos: ñandú, «comillas»)"
    if ($env:FALSO_FALLA -eq $id) { [Console]::Error.WriteLine("error: algo salió mal en $id"); throw "Falló: $id (simulado)" }
}
Paso python; Start-Sleep -Milliseconds $pausa
Paso companion
foreach ($i in 1..5) { Write-Host "Downloading paquete$i (12.3MiB)"; Start-Sleep -Milliseconds $pausa }
Paso interfaz
foreach ($p in 0, 25, 50, 75, 100) { Marca progreso $p "App de escritorio (Electron): $p %"; Start-Sleep -Milliseconds $pausa }
Paso recursos; Write-Host "Tarjeta de 16 GB -> voz recomendada: completa"
Paso oido
foreach ($p in 0, 30, 60, 90) { Marca progreso $p "Oído (Whisper): $p %"; Start-Sleep -Milliseconds $pausa }
Write-Host "barra`r 10%`r 50%`r 100%"
if ($Voz -in "ligera", "ambas", "auto") { Paso ligera; Start-Sleep -Milliseconds $pausa } else { Marca omitido ligera }
if ($Voz -ne "ligera") { Paso torch; Start-Sleep -Milliseconds ($pausa * 3); Paso f5; Start-Sleep -Milliseconds $pausa }
else { Marca omitido torch; Marca omitido f5 }
if (-not $SinOllama) { Paso ollama; foreach ($p in 10, 60, 100) { Marca progreso $p "Modelo local: $p %"; Start-Sleep -Milliseconds $pausa } }
else { Marca omitido ollama }
Paso final
Marca fin
Write-Host "Listo"
