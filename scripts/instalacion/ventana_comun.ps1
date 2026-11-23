# Piezas de las ventanas de instalar y desinstalar (WPF, que viene con Windows: no hace falta instalar nada).
# Se carga con «. scripts\instalacion\ventana_comun.ps1» después de fijar $raiz.
#
# Modo de prueba (scripts\pruebas\prueba_instalador.py): COMPANION_UI_PRUEBA=<carpeta> pone la ventana fuera de la
# pantalla, sin barra de tareas ni foco, responde «sí» a las preguntas, guarda capturas PNG en esa carpeta y
# se cierra sola al terminar.

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
$script:prueba = $env:COMPANION_UI_PRUEBA
$script:fotos = 0

$script:Estilos = @'
<Window.Resources>
  <Style x:Key="Boton" TargetType="Button">
    <Setter Property="Foreground" Value="#ECEAF6"/>
    <Setter Property="Background" Value="#2A2640"/>
    <Setter Property="BorderBrush" Value="#3A355A"/>
    <Setter Property="Padding" Value="20,9"/>
    <Setter Property="FontSize" Value="14"/>
    <Setter Property="MinWidth" Value="110"/>
    <Setter Property="Cursor" Value="Hand"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="b" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="1" CornerRadius="10" Padding="{TemplateBinding Padding}">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="BorderBrush" Value="#C4B5FD"/></Trigger>
            <Trigger Property="IsEnabled" Value="False"><Setter TargetName="b" Property="Opacity" Value="0.45"/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key="Primario" TargetType="Button" BasedOn="{StaticResource Boton}">
    <Setter Property="Background" Value="#7C5CF0"/>
    <Setter Property="BorderBrush" Value="#8B6CF5"/>
    <Setter Property="Foreground" Value="White"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
  </Style>
  <Style x:Key="Peligro" TargetType="Button" BasedOn="{StaticResource Boton}">
    <Setter Property="Background" Value="#B4364A"/>
    <Setter Property="BorderBrush" Value="#C9485C"/>
    <Setter Property="Foreground" Value="White"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
  </Style>
  <Style TargetType="CheckBox">
    <Setter Property="Foreground" Value="#ECEAF6"/>
    <Setter Property="FontSize" Value="14"/>
    <Setter Property="Margin" Value="0,6,0,0"/>
    <Setter Property="VerticalContentAlignment" Value="Top"/>
    <Setter Property="Cursor" Value="Hand"/>
  </Style>
  <Style TargetType="RadioButton">
    <Setter Property="Foreground" Value="#ECEAF6"/>
    <Setter Property="FontSize" Value="14"/>
    <Setter Property="Margin" Value="0,6,0,0"/>
    <Setter Property="VerticalContentAlignment" Value="Top"/>
    <Setter Property="Cursor" Value="Hand"/>
  </Style>
  <Style TargetType="ProgressBar">
    <Setter Property="Height" Value="8"/>
    <Setter Property="Foreground" Value="#A78BFA"/>
    <Setter Property="Background" Value="#2A2640"/>
    <Setter Property="BorderThickness" Value="0"/>
  </Style>
  <Style x:Key="Tarjeta" TargetType="Border">
    <Setter Property="Background" Value="#1D1A2E"/>
    <Setter Property="BorderBrush" Value="#2E2A45"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="CornerRadius" Value="12"/>
    <Setter Property="Padding" Value="16,12"/>
    <Setter Property="Margin" Value="0,0,0,12"/>
  </Style>
  <Style x:Key="Seccion" TargetType="TextBlock">
    <Setter Property="Foreground" Value="#9B96B8"/>
    <Setter Property="FontSize" Value="11.5"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Margin" Value="0,4,0,2"/>
  </Style>
  <Style x:Key="Nota" TargetType="TextBlock">
    <Setter Property="Foreground" Value="#9B96B8"/>
    <Setter Property="FontSize" Value="12.5"/>
    <Setter Property="TextWrapping" Value="Wrap"/>
  </Style>
</Window.Resources>
'@

function Cargar-Ventana([string]$xaml) {
    # Devuelve la ventana y un diccionario con cada elemento que tenga x:Name.
    $xaml = $xaml.Replace("<!--ESTILOS-->", $script:Estilos)
    [xml]$doc = $xaml
    $w = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $doc))
    $e = @{}
    foreach ($n in $doc.SelectNodes("//*[@*[local-name()='Name']]")) {
        $nombre = $n.GetAttribute("Name", "http://schemas.microsoft.com/winfx/2006/xaml")
        if ($nombre) { $e[$nombre] = $w.FindName($nombre) }
    }
    $icono = Join-Path $raiz "desktop\icono.ico"
    if (Test-Path $icono) {
        $w.Icon = [Windows.Media.Imaging.BitmapFrame]::Create([Uri]$icono)
        if ($e.Logo) { $e.Logo.Source = $w.Icon }
    }
    if ($script:prueba) {
        New-Item -ItemType Directory -Force $script:prueba | Out-Null
        $w.WindowStartupLocation = "Manual"
        $w.Left = -20000; $w.Top = 0
        $w.ShowActivated = $false
        $w.ShowInTaskbar = $false
    }
    return $w, $e
}

function Foto($w, [string]$nombre) {
    # Captura de la ventana (solo en las pruebas): así se revisa sin enseñarla en la pantalla del usuario.
    if (-not $script:prueba) { return }
    $w.UpdateLayout()
    $c = $w.Content
    $bmp = New-Object Windows.Media.Imaging.RenderTargetBitmap ([int]$c.ActualWidth), ([int]$c.ActualHeight), 96, 96, ([Windows.Media.PixelFormats]::Pbgra32)
    $bmp.Render($c)
    $enc = New-Object Windows.Media.Imaging.PngBitmapEncoder
    $enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bmp))
    $script:fotos++
    $f = [IO.File]::Create((Join-Path $script:prueba ("{0:D3}_{1}.png" -f $script:fotos, $nombre)))
    try { $enc.Save($f) } finally { $f.Close() }
}

function Preguntar([string]$texto, [string]$titulo = "Companion", [string]$icono = "Question") {
    if ($script:prueba) { Add-Content (Join-Path $script:prueba "preguntas.txt") $texto -Encoding UTF8; return $true }
    return [Windows.MessageBox]::Show($texto, $titulo, "YesNo", $icono) -eq "Yes"
}

function Avisar([string]$texto, [string]$titulo = "Companion", [string]$icono = "Information") {
    if ($script:prueba) { Add-Content (Join-Path $script:prueba "avisos.txt") $texto -Encoding UTF8; return }
    [Windows.MessageBox]::Show($texto, $titulo, "OK", $icono) | Out-Null
}

# ---------------------------------------------------------------- el proceso que hace el trabajo
function Lanzar([string]$script, [string[]]$argumentos, [string]$carpeta = $raiz) {
    # Lo ejecuta en otro PowerShell oculto con COMPANION_UI=1 (imprime marcas de progreso) y la salida a dos
    # archivos que la ventana va leyendo mientras tanto.
    $tmp = Join-Path $env:TEMP ("companion_ui_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    $env:COMPANION_UI = "1"
    $lista = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$script`"") + $argumentos
    $p = Start-Process powershell.exe -ArgumentList $lista -WindowStyle Hidden -PassThru -WorkingDirectory $carpeta `
        -RedirectStandardOutput "$tmp\salida.txt" -RedirectStandardError "$tmp\errores.txt"
    $null = $p.Handle                      # sin esto, ExitCode sale vacío al terminar
    return @{ Proceso = $p; Carpeta = $tmp; Lectores = @((Nuevo-Lector "$tmp\salida.txt"), (Nuevo-Lector "$tmp\errores.txt" $true)) }
}

function Nuevo-Lector([string]$ruta, [bool]$errores = $false) {
    return @{ Ruta = $ruta; Stream = $null; Dec = [Text.Encoding]::UTF8.GetDecoder(); Resto = ""; Errores = $errores }
}

function Leer-Lineas($l, [bool]$final = $false) {
    # Lo nuevo desde la última vez, en líneas. Una línea que se reescribe con \r (barras de progreso) cuenta
    # por su último estado.
    if (-not $l.Stream) {
        if (-not (Test-Path $l.Ruta)) { return @() }
        $l.Stream = [IO.File]::Open($l.Ruta, "Open", "Read", "ReadWrite, Delete")
    }
    $buf = New-Object byte[] 65536
    $chars = New-Object char[] 65537
    $sb = New-Object System.Text.StringBuilder
    while (($n = $l.Stream.Read($buf, 0, $buf.Length)) -gt 0) {
        $c = $l.Dec.GetChars($buf, 0, $n, $chars, 0)
        [void]$sb.Append($chars, 0, $c)
    }
    $todo = $l.Resto + $sb.ToString()
    if ($final) { $todo += "`n" }
    if (-not $todo.Contains("`n")) { $l.Resto = $todo; return @() }
    $partes = $todo -split "`n"
    $l.Resto = $partes[-1]
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($p in $partes[0..($partes.Count - 2)]) {
        $seg = @($p.TrimEnd("`r") -split "`r" | Where-Object { $_.Trim() })
        if ($seg.Count) { $out.Add($seg[-1].TrimStart([char]0xFEFF).TrimEnd()) }
    }
    return $out.ToArray()
}

function Cerrar-Lectores($trabajo) {
    foreach ($l in $trabajo.Lectores) { if ($l.Stream) { $l.Stream.Close() } }
    Remove-Item $trabajo.Carpeta -Recurse -Force -ErrorAction SilentlyContinue
}

function Parar-Arbol($proceso) {
    # El instalador y todo lo que haya lanzado (uv, python, descargas).
    if ($proceso -and -not $proceso.HasExited) { & taskkill.exe /F /T /PID $proceso.Id 2>$null | Out-Null }
}

# ---------------------------------------------------------------- velocidad de descarga
$script:red = @{}
function Velocidad-Red {
    # Bytes por segundo recibidos desde la llamada anterior, en la interfaz de red que más recibe (sumar todas
    # contaría dos veces lo que pasa por un adaptador virtual).
    $mejor = 0.0
    $ahora = [DateTime]::UtcNow
    foreach ($i in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
        if ($i.OperationalStatus -ne "Up" -or $i.NetworkInterfaceType -eq "Loopback") { continue }
        try { $b = $i.GetIPStatistics().BytesReceived } catch { continue }
        $antes = $script:red[$i.Id]
        if ($antes) {
            $s = ($ahora - $antes.T).TotalSeconds
            if ($s -gt 0) { $mejor = [Math]::Max($mejor, ($b - $antes.B) / $s) }
        }
        $script:red[$i.Id] = @{ B = $b; T = $ahora }
    }
    return $mejor
}

# ---------------------------------------------------------------- lista de pasos con su estado
$script:IconosPaso = @{
    pendiente = @("○", "#5E5880"); activo = @("●", "#A78BFA"); hecho = @("✓", "#4ADE80")
    omitido = @("–", "#5E5880"); error = @("✕", "#F87171")
}

function Fila-Paso($panel, [string]$texto) {
    $g = New-Object Windows.Controls.Grid
    $g.Margin = "0,3,0,3"
    foreach ($ancho in @((New-Object Windows.GridLength 26), (New-Object Windows.GridLength 1, ([Windows.GridUnitType]::Star)), [Windows.GridLength]::Auto)) {
        $col = New-Object Windows.Controls.ColumnDefinition
        $col.Width = $ancho
        $g.ColumnDefinitions.Add($col)
    }
    $icono = New-Object Windows.Controls.TextBlock
    $icono.FontFamily = "Segoe UI Symbol"; $icono.FontSize = 15; $icono.VerticalAlignment = "Center"
    $nombre = New-Object Windows.Controls.TextBlock
    $nombre.Text = $texto; $nombre.FontSize = 14; $nombre.VerticalAlignment = "Center"; $nombre.Foreground = "#ECEAF6"
    $detalle = New-Object Windows.Controls.TextBlock
    $detalle.FontSize = 12.5; $detalle.VerticalAlignment = "Center"; $detalle.Foreground = "#9B96B8"
    [Windows.Controls.Grid]::SetColumn($nombre, 1); [Windows.Controls.Grid]::SetColumn($detalle, 2)
    $g.Children.Add($icono) | Out-Null; $g.Children.Add($nombre) | Out-Null; $g.Children.Add($detalle) | Out-Null
    $panel.Children.Add($g) | Out-Null
    $fila = @{ Icono = $icono; Nombre = $nombre; Detalle = $detalle; Estado = "" }
    Estado-Paso $fila "pendiente"
    return $fila
}

function Estado-Paso($fila, [string]$estado, $detalle = $null) {      # sin tipo: [string] convierte $null en ""
    $fila.Estado = $estado
    $fila.Icono.Text = $script:IconosPaso[$estado][0]
    $fila.Icono.Foreground = $script:IconosPaso[$estado][1]
    $fila.Icono.Opacity = 1                       # el paso activo parpadea: al cambiar de estado vuelve a verse entero
    $fila.Nombre.Foreground = if ($estado -in "omitido", "pendiente") { "#8C87A8" } else { "#ECEAF6" }
    $fila.Nombre.FontWeight = if ($estado -eq "activo") { "SemiBold" } else { "Normal" }
    if ($null -ne $detalle) { $fila.Detalle.Text = $detalle }
    elseif ($estado -eq "omitido") { $fila.Detalle.Text = "no hace falta" }
    elseif ($estado -in "hecho", "pendiente") { $fila.Detalle.Text = "" }
}

function Duracion([TimeSpan]$t) {
    if ($t.TotalHours -ge 1) { return "{0}:{1:D2}:{2:D2}" -f [int][Math]::Floor($t.TotalHours), $t.Minutes, $t.Seconds }
    return "{0}:{1:D2}" -f $t.Minutes, $t.Seconds
}

function Tamano-Texto([double]$bytes) {
    if ($bytes -ge 1GB) { return ("{0:N1} GB" -f ($bytes / 1GB)) }
    if ($bytes -ge 1MB) { return ("{0:N0} MB" -f ($bytes / 1MB)) }
    return ("{0:N0} KB" -f ($bytes / 1KB))
}
