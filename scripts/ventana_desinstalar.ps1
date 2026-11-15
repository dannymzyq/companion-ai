# Ventana para desinstalar: elige qué quitar y enseña el progreso. Doble clic en Desinstalar.bat, o desde
# Configuración › Aplicaciones › Companion. Por debajo ejecuta desinstalar.ps1.
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\ventana_comun.ps1"
trap { Avisar "No pude abrir la ventana: $($_.Exception.Message)" "Companion" "Error"; break }
Set-Location $env:TEMP                    # la carpeta del companion puede acabar borrada: que nadie la tenga abierta
[Environment]::CurrentDirectory = $env:TEMP
$desinstalador = "$raiz\desinstalar.ps1"
$conGit = Test-Path "$raiz\.git"

$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Desinstalar Companion" Width="600" Height="700" MinHeight="520" WindowStartupLocation="CenterScreen"
        Background="#14121F" FontFamily="Segoe UI" ResizeMode="CanResizeWithGrip">
  <!--ESTILOS-->
  <Grid Background="#14121F">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <StackPanel Grid.Row="0" Orientation="Horizontal" Margin="28,24,28,14">
      <Image x:Name="Logo" Width="46" Height="46" Margin="0,0,14,0"/>
      <StackPanel VerticalAlignment="Center">
        <TextBlock x:Name="Titulo" Text="Desinstalar Companion" FontSize="22" FontWeight="SemiBold" Foreground="#ECEAF6"/>
        <TextBlock x:Name="Subtitulo" Text="Elige qué quitar de esta PC." FontSize="13" Foreground="#9B96B8" TextWrapping="Wrap"/>
      </StackPanel>
    </StackPanel>

    <Grid Grid.Row="1" Margin="28,0,28,8">
      <ScrollViewer x:Name="PaginaOpciones" VerticalScrollBarVisibility="Auto">
        <StackPanel>
          <Border Style="{StaticResource Tarjeta}">
            <StackPanel>
              <TextBlock Style="{StaticResource Seccion}" Text="EL PROGRAMA (SE PUEDE VOLVER A INSTALAR)"/>
              <CheckBox x:Name="Programa" IsChecked="True"><TextBlock x:Name="ProgramaT" Margin="4,-1,0,0" Foreground="#ECEAF6" TextWrapping="Wrap"/></CheckBox>
              <CheckBox x:Name="Oido" IsChecked="True"><TextBlock x:Name="OidoT" Margin="4,-1,0,0" Foreground="#ECEAF6"/></CheckBox>
              <CheckBox x:Name="VozLigera" IsChecked="True"><TextBlock x:Name="VozLigeraT" Margin="4,-1,0,0" Foreground="#ECEAF6"/></CheckBox>
              <CheckBox x:Name="VozCompleta" IsChecked="True"><TextBlock x:Name="VozCompletaT" Margin="4,-1,0,0" Foreground="#ECEAF6"/></CheckBox>
              <CheckBox x:Name="Accesos" IsChecked="True"><TextBlock Margin="4,-1,0,0" Foreground="#ECEAF6" TextWrapping="Wrap" Text="Accesos directos y la entrada en Configuración › Aplicaciones"/></CheckBox>
            </StackPanel>
          </Border>
          <Border Style="{StaticResource Tarjeta}">
            <StackPanel>
              <TextBlock Style="{StaticResource Seccion}" Text="TAMBIÉN, SI QUIERES"/>
              <CheckBox x:Name="Ollama">
                <StackPanel Margin="4,-1,0,0">
                  <TextBlock x:Name="OllamaT" Foreground="#ECEAF6" TextWrapping="Wrap" Text="Modelos locales de Ollama que usa el companion"/>
                  <TextBlock Style="{StaticResource Nota}" Text="Ollama, el programa, se queda: si ya no lo usas, quítalo desde Configuración › Aplicaciones."/>
                </StackPanel>
              </CheckBox>
              <CheckBox x:Name="Datos">
                <StackPanel Margin="4,-1,0,0">
                  <TextBlock x:Name="DatosT" Foreground="#ECEAF6" TextWrapping="Wrap"/>
                  <TextBlock Style="{StaticResource Nota}" Text="Conversación, recuerdos, ajustes, clave de API, voces y personajes propios. Van a la Papelera."/>
                </StackPanel>
              </CheckBox>
              <CheckBox x:Name="Carpeta">
                <StackPanel Margin="4,-1,0,0">
                  <TextBlock Foreground="#ECEAF6" TextWrapping="Wrap" Text="La carpeta entera del companion"/>
                  <TextBlock x:Name="CarpetaNota" Style="{StaticResource Nota}"/>
                </StackPanel>
              </CheckBox>
            </StackPanel>
          </Border>
          <TextBlock x:Name="Libera" Style="{StaticResource Nota}" Margin="2,0,2,8"/>
        </StackPanel>
      </ScrollViewer>

      <Grid x:Name="PaginaProgreso" Visibility="Collapsed">
        <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
        <Border Grid.Row="0" Style="{StaticResource Tarjeta}"><StackPanel x:Name="ListaPasos"/></Border>
        <Border x:Name="TarjetaProgreso" Grid.Row="1" Style="{StaticResource Tarjeta}">
          <StackPanel>
            <TextBlock x:Name="Accion" Foreground="#ECEAF6" FontSize="13" TextTrimming="CharacterEllipsis"/>
            <ProgressBar x:Name="Actual" Margin="0,6,0,0" Maximum="100" IsIndeterminate="True"/>
          </StackPanel>
        </Border>
        <StackPanel Grid.Row="2">
          <Border x:Name="Resultado" CornerRadius="12" Padding="16,12" Margin="0,0,0,10" Visibility="Collapsed">
            <TextBlock x:Name="ResultadoTexto" Foreground="#ECEAF6" FontSize="13.5" TextWrapping="Wrap"/>
          </Border>
          <Expander x:Name="Detalles" Header="Ver detalles" Foreground="#9B96B8" FontSize="12.5">
            <TextBox x:Name="Registro" Margin="0,6,0,0" IsReadOnly="True" FontFamily="Consolas" FontSize="11" Height="140"
                     Background="#0F0D18" Foreground="#B8B3D6" BorderBrush="#2E2A45" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto"/>
          </Expander>
        </StackPanel>
      </Grid>
    </Grid>

    <Border Grid.Row="2" Background="#1A1729" BorderBrush="#2E2A45" BorderThickness="0,1,0,0" Padding="28,14">
      <DockPanel LastChildFill="False">
        <Button x:Name="Principal" DockPanel.Dock="Right" Style="{StaticResource Peligro}" Content="Desinstalar" Margin="10,0,0,0"/>
        <Button x:Name="Secundario" DockPanel.Dock="Right" Style="{StaticResource Boton}" Content="Cancelar"/>
      </DockPanel>
    </Border>
  </Grid>
</Window>
'@
$w, $e = Cargar-Ventana $xaml

# ---------------------------------------------------------------- qué hay y cuánto ocupa (se calcula aparte)
$grupos = [ordered]@{
    Programa    = @{ Texto = "Python propio, librerías y app de escritorio"; Rutas = @("runtime", ".venv", "desktop\electron", "web\vendor") }
    Oido        = @{ Texto = "El oído (Whisper)"; Rutas = @("models\whisper") }
    VozLigera   = @{ Texto = "Voz ligera (Piper)"; Rutas = @("models\piper") }
    VozCompleta = @{ Texto = "Voz completa (PyTorch y F5-TTS)"; Rutas = @("voz\.venv", "voz\modelos") }
    Datos       = @{ Texto = "Tus datos"; Rutas = @("data", ".env", "models\custom") }
}
$tamanos = [hashtable]::Synchronized(@{})
$calculo = [PowerShell]::Create()
[void]$calculo.AddScript({
    param($raiz, $grupos, $tamanos)
    foreach ($g in $grupos.Keys) {
        $total = 0L
        foreach ($r in $grupos[$g].Rutas) {
            $p = Join-Path $raiz $r
            if (Test-Path $p -PathType Leaf) { $total += (Get-Item $p).Length; continue }
            if (-not (Test-Path $p)) { continue }
            try { foreach ($f in [IO.Directory]::EnumerateFiles($p, "*", "AllDirectories")) { try { $total += (New-Object IO.FileInfo $f).Length } catch { } } } catch { }
        }
        $tamanos[$g] = $total
    }
    try {                                 # modelos del companion que tiene Ollama, por su API
        $catalogo = @('gemma4:12b', 'gemma4:e4b-it-qat', 'gemma4:e2b-it-qat', 'qwen3:1.7b', 'gemma3:1b-it-qat')
        $m = @((Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3).models | Where-Object { $catalogo -contains $_.name })
        $tamanos["OllamaNombres"] = ($m | ForEach-Object { $_.name }) -join ", "
        $tamanos["Ollama"] = [long](($m | Measure-Object size -Sum).Sum)
    } catch { $tamanos["Ollama"] = -1 }
    $tamanos["listo"] = $true
}).AddArgument($raiz).AddArgument($grupos).AddArgument($tamanos)
$asincrono = $calculo.BeginInvoke()

foreach ($g in $grupos.Keys) { $e["${g}T"].Text = "$($grupos[$g].Texto) · calculando…" }
$e.CarpetaNota.Text = if ($conGit) { "Esta carpeta tiene git (es una copia para programar): bórrala a mano si quieres." }
                      else { "Se borra unos segundos después de cerrar esta ventana: $raiz" }
if ($conGit) { $e.Carpeta.IsEnabled = $false }

function Actualizar-Libera {
    $total = 0L
    foreach ($g in $grupos.Keys) { if ($e[$g].IsChecked -and $tamanos[$g] -gt 0) { $total += $tamanos[$g] } }
    if ($e.Ollama.IsChecked -and $tamanos.Ollama -gt 0) { $total += $tamanos.Ollama }
    $e.Libera.Text = if ($tamanos.listo) { "Se liberarán unos $(Tamano-Texto $total)." } else { "Calculando cuánto ocupa…" }
    $e.Principal.IsEnabled = [bool](@("Programa", "Oido", "VozLigera", "VozCompleta", "Accesos", "Ollama", "Datos", "Carpeta") | Where-Object { $e[$_].IsChecked })
}
$e.Carpeta.Add_Click({ if ($e.Carpeta.IsChecked) { foreach ($g in "Programa", "Oido", "VozLigera", "VozCompleta", "Accesos") { $e[$g].IsChecked = $true } }; Actualizar-Libera })
foreach ($c in "Programa", "Oido", "VozLigera", "VozCompleta", "Accesos", "Ollama", "Datos") { $e[$c].Add_Click({ Actualizar-Libera }) }

$espera = New-Object Windows.Threading.DispatcherTimer
$espera.Interval = [TimeSpan]::FromMilliseconds(300)
$espera.Add_Tick({
    foreach ($g in $grupos.Keys) {
        if ($tamanos.ContainsKey($g)) {
            $t = $tamanos[$g]
            $e["${g}T"].Text = if ($t -gt 0) { "$($grupos[$g].Texto) · $(Tamano-Texto $t)" } else { "$($grupos[$g].Texto) · no está instalado" }
        }
    }
    if ($tamanos.listo) {
        $this.Stop()
        if ($tamanos.Ollama -gt 0) { $e.OllamaT.Text = "Modelos locales de Ollama que usa el companion ($($tamanos.OllamaNombres)) · $(Tamano-Texto $tamanos.Ollama)" }
        else { $e.OllamaT.Text = "Modelos locales de Ollama que usa el companion · no hay ninguno"; $e.Ollama.IsEnabled = $false; $e.Ollama.IsChecked = $false }
        $calculo.EndInvoke($asincrono); $calculo.Dispose()
    }
    Actualizar-Libera
})
$espera.Start()
Actualizar-Libera

# ---------------------------------------------------------------- desinstalar
$etiquetas = [ordered]@{
    detener = "Cerrar el companion"; ollama = "Modelos locales de Ollama"; accesos = "Accesos directos"
    programa = "Python, librerías y app de escritorio"; oido = "El oído (Whisper)"; ligera = "Voz ligera"
    completa = "Voz completa"; datos = "Tus datos (a la Papelera)"; carpeta = "La carpeta del companion"
}
$script:estado = "opciones"
$script:filas = [ordered]@{}
$script:activo = $null
$script:fin = $false
$script:ultimoError = ""
$script:liberado = 0L

function Procesar([string]$linea) {
    if ($linea -match '^::(\w+)::?(.*)$') {
        $tipo, $a = $matches[1], ($matches[2] -split '::', 2)[0]
        switch ($tipo) {
            "paso" {
                if ($script:activo) { Estado-Paso $script:filas[$script:activo] "hecho" }
                $script:activo = $a
                if ($script:filas[$a]) { Estado-Paso $script:filas[$a] "activo" "" }
                $e.Accion.Text = "$($etiquetas[$a])…"
            }
            "omitido" { if ($script:filas[$a]) { $script:filas[$a].Nombre.Parent.Visibility = "Collapsed" } }
            "error" { $script:ultimoError = $matches[2] }
            "fin" { if ($script:activo) { Estado-Paso $script:filas[$script:activo] "hecho" }; $script:fin = $true }
        }
        return
    }
    $e.Registro.AppendText($linea + "`r`n"); $e.Registro.ScrollToEnd()
}

function Empezar {
    $elegido = @("Programa", "Oido", "VozLigera", "VozCompleta", "Accesos", "Ollama", "Datos", "Carpeta") | Where-Object { $e[$_].IsChecked }
    $lista = ($elegido | ForEach-Object { "• " + $(if ($grupos[$_]) { $grupos[$_].Texto } elseif ($_ -eq "Ollama") { "Modelos locales de Ollama" } elseif ($_ -eq "Accesos") { "Accesos directos" } else { "La carpeta entera" }) }) -join "`n"
    $aviso = "Se va a quitar:`n`n$lista`n`n" + $(if ($e.Datos.IsChecked) { "Tus datos van a la Papelera (se pueden recuperar desde ahí). " } else { "Tus datos (conversación, recuerdos, ajustes) se quedan. " }) + "¿Seguir?"
    if (-not (Preguntar $aviso "Desinstalar Companion" "Warning")) { return }
    $argumentos = @()
    $mapa = @{ Programa = "-Programa"; Oido = "-Oido"; VozLigera = "-VozLigera"; VozCompleta = "-VozCompleta"; Accesos = "-Accesos"; Ollama = "-ModelosOllama"; Datos = "-Datos"; Carpeta = "-Carpeta" }
    foreach ($k in $elegido) { $argumentos += $mapa[$k] }
    foreach ($g in $grupos.Keys) { if ($e[$g].IsChecked -and $tamanos[$g] -gt 0) { $script:liberado += $tamanos[$g] } }
    if ($e.Ollama.IsChecked -and $tamanos.Ollama -gt 0) { $script:liberado += $tamanos.Ollama }

    foreach ($k in $etiquetas.Keys) { $script:filas[$k] = Fila-Paso $e.ListaPasos $etiquetas[$k] }
    $e.PaginaOpciones.Visibility = "Collapsed"; $e.PaginaProgreso.Visibility = "Visible"
    $e.Titulo.Text = "Desinstalando…"; $e.Subtitulo.Text = "Tarda unos segundos."
    $e.Principal.Visibility = "Collapsed"; $e.Secundario.IsEnabled = $false
    $script:trabajo = Lanzar $desinstalador $argumentos $env:TEMP
    $script:estado = "desinstalando"
    $timer.Start()
    Foto $w "empieza"
}

function Terminar {
    $timer.Stop()
    $codigo = $script:trabajo.Proceso.ExitCode
    Cerrar-Lectores $script:trabajo
    $e.TarjetaProgreso.Visibility = "Collapsed"
    $e.Resultado.Visibility = "Visible"
    if ($codigo -eq 0 -and $script:fin) {
        $script:estado = "listo"
        $e.Titulo.Text = "Listo"
        $e.Subtitulo.Text = "El companion se ha quitado de esta PC."
        $e.Resultado.Background = "#173326"
        $e.ResultadoTexto.Text = "Se liberaron unos $(Tamano-Texto $script:liberado)." +
            $(if ($e.Carpeta.IsChecked) { " La carpeta se borrará al cerrar esta ventana." }
              elseif (-not $e.Datos.IsChecked) { " Tus datos siguen en la carpeta data: si vuelves a instalar, el companion te recordará." } else { "" })
    } else {
        $script:estado = "fallo"
        if ($script:activo) { Estado-Paso $script:filas[$script:activo] "error" "falló" }
        $e.Titulo.Text = "No se pudo quitar todo"
        $e.Subtitulo.Text = "Puede que algún archivo siga abierto. Cierra el companion y vuelve a intentarlo."
        $e.Resultado.Background = "#3A1A22"
        $e.ResultadoTexto.Text = if ($script:ultimoError) { $script:ultimoError } else { "El desinstalador se cerró con el código $codigo." }
        $e.Detalles.IsExpanded = $true
    }
    $e.Secundario.Content = "Cerrar"; $e.Secundario.IsEnabled = $true
    Foto $w $script:estado
    if ($script:prueba) {
        $r = @{ estado = $script:estado; codigo = $codigo; error = $script:ultimoError; pasos = @{} }
        foreach ($k in $script:filas.Keys) { $r.pasos[$k] = $script:filas[$k].Estado }
        $r | ConvertTo-Json | Set-Content (Join-Path $script:prueba "resumen.json") -Encoding UTF8
        $cierre = New-Object Windows.Threading.DispatcherTimer
        $cierre.Interval = [TimeSpan]::FromSeconds(1)
        $cierre.Add_Tick({ $this.Stop(); $w.Close() })
        $cierre.Start()
    }
}

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(150)
$timer.Add_Tick({
    $termino = $script:trabajo.Proceso.HasExited
    foreach ($l in $script:trabajo.Lectores) { foreach ($linea in (Leer-Lineas $l $termino)) { Procesar $linea } }
    if ($termino) { Terminar }
})

$e.Principal.Add_Click({ Empezar })
$e.Secundario.Add_Click({ $w.Close() })
$w.Add_Closing({ param($s, $ev) if ($script:estado -eq "desinstalando") { $ev.Cancel = $true } })

if ($script:prueba) {
    if ($env:COMPANION_UI_DATOS -eq "1") { $e.Datos.IsChecked = $true }
    if ($env:COMPANION_UI_CARPETA -eq "1") { $e.Carpeta.IsChecked = $true }
    $w.Add_ContentRendered({
        $arranque = New-Object Windows.Threading.DispatcherTimer
        $arranque.Interval = [TimeSpan]::FromMilliseconds(400)
        $arranque.Add_Tick({ if ($tamanos.listo) { $this.Stop(); Actualizar-Libera; Foto $w "opciones"; Empezar } })
        $arranque.Start()
    })
}
[void]$w.ShowDialog()
