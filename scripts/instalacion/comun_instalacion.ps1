# Piezas comunes del instalador y el desinstalador (se cargan con «. scripts\instalacion\comun_instalacion.ps1»).
#
# Con COMPANION_UI=1 (lo pone la ventana de instalación) se imprimen marcas que la ventana lee para enseñar el
# progreso en vivo:   ::paso::<id>   ::omitido::<id>   ::progreso::<0-100>::<texto>   ::error::<texto>   ::fin::
# En la terminal no se imprimen: ahí se ve la salida normal de siempre.

$script:ui = $env:COMPANION_UI -eq "1"
if ($script:ui) {
    # La ventana lee la salida como UTF-8 (si no, los acentos llegan rotos) y sin esperar a que se llene un búfer.
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding = [Console]::OutputEncoding
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUNBUFFERED = "1"
}

function Marca([string]$tipo, [string]$a = "", [string]$b = "") {
    if (-not $script:ui) { return }
    $linea = "::${tipo}::$a"
    if ($b) { $linea += "::$b" }
    [Console]::Out.WriteLine($linea)
    [Console]::Out.Flush()
}

function Tamano([double]$bytes) {
    if ($bytes -ge 1GB) { return ("{0:N1} GB" -f ($bytes / 1GB)) }
    return ("{0:N0} MB" -f ($bytes / 1MB))
}

function Descargar([string]$url, [string]$destino, [string]$texto) {
    # Descarga con progreso (Invoke-WebRequest no lo da sin su barra, que va muy lenta). Se escribe en .part y
    # solo al terminar pasa a su nombre: una descarga cortada no se toma por buena.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $parte = "$destino.part"
    $pedido = [Net.HttpWebRequest]::Create($url)
    $pedido.UserAgent = "companion-instalador"
    $pedido.Timeout = 30000
    $pedido.ReadWriteTimeout = 60000
    $respuesta = $pedido.GetResponse()
    try {
        $total = $respuesta.ContentLength
        $entrada = $respuesta.GetResponseStream()
        $salida = [IO.File]::Create($parte)
        try {
            $buf = New-Object byte[] 262144
            $hecho = 0
            $reloj = [Diagnostics.Stopwatch]::StartNew()
            while (($n = $entrada.Read($buf, 0, $buf.Length)) -gt 0) {
                $salida.Write($buf, 0, $n)
                $hecho += $n
                if ($reloj.ElapsedMilliseconds -ge 400 -and $total -gt 0) {
                    $reloj.Restart()
                    Marca progreso ([int](100 * $hecho / $total)) "${texto}: $(Tamano $hecho) de $(Tamano $total)"
                }
            }
        } finally { $salida.Close(); $entrada.Close() }
    } finally { $respuesta.Close() }
    Move-Item -Force $parte $destino
}

# ---------------------------------------------------------------- puerto del companion
# El companion escucha en PORT (de .env; 8200 si no está). Si otro programa ya usa ese puerto, se busca uno libre
# y se guarda en .env, donde lo leen el servidor, detener.ps1 y la ventana. Necesita $raiz.
function Leer-Puerto {
    $ruta = Join-Path $raiz ".env"
    if (Test-Path $ruta) {
        $l = [IO.File]::ReadAllLines($ruta) | Where-Object { $_ -match '^\s*PORT\s*=\s*(\d+)' } | Select-Object -First 1
        if ($l -and $l -match '(\d+)') { return [int]$matches[1] }
    }
    return 8200
}

function Dueno-Puerto([int]$p) {
    # Quién escucha en ese puerto: $null si nadie; si no, el proceso y si es un companion de esta carpeta.
    $id = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -First 1
    if (-not $id) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    $padre = if ($proc) { Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue }
    $deAqui = [bool]($proc -and $proc.CommandLine -match '\s-m\s+companion(\s|$)' -and
        (($proc.ExecutablePath -and $proc.ExecutablePath.StartsWith("$raiz\", [StringComparison]::OrdinalIgnoreCase)) -or
         ($padre -and $padre.ExecutablePath -and $padre.ExecutablePath.StartsWith("$raiz\", [StringComparison]::OrdinalIgnoreCase))))
    return @{ Id = $id; Nombre = $(if ($proc) { $proc.Name } else { "?" }); Companion = $deAqui }
}

function Puerto-Libre {
    # El primero libre desde 8200, sin los de las pruebas (8201, 8211) ni el de la voz (8210).
    return 8200..8299 | Where-Object { $_ -notin 8201, 8210, 8211 -and -not (Dueno-Puerto $_) } | Select-Object -First 1
}

function Guardar-Puerto([int]$p) {
    # PORT=… en .env, sin BOM y sin tocar las demás líneas (ahí puede estar la clave de API).
    $ruta = Join-Path $raiz ".env"
    $lineas = @(if (Test-Path $ruta) { [IO.File]::ReadAllLines($ruta) })
    $hay = $false
    $lineas = @($lineas | ForEach-Object { if ($_ -match '^\s*PORT\s*=') { $hay = $true; "PORT=$p" } else { $_ } })
    if (-not $hay) { $lineas += "PORT=$p" }
    [IO.File]::WriteAllLines($ruta, $lineas, (New-Object System.Text.UTF8Encoding $false))
}
