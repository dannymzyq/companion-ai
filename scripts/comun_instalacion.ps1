# Piezas comunes del instalador y el desinstalador (se cargan con «. scripts\comun_instalacion.ps1»).
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
