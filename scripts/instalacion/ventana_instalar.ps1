# Ventana de instalación: elige qué instalar y enseña el progreso en vivo. Doble clic en Instalar.bat.
# Por debajo ejecuta instalar.ps1 (el mismo de la terminal), que imprime marcas de progreso con COMPANION_UI=1.
#
# Con -Paquete (la abre el instalador .exe de un Release, desde la carpeta temporal donde se descomprime): deja
# elegir la carpeta (por defecto C:\Program Files\Companion, o donde ya esté instalado), copia ahí el programa
# —solo lo que cambió respecto a la versión instalada— y luego completa o actualiza lo demás.
param([string]$Paquete = "")
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)          # donde están estos scripts (la carpeta instalada, o el paquete)
$paquete = [bool]$Paquete
$destino = $raiz                                  # donde se instala
$versionNueva = if (Test-Path "$raiz\VERSION") { (Get-Content "$raiz\VERSION" -Raw).Trim() } else { "" }
Set-Location $raiz
foreach ($f in @(Get-ChildItem "$raiz\*.ps1") + @(Get-ChildItem "$raiz\scripts\*.ps1")) {
    Unblock-File $f.FullName -ErrorAction SilentlyContinue          # copias bajadas de internet como .zip
}
. "$PSScriptRoot\ventana_comun.ps1"
trap { Avisar "No pude abrir la ventana: $($_.Exception.Message)" "Companion" "Error"; break }
$instalador = if ($env:COMPANION_INSTALAR_SCRIPT) { $env:COMPANION_INSTALAR_SCRIPT } else { "$raiz\instalar.ps1" }

$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Instalar Companion" Width="620" Height="720" MinHeight="560" WindowStartupLocation="CenterScreen"
        Background="#14121F" FontFamily="Segoe UI" ResizeMode="CanResizeWithGrip">
  <!--ESTILOS-->
  <Grid Background="#14121F">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <StackPanel Grid.Row="0" Orientation="Horizontal" Margin="28,24,28,14">
      <Image x:Name="Logo" Width="46" Height="46" Margin="0,0,14,0"/>
      <StackPanel VerticalAlignment="Center">
        <TextBlock x:Name="Titulo" Text="Instalar Companion" FontSize="22" FontWeight="SemiBold" Foreground="#ECEAF6"/>
        <TextBlock x:Name="Subtitulo" Text="Elige qué quieres y pulsa Instalar. No hace falta nada más." FontSize="13" Foreground="#9B96B8" TextWrapping="Wrap"/>
      </StackPanel>
    </StackPanel>

    <Grid Grid.Row="1" Margin="28,0,28,8">
      <!-- 1. opciones -->
      <ScrollViewer x:Name="PaginaOpciones" VerticalScrollBarVisibility="Auto">
        <StackPanel>
          <Border x:Name="TarjetaCarpeta" Style="{StaticResource Tarjeta}" Visibility="Collapsed">
            <StackPanel>
              <TextBlock Style="{StaticResource Seccion}" Text="CARPETA DE INSTALACIÓN"/>
              <DockPanel>
                <Button x:Name="CambiarCarpeta" DockPanel.Dock="Right" Style="{StaticResource Boton}" Content="Cambiar…" Margin="10,0,0,0"/>
                <TextBox x:Name="Carpeta" FontSize="13.5" Padding="8,6" VerticalContentAlignment="Center"
                         Background="#0F0D18" Foreground="#ECEAF6" BorderBrush="#2E2A45" CaretBrush="#ECEAF6"/>
              </DockPanel>
              <TextBlock x:Name="VersionNota" Style="{StaticResource Nota}" Margin="0,8,0,0"/>
            </StackPanel>
          </Border>
          <Border Style="{StaticResource Tarjeta}">
            <StackPanel>
              <TextBlock Style="{StaticResource Seccion}" Text="TU PC"/>
              <TextBlock x:Name="InfoPC" Foreground="#ECEAF6" FontSize="13.5" TextWrapping="Wrap"/>
              <TextBlock x:Name="YaInstalado" Style="{StaticResource Nota}" Margin="0,6,0,0" Visibility="Collapsed"
                         Text="Ya hay partes instaladas: se saltan y solo se completa lo que falte."/>
            </StackPanel>
          </Border>
          <Border Style="{StaticResource Tarjeta}">
            <StackPanel>
              <TextBlock Style="{StaticResource Seccion}" Text="VOZ"/>
              <RadioButton x:Name="VozAuto" GroupName="voz" IsChecked="True">
                <StackPanel Margin="4,-2,0,0">
                  <TextBlock Text="Automática (recomendada)" Foreground="#ECEAF6" FontSize="14"/>
                  <TextBlock x:Name="VozAutoNota" Style="{StaticResource Nota}"/>
                </StackPanel>
              </RadioButton>
              <RadioButton x:Name="VozAmbas" GroupName="voz">
                <StackPanel Margin="4,-2,0,0">
                  <TextBlock Text="Voz completa y ligera" Foreground="#ECEAF6" FontSize="14"/>
                  <TextBlock Style="{StaticResource Nota}" Text="Voces clonadas, las más naturales. Necesita tarjeta NVIDIA. Unos 8 GB."/>
                </StackPanel>
              </RadioButton>
              <RadioButton x:Name="VozLigera" GroupName="voz">
                <StackPanel Margin="4,-2,0,0">
                  <TextBlock Text="Solo voz ligera" Foreground="#ECEAF6" FontSize="14"/>
                  <TextBlock Style="{StaticResource Nota}" Text="Funciona en cualquier PC, en el procesador. Suena más sintética. Unos 0,4 GB."/>
                </StackPanel>
              </RadioButton>
            </StackPanel>
          </Border>
          <Border Style="{StaticResource Tarjeta}">
            <StackPanel>
              <TextBlock Style="{StaticResource Seccion}" Text="CEREBRO Y ACCESOS"/>
              <CheckBox x:Name="ConOllama" IsChecked="True">
                <StackPanel Margin="4,-2,0,0">
                  <TextBlock Text="Cerebro local (Ollama y un modelo de unos 5 GB)" Foreground="#ECEAF6" FontSize="14" TextWrapping="Wrap"/>
                  <TextBlock Style="{StaticResource Nota}" Text="Para conversar sin internet ni clave. Sin él necesitas una clave de API (Google Gemini tiene una gratuita)."/>
                </StackPanel>
              </CheckBox>
              <CheckBox x:Name="ConAccesos" IsChecked="True">
                <StackPanel Margin="4,-2,0,0">
                  <TextBlock Text="Accesos directos en el escritorio y en el menú Inicio" Foreground="#ECEAF6" FontSize="14" TextWrapping="Wrap"/>
                  <TextBlock Style="{StaticResource Nota}" Text="También aparece en Configuración › Aplicaciones, para desinstalarlo desde ahí."/>
                </StackPanel>
              </CheckBox>
            </StackPanel>
          </Border>
          <TextBlock x:Name="Espacio" Style="{StaticResource Nota}" Margin="2,0,2,8"/>
        </StackPanel>
      </ScrollViewer>

      <!-- 2. progreso -->
      <Grid x:Name="PaginaProgreso" Visibility="Collapsed">
        <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
        <Border Grid.Row="0" Style="{StaticResource Tarjeta}">
          <StackPanel x:Name="ListaPasos"/>
        </Border>
        <Border x:Name="TarjetaProgreso" Grid.Row="1" Style="{StaticResource Tarjeta}">
          <StackPanel>
            <DockPanel>
              <TextBlock x:Name="TotalTexto" DockPanel.Dock="Right" Foreground="#ECEAF6" FontSize="13.5" FontWeight="SemiBold"/>
              <TextBlock Text="Progreso total" Foreground="#ECEAF6" FontSize="13.5"/>
            </DockPanel>
            <ProgressBar x:Name="Total" Margin="0,6,0,12" Maximum="100" Height="10"/>
            <TextBlock x:Name="Accion" Foreground="#ECEAF6" FontSize="13" TextTrimming="CharacterEllipsis"/>
            <ProgressBar x:Name="Actual" Margin="0,6,0,6" Maximum="100" Height="6"/>
            <DockPanel>
              <TextBlock x:Name="Tiempo" DockPanel.Dock="Right" Style="{StaticResource Nota}"/>
              <TextBlock x:Name="Velocidad" Style="{StaticResource Nota}"/>
            </DockPanel>
            <TextBlock x:Name="Ultima" Style="{StaticResource Nota}" Margin="0,4,0,0" FontFamily="Consolas" FontSize="11.5"
                       TextWrapping="NoWrap" TextTrimming="CharacterEllipsis"/>
          </StackPanel>
        </Border>
        <Grid Grid.Row="2">
          <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/></Grid.RowDefinitions>
          <Border x:Name="Resultado" Grid.Row="0" CornerRadius="12" Padding="16,12" Margin="0,0,0,10" Visibility="Collapsed">
            <TextBlock x:Name="ResultadoTexto" Foreground="#ECEAF6" FontSize="13.5" TextWrapping="Wrap"/>
          </Border>
          <Expander x:Name="Detalles" Grid.Row="1" Header="Ver detalles" Foreground="#9B96B8" FontSize="12.5">
            <TextBox x:Name="Registro" Margin="0,6,0,0" IsReadOnly="True" FontFamily="Consolas" FontSize="11"
                     Background="#0F0D18" Foreground="#B8B3D6" BorderBrush="#2E2A45" TextWrapping="Wrap"
                     VerticalScrollBarVisibility="Auto" MinHeight="120"/>
          </Expander>
        </Grid>
      </Grid>
    </Grid>

    <Border Grid.Row="2" Background="#1A1729" BorderBrush="#2E2A45" BorderThickness="0,1,0,0" Padding="28,14">
      <DockPanel LastChildFill="False">
        <TextBlock x:Name="Pie" DockPanel.Dock="Left" VerticalAlignment="Center" Style="{StaticResource Nota}" MaxWidth="300"/>
        <Button x:Name="Principal" DockPanel.Dock="Right" Style="{StaticResource Primario}" Content="Instalar" Margin="10,0,0,0"/>
        <Button x:Name="Secundario" DockPanel.Dock="Right" Style="{StaticResource Boton}" Content="Cancelar"/>
      </DockPanel>
    </Border>
  </Grid>
</Window>
'@
$w, $e = Cargar-Ventana $xaml

# ---------------------------------------------------------------- lo que hay en esta PC
$gpu = $null
try {
    $smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
    if ($smi) {
        $l = (& $smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        if ($l) { $p = $l -split ","; $gpu = @{ Nombre = $p[0].Trim(); GB = [math]::Round([double]$p[1] / 1024) } }
    }
} catch { }
$completaRecomendada = $gpu -and $gpu.GB -ge 3.5      # una NVIDIA de 4 GB: la completa y el oído ocupan ~2,6 GB
$script:libre = 0
$e.VozAutoNota.Text = if ($completaRecomendada) { "En tu PC: las dos. Suena la completa y, si a la tarjeta le falta memoria (modelo local grande, un juego), pasa sola a la ligera." }
                      else { "En tu PC: solo voz ligera (la completa necesita una NVIDIA de 4 GB o más)." }
if (-not $gpu) { $e.VozAmbas.IsEnabled = $false }

function Version-Instalada([string]$dir) {
    # La versión que dejó el instalador en esa carpeta ("" si no hay nada instalado con él).
    $m = Join-Path $dir "manifest.json"
    if (-not (Test-Path $m)) { return "" }
    try { return ([IO.File]::ReadAllText($m) | ConvertFrom-Json).version } catch { return "" }
}

function Carpeta-Por-Defecto {
    # Donde ya esté instalado (lo apuntó el instalador en Aplicaciones instaladas); si no, C:\Program Files\Companion.
    try {
        $loc = (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CompanionPC" -ErrorAction Stop).InstallLocation
        if ($loc -and (Test-Path "$loc\iniciar.ps1") -and -not (Test-Path "$loc\.git")) { return $loc }
    } catch { }
    return Join-Path $env:ProgramFiles "Companion"
}

function Cambiar-Destino([string]$dir) {
    # Todo lo que depende de la carpeta elegida: versión instalada, lo que ya hay, el espacio libre y el botón.
    $script:destino = $dir.Trim().TrimEnd("\")
    $d = $script:destino
    $git = $d -and (Test-Path "$d\.git")
    $hay = $d -and ((Test-Path "$d\.venv\Scripts\python.exe") -or (Test-Path "$d\desktop\electron\electron.exe") -or (Test-Path "$d\models\whisper"))
    $e.YaInstalado.Visibility = if ($hay -and -not $git) { "Visible" } else { "Collapsed" }
    $disco = if ($d -match '^[A-Za-z]:') { Get-PSDrive -Name $d.Substring(0, 1) -ErrorAction SilentlyContinue } else { $null }
    $script:libre = if ($disco) { $disco.Free } else { 0 }
    $e.InfoPC.Text = if ($gpu) { "Tarjeta gráfica: $($gpu.Nombre) ($($gpu.GB) GB)." } else { "No encontré una tarjeta NVIDIA: todo correrá en el procesador." }
    if (-not $paquete) { $e.InfoPC.Text += "`nSe instala en: $d"; return }
    $antes = Version-Instalada $d
    $e.Principal.IsEnabled = -not $git -and [bool]$d
    if ($git) {
        $e.VersionNota.Text = "Esa carpeta es una copia de desarrollo (git): se actualiza con git pull. Elige otra."
        $e.VersionNota.Foreground = "#F87171"
    } elseif ($antes -and $antes -eq $versionNueva) {
        $e.VersionNota.Text = "Ya tienes la versión $versionNueva. Se revisa que no falte nada; no se vuelve a descargar lo que ya está."
        $e.VersionNota.Foreground = "#9B96B8"
    } elseif ($antes) {
        $e.VersionNota.Text = "Tienes la versión ${antes}: se actualiza a la $versionNueva copiando solo lo que cambió. Tus datos, voces y personajes se conservan."
        $e.VersionNota.Foreground = "#9B96B8"
    } elseif ($hay) {
        $e.VersionNota.Text = "Ahí ya hay un companion: se pone al día con la versión $versionNueva sin tocar tus datos."
        $e.VersionNota.Foreground = "#9B96B8"
    } else {
        $e.VersionNota.Text = "Se instala la versión $versionNueva."
        $e.VersionNota.Foreground = "#9B96B8"
    }
    $e.Principal.Content = if ($antes -or $hay) { "Actualizar" } else { "Instalar" }
}

function Elegida {
    if ($e.VozLigera.IsChecked) { return "ligera" }
    if ($e.VozAmbas.IsChecked) { return "ambas" }
    return "auto"
}
function Calcular-Espacio {
    $voz = Elegida
    $completa = $voz -eq "ambas" -or ($voz -eq "auto" -and $completaRecomendada)
    $gb = 3.5 + 0.4 + $(if ($completa) { 7 } else { 0 })
    $texto = "Ocupará unos {0:N0} GB en esta carpeta" -f $gb
    if ($e.ConOllama.IsChecked) { $texto += " y unos 5 GB más del modelo local (en la carpeta de Ollama)" }
    $unidad = if ($script:destino -match '^[A-Za-z]:') { $script:destino.Substring(0, 2) } else { "el disco" }
    $texto += ". Libres en $unidad {0:N0} GB. Según tu conexión, tarda de 10 a 40 minutos (una actualización, mucho menos)." -f ($script:libre / 1GB)
    $e.Espacio.Text = $texto
    $falta = $script:libre -gt 0 -and $script:libre / 1GB -lt $gb + 1
    $e.Espacio.Foreground = if ($falta) { "#F87171" } else { "#9B96B8" }
}
foreach ($c in $e.VozAuto, $e.VozAmbas, $e.VozLigera, $e.ConOllama) { $c.Add_Click({ Calcular-Espacio }) }

if ($paquete) {
    $e.TarjetaCarpeta.Visibility = "Visible"
    $e.Titulo.Text = "Instalar Companion $versionNueva"
    $w.Title = "Instalar Companion $versionNueva"
    $inicial = if ($env:COMPANION_UI_DESTINO) { $env:COMPANION_UI_DESTINO } else { Carpeta-Por-Defecto }
    $e.Carpeta.Text = $inicial
    Cambiar-Destino $inicial
    # En una actualización se mantiene lo que ya había: la voz completa y el cerebro local.
    if (Test-Path "$inicial\voz\.venv\Scripts\python.exe") { if ($gpu) { $e.VozAmbas.IsChecked = $true } }
    elseif ((Test-Path "$inicial\models\piper") -and (Test-Path "$inicial\.venv") -and -not $completaRecomendada) { $e.VozLigera.IsChecked = $true }
    if ((Test-Path "$inicial\.venv") -and -not (Get-Command ollama -ErrorAction SilentlyContinue) -and
        -not (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $e.ConOllama.IsChecked = $false }
    $e.Carpeta.Add_TextChanged({ Cambiar-Destino $e.Carpeta.Text; Calcular-Espacio })
    $e.CambiarCarpeta.Add_Click({
        Add-Type -AssemblyName System.Windows.Forms
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = "¿Dónde instalo Companion? Se crea una carpeta «Companion» dentro de la que elijas."
        $dlg.ShowNewFolderButton = $true
        $actual = $e.Carpeta.Text.Trim()
        if ($actual -and (Test-Path (Split-Path -Parent $actual))) { $dlg.SelectedPath = Split-Path -Parent $actual }
        if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $elegida = $dlg.SelectedPath.TrimEnd("\")
            # Si ya es una instalación (o se llama Companion), esa misma; si no, una carpeta Companion dentro.
            if (-not (Test-Path "$elegida\iniciar.ps1") -and (Split-Path -Leaf $elegida) -ne "Companion") { $elegida = Join-Path $elegida "Companion" }
            $e.Carpeta.Text = $elegida
        }
    })
} else {
    Cambiar-Destino $raiz
}
Calcular-Espacio

# ---------------------------------------------------------------- pasos
$definicion = [ordered]@{
    programa  = @("El programa (solo lo que cambió)", 2)
    python    = @("Python propio", 3)
    companion = @("Librerías del companion", 10)
    interfaz  = @("Interfaz y app de escritorio", 6)
    recursos  = @("Revisando tu PC", 1)
    oido      = @("El oído (Whisper, 1,5 GB)", 12)
    ligera    = @("Voz ligera (Piper, 380 MB)", 4)
    torch     = @("Voz completa: PyTorch (unos 3 GB)", 25)
    f5        = @("Voz completa: F5-TTS y su modelo (1,4 GB)", 10)
    ollama    = @("Cerebro local (Ollama y un modelo)", 18)
    final     = @("Accesos directos y últimos detalles", 1)
}
$script:filas = [ordered]@{}
$script:trabajo = $null
$script:estado = "opciones"           # opciones | instalando | listo | fallo | cancelado
$script:activo = $null
$script:pct = 0
$script:fin = $false
$script:ultimoError = ""
$script:ultimasErr = New-Object System.Collections.Generic.Queue[string]
$script:inicio = $null
$script:bytesPaso = 0.0
$script:ultimoProgreso = [DateTime]::MinValue
$script:registroArchivo = $null
$script:tick = 0

function Recalcular-Total {
    $suma = 0.0; $hecho = 0.0
    foreach ($k in $definicion.Keys) {
        $f = $script:filas[$k]
        if ($f.Estado -eq "omitido") { continue }
        $peso = $definicion[$k][1]
        $suma += $peso
        if ($f.Estado -eq "hecho") { $hecho += $peso }
        elseif ($f.Estado -eq "activo") { $hecho += $peso * $script:pct / 100 }
    }
    $v = if ($suma) { [math]::Min(100, 100 * $hecho / $suma) } else { 0 }
    $e.Total.Value = $v
    $e.TotalTexto.Text = "{0:N0} %" -f $v
}

function Registrar([string]$linea) {
    if ($script:registroArchivo) { $script:registroArchivo.WriteLine($linea) }
    $e.Registro.AppendText($linea + "`r`n")
    if ($e.Registro.LineCount -gt 3000) { $e.Registro.Text = ($e.Registro.Text -split "`r`n" | Select-Object -Last 2000) -join "`r`n" }
    $e.Registro.ScrollToEnd()
}

function Procesar([string]$linea, [bool]$esError) {
    if ($linea -match '^::(\w+)::?(.*)$') {
        $tipo, $resto = $matches[1], $matches[2]
        $a, $b = ($resto -split '::', 2) + @("")
        switch ($tipo) {
            "paso" {
                if ($script:activo -and $script:filas[$script:activo].Estado -eq "activo") { Estado-Paso $script:filas[$script:activo] "hecho" }
                $script:activo = $a
                if ($script:filas[$a]) { Estado-Paso $script:filas[$a] "activo" "" }
                $script:pct = 0
                $script:bytesPaso = 0.0
                $e.Actual.Value = 0
                $e.Actual.IsIndeterminate = $true
                $e.Accion.Text = if ($script:filas[$a]) { $definicion[$a][0] + "…" } else { $a }
            }
            "omitido" { if ($script:filas[$a] -and $script:filas[$a].Estado -eq "pendiente") { Estado-Paso $script:filas[$a] "omitido" } }
            "progreso" {
                $script:pct = [int]$a
                $script:ultimoProgreso = [DateTime]::UtcNow
                $e.Actual.IsIndeterminate = $false
                $e.Actual.Value = $script:pct
                if ($b) { $e.Accion.Text = $b }
                if ($script:activo -and $script:filas[$script:activo]) { $script:filas[$script:activo].Detalle.Text = "$script:pct %" }
            }
            "error" { $script:ultimoError = $resto }
            "fin" {
                if ($script:activo -and $script:filas[$script:activo]) { Estado-Paso $script:filas[$script:activo] "hecho" }
                $script:fin = $true
            }
        }
        Recalcular-Total
        return
    }
    Registrar $linea
    if ($esError) {
        $script:ultimasErr.Enqueue($linea)
        while ($script:ultimasErr.Count -gt 6) { [void]$script:ultimasErr.Dequeue() }
    }
    if ($linea -notmatch '^\s*(\+ |At line|En línea|CategoryInfo|FullyQualifiedErrorId)') { $e.Ultima.Text = $linea }   # no el adorno de los errores de PowerShell
}

function Mostrar-Pagina([string]$cual) {
    $e.PaginaOpciones.Visibility = if ($cual -eq "opciones") { "Visible" } else { "Collapsed" }
    $e.PaginaProgreso.Visibility = if ($cual -eq "progreso") { "Visible" } else { "Collapsed" }
}

function Puede-Escribir([string]$dir) {
    # ¿El usuario puede crear y escribir en esa carpeta sin ser administrador?
    try {
        New-Item -ItemType Directory -Force $dir -ErrorAction Stop | Out-Null
        $f = Join-Path $dir (".prueba_" + [guid]::NewGuid().ToString("N"))
        [IO.File]::WriteAllText($f, "x")
        Remove-Item $f -Force
        return $true
    } catch { return $false }
}

function Preparar-Carpeta([string]$dir) {
    # En C:\Program Files hace falta permiso de administrador, pero solo una vez: se crea la carpeta y se le da a
    # tu usuario permiso para modificarla. Así la app (que escribe sus datos ahí) y las actualizaciones funcionan
    # sin administrador, y nada se ejecuta como administrador desde esa carpeta.
    if (Puede-Escribir $dir) { return $true }
    if (-not (Preguntar "Para instalar en`n$dir`nWindows pedirá permiso de administrador una sola vez (para crear la carpeta y dejar que tu usuario la use).`n`n¿Seguir?" "Instalar Companion")) { return $false }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $q = $dir.Replace("'", "''")
    $orden = "New-Item -ItemType Directory -Force -Path '$q' | Out-Null; & icacls.exe '$q' /grant '*${sid}:(OI)(CI)M' /T /C /Q | Out-Null"
    $codificada = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($orden))
    try {
        Start-Process powershell.exe -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $codificada"
    } catch {
        Avisar "No se dio el permiso de administrador. Elige otra carpeta (por ejemplo dentro de tu usuario) o vuelve a intentarlo." "Instalar Companion" "Warning"
        return $false
    }
    if (Puede-Escribir $dir) { return $true }
    Avisar "No pude preparar la carpeta $dir. Elige otra." "Instalar Companion" "Error"
    return $false
}

function Puerto-De([string]$dir) {
    $env_ = Join-Path $dir ".env"
    if (Test-Path $env_) {
        $l = [IO.File]::ReadAllLines($env_) | Where-Object { $_ -match '^\s*PORT\s*=\s*(\d+)' } | Select-Object -First 1
        if ($l -and $l -match '(\d+)') { return [int]$matches[1] }
    }
    return 8200
}

function Empezar {
    $d = $script:destino
    $script:esActualizacion = $paquete -and ([bool](Version-Instalada $d) -or (Test-Path "$d\.venv\Scripts\python.exe"))
    if ($paquete) {
        if (-not $d) { return }
        if (Test-Path "$d\.git") { Avisar "Esa carpeta es una copia de desarrollo (git): actualízala con git pull." "Instalar Companion" "Warning"; return }
        if (-not (Preparar-Carpeta $d)) { return }
    }
    if (-not $script:prueba -and (Test-Path "$d\detener.ps1")) {
        $abierto = Get-NetTCPConnection -LocalPort (Puerto-De $d) -State Listen -ErrorAction SilentlyContinue
        if ($abierto) {
            if (-not (Preguntar "El companion está abierto. Para instalar hay que cerrarlo un momento.`n`n¿Lo cierro ahora?" "Instalar Companion")) { return }
            Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$d\detener.ps1`"" -WindowStyle Hidden -Wait
        }
    }
    $voz = Elegida
    $argumentos = @("-Voz", $voz)
    if (-not $e.ConOllama.IsChecked) { $argumentos += "-SinOllama" }
    if ($e.ConAccesos.IsChecked) { $argumentos += "-AccesosDirectos" }

    $e.ListaPasos.Children.Clear()
    $script:filas = [ordered]@{}
    foreach ($k in $definicion.Keys) { $script:filas[$k] = Fila-Paso $e.ListaPasos $definicion[$k][0] }
    if (-not $paquete) { Estado-Paso $script:filas.programa "omitido" }
    if ($voz -eq "ligera") { Estado-Paso $script:filas.torch "omitido"; Estado-Paso $script:filas.f5 "omitido" }
    if (-not $e.ConOllama.IsChecked) { Estado-Paso $script:filas.ollama "omitido" }
    $script:activo = $null; $script:pct = 0; $script:fin = $false; $script:ultimoError = ""; $script:ultimasErr.Clear()
    $e.Registro.Clear(); $e.Ultima.Text = ""; $e.Resultado.Visibility = "Collapsed"; $e.TarjetaProgreso.Visibility = "Visible"
    $e.Detalles.IsExpanded = $false
    $e.Actual.IsIndeterminate = $true; $e.Accion.Text = "Empezando…"
    Recalcular-Total

    New-Item -ItemType Directory -Force "$d\data" | Out-Null
    $script:registroArchivo = New-Object IO.StreamWriter "$d\data\instalacion.log", $false, (New-Object Text.UTF8Encoding $false)
    $script:registroArchivo.AutoFlush = $true
    $script:registroArchivo.WriteLine("Instalación $(Get-Date -Format 'yyyy-MM-dd HH:mm') · $($argumentos -join ' ')")

    $e.Titulo.Text = "Instalando…"
    $e.Subtitulo.Text = "Puedes seguir usando la PC mientras tanto. Lo ya descargado no se repite si se corta."
    $e.Principal.Visibility = "Collapsed"
    $e.Secundario.Content = "Cancelar"
    $e.Pie.Text = ""
    Mostrar-Pagina "progreso"
    $script:inicio = [DateTime]::UtcNow
    [void](Velocidad-Red)
    $e.CambiarCarpeta.IsEnabled = $false; $e.Carpeta.IsReadOnly = $true
    $script:trabajo = if ($paquete) {
        Lanzar "$raiz\scripts\instalacion\instalar_paquete.ps1" (@("-Origen", "`"$raiz`"", "-Destino", "`"$d`"") + $argumentos) $raiz
    } else { Lanzar $instalador $argumentos }
    $script:estado = "instalando"
    $timer.Start()
    Foto $w "empieza"
}

function Terminar {
    $timer.Stop()
    $codigo = $script:trabajo.Proceso.ExitCode
    Cerrar-Lectores $script:trabajo
    $e.Actual.IsIndeterminate = $false
    if ($script:estado -eq "cancelado") {
        if ($script:activo -and $script:filas[$script:activo].Estado -eq "activo") { Estado-Paso $script:filas[$script:activo] "pendiente" "cancelado" }
        $e.Titulo.Text = "Instalación cancelada"
        $e.Subtitulo.Text = "Lo que ya se descargó se conserva: al reanudar sigue donde se quedó."
        $e.Principal.Content = "Reanudar"
    } elseif ($codigo -eq 0 -and $script:fin) {
        $script:estado = "listo"
        foreach ($f in $script:filas.Values) { if ($f.Estado -eq "pendiente") { Estado-Paso $f "omitido" } }
        $script:pct = 100; Recalcular-Total
        $e.Total.Value = 100; $e.TotalTexto.Text = "100 %"
        $e.Actual.Value = 100
        $e.Accion.Text = "Todo instalado."
        $e.Titulo.Text = "¡Listo!"
        $e.Subtitulo.Text = if ($script:esActualizacion) { "Companion está al día (versión $versionNueva)." }
                            else { "El companion ya está instalado. La primera vez te pedirá tus datos, el cerebro y la voz." }
        $e.Resultado.Background = "#173326"; $e.Resultado.Visibility = "Visible"
        $e.ResultadoTexto.Text = "Instalación completa en $(Duracion ([DateTime]::UtcNow - $script:inicio))." +
            $(if ($e.ConAccesos.IsChecked) { " Tienes un acceso directo «Companion» en el escritorio." } else { "" })
        $e.Principal.Content = "Abrir Companion"
    } else {
        $script:estado = "fallo"
        if ($script:activo -and $script:filas[$script:activo]) { Estado-Paso $script:filas[$script:activo] "error" "falló" }
        $motivo = if ($script:ultimoError) { $script:ultimoError } else { ($script:ultimasErr.ToArray() -join "`n") }
        if (-not $motivo) { $motivo = "El instalador se cerró con el código $codigo." }
        $e.Titulo.Text = "No se pudo completar"
        $e.Subtitulo.Text = "Lo que ya se instaló se conserva: Reintentar sigue donde se quedó."
        $e.Resultado.Background = "#3A1A22"; $e.Resultado.Visibility = "Visible"
        $e.ResultadoTexto.Text = "$motivo`n`nSi vuelve a fallar, mira data\instalacion.log (o «Ver detalles»). Muchas veces es la conexión: reintentar suele bastar."
        $e.Detalles.IsExpanded = $true
        $e.Principal.Content = "Reintentar"
    }
    if ($script:estado -in "listo", "fallo") { $e.TarjetaProgreso.Visibility = "Collapsed" }
    if ($script:registroArchivo) { $script:registroArchivo.WriteLine("Fin: $script:estado (código $codigo)"); $script:registroArchivo.Close(); $script:registroArchivo = $null }
    $e.Principal.Visibility = "Visible"
    $e.Secundario.Content = "Cerrar"
    $e.Velocidad.Text = ""
    Foto $w $script:estado
    if ($script:prueba) {
        $resumen = @{ estado = $script:estado; codigo = $codigo; error = $script:ultimoError
                      pasos = @{}; total = [math]::Round($e.Total.Value) }
        foreach ($k in $script:filas.Keys) { $resumen.pasos[$k] = $script:filas[$k].Estado }
        $resumen | ConvertTo-Json | Set-Content (Join-Path $script:prueba "resumen.json") -Encoding UTF8
        $cierre = New-Object Windows.Threading.DispatcherTimer
        $cierre.Interval = [TimeSpan]::FromSeconds(1)
        $cierre.Add_Tick({ $this.Stop(); $w.Close() })
        $cierre.Start()
    }
}

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(150)
$timer.Add_Tick({
    $t = $script:trabajo
    $termino = $t.Proceso.HasExited
    foreach ($l in $t.Lectores) { foreach ($linea in (Leer-Lineas $l $termino)) { Procesar $linea $l.Errores } }
    $script:tick++
    if ($script:tick % 7 -eq 0) {                                   # cada segundo, más o menos
        $v = Velocidad-Red
        $script:bytesPaso += $v
        $e.Tiempo.Text = "Tiempo: " + (Duracion ([DateTime]::UtcNow - $script:inicio))
        $e.Velocidad.Text = if ($v -gt 50KB) { "Descargando a $(Tamano-Texto $v)/s · $(Tamano-Texto $script:bytesPaso) en este paso" } else { "" }
        if ($script:activo -and $script:filas[$script:activo] -and $script:filas[$script:activo].Estado -eq "activo" -and
            ([DateTime]::UtcNow - $script:ultimoProgreso).TotalSeconds -gt 3 -and $script:bytesPaso -gt 1MB) {
            $script:filas[$script:activo].Detalle.Text = Tamano-Texto $script:bytesPaso
        }
        $fila = if ($script:activo) { $script:filas[$script:activo] } else { $null }
        if ($fila -and $fila.Estado -eq "activo") { $fila.Icono.Opacity = if ($fila.Icono.Opacity -lt 1) { 1 } else { 0.35 } }
    }
    if ($script:prueba -and $script:tick % 20 -eq 0) { Foto $w "progreso" }
    if ($termino) { Terminar }
})

$e.Principal.Add_Click({
    switch ($script:estado) {
        "listo" {
            Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$script:destino\iniciar.ps1`"" -WorkingDirectory $script:destino -WindowStyle Hidden
            $w.Close()
        }
        default { Empezar }              # opciones, fallo o cancelado: se (re)empieza; lo hecho se salta
    }
})
$e.Secundario.Add_Click({
    if ($script:estado -eq "instalando") {
        if (Preguntar "¿Cancelar la instalación? Lo ya descargado se conserva y puedes reanudarla luego." "Instalar Companion") {
            $script:estado = "cancelado"
            Parar-Arbol $script:trabajo.Proceso
        }
    } else { $w.Close() }
})
$w.Add_Closing({
    param($s, $ev)
    if ($script:estado -eq "instalando") {
        if (Preguntar "La instalación sigue en marcha. ¿Cancelarla y cerrar?" "Instalar Companion") {
            $script:estado = "cancelado"
            Parar-Arbol $script:trabajo.Proceso
            if ($script:registroArchivo) { $script:registroArchivo.Close() }
        } else { $ev.Cancel = $true }
    }
})

if ($script:prueba) {
    # Pruebas: elecciones por variables de entorno, se pulsa Instalar sola y (si se pide) se cancela a los N s.
    if ($env:COMPANION_UI_VOZ -eq "ligera") { $e.VozLigera.IsChecked = $true }
    if ($env:COMPANION_UI_SIN_OLLAMA -eq "1") { $e.ConOllama.IsChecked = $false }
    if ($env:COMPANION_UI_SIN_ACCESOS -eq "1") { $e.ConAccesos.IsChecked = $false }
    Calcular-Espacio
    $w.Add_ContentRendered({
        Foto $w "opciones"
        Empezar
        if ($env:COMPANION_UI_CANCELAR_EN) {
            $c = New-Object Windows.Threading.DispatcherTimer
            $c.Interval = [TimeSpan]::FromSeconds([double]$env:COMPANION_UI_CANCELAR_EN)
            $c.Add_Tick({ $this.Stop(); $e.Secundario.RaiseEvent((New-Object Windows.RoutedEventArgs ([Windows.Controls.Button]::ClickEvent))) })
            $c.Start()
        }
    })
}
[void]$w.ShowDialog()
