# Instalación desde el paquete de un Release (lo lanza la ventana de instalar cuando se abre desde el .exe):
# primero copia el programa a la carpeta elegida, solo lo que cambió (copiar_programa.ps1), y después ejecuta el
# instalar.ps1 de esa carpeta, que completa o pone al día lo demás (Python, librerías, modelos) y salta lo que ya está.
#   instalar_paquete.ps1 -Origen <paquete> -Destino <carpeta> [argumentos de instalar.ps1]
param(
    [Parameter(Mandatory = $true)][string]$Origen,
    [Parameter(Mandatory = $true)][string]$Destino,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Resto
)
$ErrorActionPreference = "Stop"
. (Join-Path $Origen "scripts\instalacion\comun_instalacion.ps1")
trap { Marca error $_.Exception.Message; break }

Marca paso programa
Write-Host "`n== El programa" -ForegroundColor Cyan
& (Join-Path $Origen "scripts\instalacion\copiar_programa.ps1") -Origen $Origen -Destino $Destino

# El resto, con el instalar.ps1 que acaba de copiarse (el de esta versión). Escribe en la misma salida, con sus
# propias marcas de progreso.
$lista = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Destino "instalar.ps1")) + @($Resto | Where-Object { $_ })
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" @lista
exit $LASTEXITCODE
