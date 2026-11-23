# Instalador del companion (Windows). Deja TODO dentro de esta carpeta: Python, entornos, modelos y la app.
# Lo normal es hacer doble clic en Instalar.bat, que abre una ventana con el progreso. Desde una terminal:
#   powershell -ExecutionPolicy Bypass -File instalar.ps1 [-Voz auto|completa|ligera|ambas] [-SinOllama]
#                                                          [-SinModeloLocal] [-AccesosDirectos]
#
# Qué instala (lo que ya está, se salta):
#   runtime\uv.exe, runtime\python   uv (gestor de Python) y Python 3.13 propios
#   .venv                            dependencias del companion (requirements.txt)
#   web\vendor, desktop\electron     librerías 3D de la interfaz y la app de escritorio
#   models\whisper                   el oído (Whisper large-v3-turbo, 1,5 GB)
#   models\piper                     la voz ligera (Piper, 380 MB, corre en el procesador)
#   voz\.venv, voz\modelos           la voz completa (PyTorch + F5-TTS, ~6 GB; necesita tarjeta NVIDIA)
#   Ollama + un modelo local         el cerebro local (lo único que queda fuera de la carpeta: es un programa
#                                    del sistema; sus modelos viven en su propia carpeta)
#   -AccesosDirectos                 accesos en el escritorio y el menú Inicio, y la entrada en Aplicaciones
#                                    instaladas de Windows (para desinstalarlo desde ahí)
param(
    [ValidateSet("auto", "completa", "ligera", "ambas")][string]$Voz = "auto",
    [switch]$SinOllama,            # no instala Ollama ni descarga un modelo local (solo cerebro en la nube)
    [switch]$SinModeloLocal,       # instala Ollama pero no descarga ningún modelo
    [switch]$AccesosDirectos,      # crea los accesos directos y la entrada para desinstalar
    [switch]$NoRehacer             # conserva un .venv hecho con un Python de fuera (rehacerlo detiene el companion)
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$raiz = $PSScriptRoot
Set-Location $raiz
. "$raiz\scripts\instalacion\comun_instalacion.ps1"
trap { Marca error $_.Exception.Message; break }
function Paso($id, $texto) { Marca paso $id; Write-Host "`n== $texto" -ForegroundColor Cyan }
function Comprobar($que) { if ($LASTEXITCODE -ne 0) { throw "Falló: $que" } }

# ---------------------------------------------------------------- 1. uv y Python propios
Paso python "Python propio (runtime\)"
$uv = Join-Path $raiz "runtime\uv.exe"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $raiz "runtime\python"
$env:UV_CACHE_DIR = Join-Path $raiz "runtime\cache"
# Versión fija de uv y su suma SHA-256 publicada (la probada en esta PC): una descarga dañada o cambiada no se usa.
$uvVersion = "0.13.8"
$uvSuma = "529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8"
if (-not (Test-Path $uv)) {
    New-Item -ItemType Directory -Force "runtime" | Out-Null
    $zip = Join-Path $raiz "runtime\uv.zip"
    Write-Host "Descargando uv $uvVersion (gestor de Python, ~20 MB) de github.com/astral-sh/uv..."
    Descargar "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" $zip "uv"
    $real = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($real -ne $uvSuma) { Remove-Item $zip -Force; throw "La descarga de uv no coincide con su suma SHA-256: no la uso." }
    Expand-Archive -Path $zip -DestinationPath (Join-Path $raiz "runtime") -Force
    Remove-Item $zip -Force
}
# --no-bin y --no-registry: nada fuera de esta carpeta (sin ellos, uv deja python3.13.exe en ~\.local\bin y lo
# apunta en el registro de Windows)
& $uv python install 3.13 --no-bin --no-registry; Comprobar "instalar Python 3.13"

function Entorno($carpeta) {
    # Crea el entorno con el Python de runtime\. Si existe uno hecho con un Python de fuera, se rehace.
    $cfg = Join-Path $carpeta "pyvenv.cfg"
    # solo cuenta la línea «home»: la línea «command» lleva la ruta del proyecto aunque el Python sea de fuera
    $propio = (Test-Path $cfg) -and [bool](Get-Content $cfg | Where-Object { $_ -match '^\s*home\s*=' -and $_.ToLower().Contains($raiz.ToLower()) })
    if ((Test-Path "$carpeta\Scripts\python.exe") -and ($propio -or $NoRehacer)) { return }
    if (Test-Path $carpeta) {
        Write-Host "Rehaciendo $carpeta con el Python del proyecto..."
        # El companion en marcha tiene abiertos los archivos del entorno. En otro proceso: lo que «ollama stop»
        # escribe por su salida de error no debe cortar el instalador.
        Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$raiz\detener.ps1`"" -WindowStyle Hidden -Wait
        Start-Sleep -Seconds 1
        Remove-Item $carpeta -Recurse -Force
    }
    & $uv venv --python 3.13 $carpeta; Comprobar "crear $carpeta"
}

# requirements.lock: las versiones exactas probadas (sale de requirements.txt; se rehace con scripts\instalacion\fijar_versiones.ps1).
# Si alguna ya no se puede bajar, se instala lo último compatible con requirements.txt.
function Dependencias($python, $lock, $lista, $que) {
    if (Test-Path $lock) {
        & $uv pip install --python $python -r $lock
        if ($LASTEXITCODE -eq 0) { return }
        Write-Warning "No pude instalar las versiones fijas de $lock; pruebo con las últimas compatibles."
    }
    & $uv pip install --python $python -r $lista; Comprobar $que
}

# ---------------------------------------------------------------- 2. el companion
Paso companion "Entorno del companion (.venv)"
Entorno (Join-Path $raiz ".venv")
$py = Join-Path $raiz ".venv\Scripts\python.exe"
Dependencias $py "requirements.lock" "requirements.txt" "dependencias del companion"

Paso interfaz "Interfaz y app de escritorio"
& "$raiz\scripts\instalacion\setup.ps1" -SoloWeb

# ---------------------------------------------------------------- 3. modelos según la tarjeta
Paso recursos "Recursos según tu PC"
$rec = (& $py scripts\instalacion\preparar_recursos.py --recomendar) -split '\s+'
$vozRec, $modeloRec, $gb = $rec[0], $rec[1], $rec[2]
if ($gb -eq "0.0" -or $gb -eq "0") { Write-Host "Sin tarjeta NVIDIA: voz ligera y el modelo local más pequeño." }
else { Write-Host "Tarjeta de $gb GB -> voz recomendada: $vozRec, modelo local recomendado: $modeloRec" }
# Las dos voces desde 4 GB: la completa y el oído ocupan unos 2,6 GB y caben con el cerebro en la nube; si no
# caben (modelo local, un juego), el companion pasa solo a la ligera (profile.engine_now). Con menos, solo la ligera.
if ($Voz -eq "auto") { $Voz = if ([double]$gb -ge 3.5) { "ambas" } else { "ligera" } }

Paso oido "El oído (Whisper)"
& $py scripts\instalacion\preparar_recursos.py --oido; Comprobar "descargar el oído"
if ($Voz -in "ligera", "ambas") {
    Paso ligera "Voz ligera (Piper)"
    & $py scripts\instalacion\preparar_recursos.py --ligera; Comprobar "descargar la voz ligera"
} else { Marca omitido ligera }

if ($Voz -in "completa", "ambas") {
    Paso torch "Voz completa (voz\): PyTorch, varios GB"
    Entorno (Join-Path $raiz "voz\.venv")
    $pyVoz = Join-Path $raiz "voz\.venv\Scripts\python.exe"
    # PyTorch para CUDA 13 (cu130) solo funciona con un driver de NVIDIA 580 o más nuevo; con uno anterior PyTorch
    # no ve la tarjeta (cudaErrorNotSupported) y la voz completa no arranca (laptop con RTX 3050, 15 nov 2026).
    # Ahí va el de CUDA 12.6, que vale para drivers desde la serie 525 y para las tarjetas hasta las RTX 40.
    # La versión local (+cu130 / +cu126) hace que uv cambie la que ya hubiera instalada si no es la buena.
    $cudaDriver = 0.0
    $cabecera = (& nvidia-smi 2>$null | Select-Object -First 4) -join " "
    if ($cabecera -match 'CUDA (?:UMD )?Version:\s*(\d+\.\d+)') { $cudaDriver = [double]::Parse($Matches[1], [cultureinfo]::InvariantCulture) }
    $cu = if ($cudaDriver -ge 13.0 -or $cudaDriver -eq 0) { "cu130" } else { "cu126" }
    if ($cu -eq "cu126") {
        $cap = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1)
        Write-Host "El driver de NVIDIA admite CUDA $cudaDriver (menos de 13): PyTorch para CUDA 12.6."
        if ("$cap" -match '^\s*1[2-9]\.') { Write-Host "Tu tarjeta (RTX 50) necesita un driver de NVIDIA 580 o más nuevo para la voz completa: actualízalo y vuelve a instalar." }
    }
    $torchPaquetes = "torch==2.12.1 torchaudio==2.11.0" -split ' ' | ForEach-Object { "$_+$cu" }
    & $uv pip install --python $pyVoz @torchPaquetes --index-url "https://download.pytorch.org/whl/$cu"; Comprobar "PyTorch"
    Paso f5 "Voz completa: F5-TTS y su modelo"
    Dependencias $pyVoz "voz\requirements.lock" "voz\requirements.txt" "F5-TTS"
    & $py scripts\instalacion\preparar_recursos.py --completa; Comprobar "descargar el modelo de la voz completa"
} else { Marca omitido torch; Marca omitido f5 }

# ---------------------------------------------------------------- 4. cerebro local (Ollama)
if (-not $SinOllama) {
    Paso ollama "Cerebro local (Ollama)"
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"; if (-not (Test-Path $ollama)) { $ollama = $null } }
    if (-not $ollama) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host "Instalando Ollama con winget..."
            Marca progreso 0 "Instalando Ollama (el programa que mueve el cerebro local)…"
            winget install -e --id Ollama.Ollama --silent --disable-interactivity --accept-source-agreements --accept-package-agreements
            $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        }
        if (-not $ollama -or -not (Test-Path $ollama)) { Write-Warning "No pude instalar Ollama. Instálalo desde https://ollama.com/download y vuelve a instalar (o usa solo el cerebro en la nube)."; $ollama = $null }
    }
    if ($ollama -and -not $SinModeloLocal) {
        try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null }
        catch { Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep -Seconds 4 }
        # por su API: así se ve el progreso (si falla, con el propio ollama)
        & $py scripts\instalacion\preparar_recursos.py --ollama $modeloRec
        if ($LASTEXITCODE -ne 0) { Write-Host "Descargando el modelo local $modeloRec..."; & $ollama pull $modeloRec }
    }
} else { Marca omitido ollama }

# ---------------------------------------------------------------- 5. últimos detalles
Paso final "Últimos detalles"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
New-Item -ItemType Directory -Force "data" | Out-Null
# Puerto: si otro programa de esta PC ya usa el 8200, el companion se queda con uno libre (se guarda en .env).
# Un companion de esta carpeta abierto no cuenta: ese puerto es suyo.
$puerto = Leer-Puerto
$dueno = Dueno-Puerto $puerto
if ($dueno -and -not $dueno.Companion) {
    $libre = Puerto-Libre
    if ($libre) {
        Guardar-Puerto $libre
        Write-Host "El puerto $puerto lo usa otro programa ($($dueno.Nombre)): el companion usará el $libre."
        $puerto = $libre
    }
}
Write-Host "El companion escuchará en http://127.0.0.1:$puerto"
if ($AccesosDirectos) {
    # COMPANION_PRUEBA_ACCESOS (solo las pruebas): los accesos van a esa carpeta y no se toca el registro.
    $prueba = $env:COMPANION_PRUEBA_ACCESOS
    $escritorio = if ($prueba) { Join-Path $prueba "Escritorio" } else { [Environment]::GetFolderPath("Desktop") }
    $menu = if ($prueba) { Join-Path $prueba "Menu" } else { Join-Path ([Environment]::GetFolderPath("Programs")) "Companion" }
    New-Item -ItemType Directory -Force $escritorio, $menu | Out-Null
    $ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    $icono = "$raiz\desktop\icono.ico,0"
    $shell = New-Object -ComObject WScript.Shell
    # El acceso lleva el AppUserModelID de la ventana (desktop\main.js, APP_ID): Windows los agrupa en la barra de
    # tareas con el icono del companion, y anclar la ventana ancla este acceso (no electron.exe).
    if (-not ("CompanionIdApp" -as [type])) {
        Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class CompanionIdApp {
    [StructLayout(LayoutKind.Sequential, Pack = 4)] public struct PropertyKey { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit)] public struct PropVariant {
        [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        void GetCount(out uint c); void GetAt(uint i, out PropertyKey k); void GetValue(ref PropertyKey k, out PropVariant v);
        void SetValue(ref PropertyKey k, ref PropVariant v); void Commit(); }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr bc, int flags, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);
    public static void Set(string lnk, string id) {
        Guid iid = typeof(IPropertyStore).GUID; IPropertyStore st;
        SHGetPropertyStoreFromParsingName(lnk, IntPtr.Zero, 2, ref iid, out st);   // GPS_READWRITE
        var key = new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        var v = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(id) };  // VT_LPWSTR
        try { st.SetValue(ref key, ref v); st.Commit(); }
        finally { Marshal.FreeCoTaskMem(v.p); Marshal.ReleaseComObject(st); }
    }
}
"@
    }
    function Fijar-IdApp($ruta) {
        try { [CompanionIdApp]::Set($ruta, "Companion.Desktop") } catch { Write-Host "Aviso: el acceso no lleva el id de la app ($($_.Exception.Message))" }
    }
    function Acceso($ruta, $script, $descripcion) {
        $l = $shell.CreateShortcut($ruta)
        $l.TargetPath = $ps
        $l.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$raiz\$script`""
        $l.WorkingDirectory = $raiz
        $l.IconLocation = $icono
        $l.WindowStyle = 7
        $l.Description = $descripcion
        $l.Save()
        if ($script -eq "iniciar.ps1") { Fijar-IdApp $ruta }
    }
    Acceso (Join-Path $escritorio "Companion.lnk") "iniciar.ps1" "Abrir el companion"
    Acceso (Join-Path $menu "Companion.lnk") "iniciar.ps1" "Abrir el companion"
    Acceso (Join-Path $menu "Desinstalar Companion.lnk") "scripts\instalacion\ventana_desinstalar.ps1" "Quitar el companion de esta PC"
    if (-not $prueba) {
        $clave = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CompanionPC"
        New-Item -Path $clave -Force | Out-Null
        $version = if (Test-Path "$raiz\VERSION") { (Get-Content "$raiz\VERSION" -Raw).Trim() } else { "" }
        $valores = @{ DisplayName = "Companion"; Publisher = "Companion PC"; InstallLocation = $raiz; DisplayVersion = $version
                      DisplayIcon = "$raiz\desktop\icono.ico"
                      UninstallString = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$raiz\scripts\instalacion\ventana_desinstalar.ps1`"" }
        foreach ($k in $valores.Keys) { Set-ItemProperty -Path $clave -Name $k -Value $valores[$k] }
        Set-ItemProperty -Path $clave -Name NoModify -Value 1 -Type DWord
        Set-ItemProperty -Path $clave -Name NoRepair -Value 1 -Type DWord
    }
    Write-Host "Accesos directos creados en el escritorio y en el menú Inicio."
}
Marca fin
Write-Host "`n== Listo" -ForegroundColor Cyan
Write-Host "Abre el companion con Companion.bat (o el acceso directo del escritorio)."
Write-Host "La primera vez te pedirá tus datos, el cerebro (clave de API o modelo local), el personaje y la voz."
