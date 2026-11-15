# Instalar y ejecutar el companion

Guía para dejar el companion funcionando en una PC desde cero. Todo queda dentro de la carpeta del proyecto,
salvo Ollama (el programa que corre el cerebro local), que se instala en el sistema.

## 1. Requisitos

| | Mínimo | Recomendado |
| --- | --- | --- |
| Sistema | Windows 10 u 11 de 64 bits, o un Mac con Apple Silicon y macOS 14 | Windows 11 |
| Disco libre | 6 GB (sin voz completa ni cerebro local) | 20 GB |
| Tarjeta gráfica | Ninguna (todo corre en el procesador, más lento) | NVIDIA con 12 GB o más |
| Internet | Para instalar; después solo si usas el cerebro en la nube | |
| Micrófono y altavoces | Sí (también se puede escribir) | Cámara, opcional |

No hace falta tener Python, Node ni nada más instalado: el instalador trae su propio Python.

**Mac con Apple Silicon:** usa `Companion-X.Y.Z-mac.dmg` del Release (arrastra Companion a Aplicaciones y ábrelo;
la primera vez, Ajustes del Sistema › Privacidad y seguridad › «Abrir igualmente», porque no está firmada por un
desarrollador de Apple). La app instala todo en `~/Library/Application Support/Companion` con `instalar.sh`. En
16 GB o más se instalan las dos voces; con 8 GB, solo la ligera. Usar ventanas por ti, controlar la música y
escuchar el sonido de lo compartido solo existen en Windows.

En Linux existen `instalar.sh` e `iniciar.sh`, pero **no están probados**; allí no hay app de escritorio y el
companion se abre en el navegador.

## 2. Instalar

Descarga el instalador de la última versión, **`Companion-Setup-X.Y.Z.exe`**, de
[Releases](https://github.com/dannymzyq/companion-ai/releases) y ábrelo (si Windows SmartScreen avisa de que no
está firmado: «Más información» › «Ejecutar de todas formas»). Es la misma ventana de abajo, con una tarjeta más
arriba: **la carpeta**. Por defecto `C:\Program Files\Companion`, o donde ya esté instalado; «Cambiar…» deja
elegir otra. En Program Files, Windows pide permiso de administrador una sola vez (para crear la carpeta y darle
permiso de escritura a tu usuario). Desde una copia del código (git o .zip), haz **doble clic en `Instalar.bat`**.

1. **Elige** la voz (automática, completa y ligera, o solo ligera), si quieres el cerebro local (Ollama) y si
   quieres accesos directos. Arriba ves tu tarjeta gráfica y abajo cuánto va a ocupar y cuánto espacio libre hay.
2. Pulsa **Instalar** y mira el progreso en vivo: cada paso con su estado (○ pendiente, ● en marcha, ✓ hecho,
   – no hace falta), el progreso total, lo que está descargando con su porcentaje, la velocidad y el tiempo.
   «Ver detalles» enseña todo lo que va haciendo (queda guardado en `data\instalacion.log`).
3. Al terminar, **Abrir Companion**. Si algo falla, la ventana dice por qué y **Reintentar** sigue donde se
   quedó. Se puede **Cancelar** en cualquier momento: lo ya descargado no se repite.

Con los accesos directos, el companion queda en el escritorio y en el menú Inicio (carpeta «Companion», con
su desinstalador), y aparece en **Configuración › Aplicaciones** para quitarlo desde ahí.

Si abres `Companion.bat` sin haber instalado, se abre esta misma ventana.

**Desde una terminal** (lo mismo, sin ventana):

```powershell
powershell -ExecutionPolicy Bypass -File instalar.ps1
```

```bash
bash instalar.sh
```

En Git Bash, `instalar.sh` simplemente llama a `instalar.ps1`.

La primera instalación descarga entre 6 y 15 GB según la PC y puede tardar de 10 a 40 minutos. Se puede
repetir cuantas veces haga falta: lo que ya está instalado se salta. Si el companion está abierto, la ventana
pregunta si lo cierra antes de empezar.

Instala las mismas versiones que se probaron: uv va en una versión fija y se comprueba su suma SHA-256, y las
librerías salen de `requirements.lock` y `voz\requirements.lock`. Si alguna de esas versiones ya no se puede
descargar, avisa e instala las últimas compatibles con `requirements.txt`.

### Qué instala y dónde

| Qué | Dónde | Tamaño |
| --- | --- | --- |
| uv y Python 3.13 propios | `runtime\` | 0,1 GB, más la caché de descargas (`runtime\cache`, hasta 4 GB; se puede borrar) |
| Entorno del companion | `.venv` | 2,3 GB |
| Librerías 3D de la interfaz y app de escritorio (Electron) | `web\vendor`, `desktop\electron` | 0,3 GB |
| Oído: Whisper large-v3-turbo | `models\whisper` | 1,5 GB |
| Voz ligera: Piper (corre en el procesador) | `models\piper` | 0,4 GB |
| Voz completa: PyTorch + F5-TTS y su modelo (solo con tarjeta NVIDIA) | `voz\.venv`, `voz\modelos` | 4,9 GB |
| Cerebro local: Ollama y el modelo recomendado para la tarjeta | programa del sistema | 1 a 6 GB |

### Opciones del instalador

| PowerShell | Bash | Para qué |
| --- | --- | --- |
| `-Voz auto` | `--voz=auto` | Por defecto: elige la voz según la tarjeta |
| `-Voz ligera` | `--voz=ligera` | Solo la voz ligera (sin tarjeta NVIDIA o con poca memoria) |
| `-Voz completa` | `--voz=completa` | Solo la voz completa |
| `-Voz ambas` | `--voz=ambas` | Las dos: suena la completa y, si a la tarjeta le falta memoria, pasa sola a la ligera (lo normal con una NVIDIA de 6 GB o más) |
| `-SinOllama` | `--sin-ollama` | No instala Ollama ni descarga un modelo: solo cerebro en la nube |
| `-SinModeloLocal` | `--sin-modelo-local` | Instala Ollama pero no descarga ningún modelo |
| `-AccesosDirectos` | | Accesos en el escritorio y el menú Inicio, y la entrada en Aplicaciones instaladas |
| `-NoRehacer` | `--no-rehacer` (Git Bash) | Conserva un `.venv` creado con un Python de fuera del proyecto |
| | `--instalar-ollama` | Linux: instala Ollama con su script oficial (en el Mac, descárgalo de ollama.com) |

Ejemplo, para una PC sin tarjeta gráfica que solo usará el cerebro en la nube:

```powershell
powershell -ExecutionPolicy Bypass -File instalar.ps1 -Voz ligera -SinOllama
```

### Qué se recomienda según la tarjeta

La voz, el oído y el modelo local comparten la memoria de vídeo. El instalador y la bienvenida hacen esta
cuenta con la tarjeta de la PC:

| Tarjeta NVIDIA | Voz | Modelo local |
| --- | --- | --- |
| Ninguna o 4 GB | ligera | Gemma 3 1B (solo texto) |
| 6 GB | ligera (completa si el cerebro es la nube) | Qwen 3 1.7B (solo texto) |
| 8 GB | ligera (completa si el cerebro es la nube) | Gemma 4 E2B |
| 12 GB o más | completa | Gemma 4 E4B |

Con 16 GB se ofrece también Gemma 4 12B (unos 10,6 GB): más listo, pero con un juego abierto ya no cabe, así que
no viene marcado. Los modelos «solo texto» no pueden mirar la cámara ni la pantalla. Esta tabla sale del cálculo de memoria;
solo se ha probado en una tarjeta de 16 GB.

## 3. Ejecutar

Doble clic en el acceso directo **Companion** del escritorio (o en **`Companion.bat`**), o desde una terminal:

```powershell
powershell -ExecutionPolicy Bypass -File iniciar.ps1
```

```bash
bash iniciar.sh
```

Se abre la ventana del companion. Para arrancar solo el servidor, sin ventana, añade `-SinVentana`
(`--sin-ventana` en bash) y abre <http://127.0.0.1:8200> en el navegador.

### La primera vez: la bienvenida

1. **Tus datos**: cómo quieres que te llame, año de nacimiento y género (o prefieres no decirlo).
2. **Cerebro**: pega una clave de API (Gemini tiene capa gratuita: <https://aistudio.google.com/apikey>) o
   elige «usar un modelo en esta PC» para no usar ninguna clave.
3. **Personaje**: Avatar 1, Avatar 2, Avatar 3 (una esfera) o un VRM tuyo, con vista previa.
4. **Voz**: voz completa o ligera (viene marcada la recomendada para tu PC) y una de las nueve voces; el
   botón ▶ deja oír cada una. El personaje toma el nombre de la voz.
5. **Micrófono y cámara**: permite el acceso y elige los dispositivos.

Todo queda guardado en `data\settings.json` y se cambia después en **Ajustes** (el engranaje). Al final de
Ajustes, «Empezar de nuevo» repite la bienvenida o borra todos tus datos.

### Servicios que quedan en marcha

| Servicio | Puerto | Quién lo arranca |
| --- | --- | --- |
| Companion (interfaz y conversación) | 8200 | `iniciar.ps1` |
| Voz completa (`voz\servidor.py`) | 8210 | El propio companion, solo si usas la voz completa |
| Ollama (cerebro local) | 11434 | `iniciar.ps1`, si no estaba abierto |

Todos escuchan solo en esta PC (127.0.0.1). Si otro programa ya usa el 8200, el instalador (y, si hace falta, el
arranque) eligen el primer puerto libre desde el 8200 y lo guardan en `.env` como `PORT=…`.

### Detener

Cerrar la ventana del companion apaga también su servidor y la voz. Para apagarlo a mano:

```powershell
powershell -ExecutionPolicy Bypass -File detener.ps1
```

```bash
bash detener.sh
```

## 4. Configuración opcional (`.env`)

El instalador crea `.env` a partir de `.env.example`. Lo que se elige en la bienvenida manda sobre este
archivo, así que normalmente no hace falta tocarlo. Lo más útil:

| Variable | Para qué |
| --- | --- |
| `PORT` | Puerto del companion (8200) |
| `GEMINI_API_KEY` | Clave de Gemini, si prefieres ponerla aquí en vez de en la bienvenida |
| `LLM_PROVIDER` | `gemini` (nube) o `local` |
| `OLLAMA_MODEL` | Modelo local por defecto |
| `VOICE_ENGINE` | `completa` o `ligera` |
| `TTS_URL` | Dirección del servidor de voz (por defecto, el propio: `http://127.0.0.1:8210`) |

`.env` y la carpeta `data\` contienen tu clave y tus conversaciones: no los compartas.

## 5. Problemas frecuentes

| Qué pasa | Qué hacer |
| --- | --- |
| PowerShell dice que la ejecución de scripts está deshabilitada | Usa el comando completo con `-ExecutionPolicy Bypass`, como en esta guía |
| «Falta la clave del cerebro en la nube» | Ajustes › Cerebro › «Proveedor y clave», o cambia a «Local» |
| El personaje responde solo con texto, sin voz | Voz completa: mira `data\voz.log`. O pasa a la voz ligera en Ajustes › Voz y sonido |
| «La voz ligera no está instalada» | Ajustes › Voz y sonido › Voz › «Cambiar» › botón de descarga, o `instalar.ps1 -Voz ambas` |
| No se oye nada, o suena por otro aparato | Ajustes › Voz y sonido › «Salida de audio» y «Volumen» |
| El modelo local responde muy lento | No cabe en la tarjeta: elige uno más pequeño en Ajustes › Cerebro › «Modelo local», cierra juegos, o usa la nube |
| «Ollama no está abierto en esta PC» | Ábrelo desde el menú Inicio, o vuelve a ejecutar `iniciar.ps1` |
| No te oye | Revisa el micrófono elegido en Ajustes; la barra debe moverse al hablar |
| El companion no arranca | Mira las últimas líneas de `data\companion.log` (el aviso de error las enseña) |
| «solo se permite un uso de cada dirección de socket» (error 10048) | Otro programa usaba el puerto 8200. El instalador y el arranque ya eligen uno libre y lo guardan en `.env` (`PORT=8202`, por ejemplo); en versiones anteriores, pon tú esa línea en `.env` |
| Se cerró solo y al volver a abrirlo no sé por qué | El registro de la vez anterior queda en `data\companion.1.log` (y `.2`, `.3`) |
| Algo quedó a medias en la instalación | Vuelve a abrir `Instalar.bat` y pulsa Instalar: retoma donde se quedó. El detalle está en `data\instalacion.log` |
| Doble clic en `Instalar.bat` y no aparece nada | Windows puede tardar unos segundos la primera vez. Si sigue sin abrirse, ejecuta `powershell -ExecutionPolicy Bypass -File scripts\ventana_instalar.ps1` en una terminal para ver el error |

## 6. Actualizar y desinstalar

- **Actualizar**: abre el instalador de la versión nueva. Encuentra la carpeta donde está instalado (o la que
  elijas) y dice de qué versión a cuál actualiza; copia solo los archivos que cambiaron, borra los que la nueva
  versión ya no trae y completa lo demás saltando lo que ya está (Python, el oído, las voces, PyTorch y el
  modelo local no se vuelven a descargar salvo que la versión los cambie). Tus datos, `.env`, voces y personajes
  propios no se tocan. Si el companion está abierto, pide cerrarlo un momento. Una copia con git se actualiza con
  `git pull` (el instalador no la toca). `Companion.bat` reinicia solo el servidor si el código es más nuevo.
- **Actualizar las librerías** (para quien desarrolla): instálalas en `.venv` o `voz\.venv`, prueba que todo va
  bien y fija las versiones nuevas con `powershell -ExecutionPolicy Bypass -File scripts\fijar_versiones.ps1`.
- **Liberar espacio**: `runtime\cache` se puede borrar sin problema.
- **Desinstalar**: doble clic en **`Desinstalar.bat`**, o Configuración › Aplicaciones › Companion ›
  Desinstalar, o el acceso del menú Inicio. Se abre una ventana con lo que ocupa cada parte:
  - Marcado: Python y librerías, el oído, las voces y los accesos directos (se pueden volver a instalar).
  - Sin marcar, si quieres: los modelos locales de Ollama que usa el companion, **tus datos** (conversación,
    recuerdos, ajustes, clave de API, voces y personajes propios; van a la Papelera) y **la carpeta entera**
    (se borra unos segundos después de cerrar; no se ofrece si la carpeta es una copia con git).
  - Ollama, el programa, se queda: si ya no lo usas, quítalo desde Configuración › Aplicaciones.

  Desde una terminal: `powershell -ExecutionPolicy Bypass -File desinstalar.ps1 -Programa -Oido -VozLigera
  -VozCompleta -Accesos` (y `-ModelosOllama`, `-Datos`, `-Carpeta` si los quieres).

Más detalle sobre cómo funciona por dentro en [README.md](README.md).
