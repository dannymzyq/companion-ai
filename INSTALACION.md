# Instalar y ejecutar el companion

Guía para dejar el companion funcionando en una PC desde cero. Todo queda dentro de la carpeta del proyecto,
salvo Ollama (el programa que corre el cerebro local), que se instala en el sistema.

## 1. Requisitos

| | Mínimo | Recomendado |
| --- | --- | --- |
| Sistema | Windows 10 u 11 de 64 bits | Windows 11 |
| Disco libre | 6 GB (sin voz completa ni cerebro local) | 20 GB |
| Tarjeta gráfica | Ninguna (todo corre en el procesador, más lento) | NVIDIA con 12 GB o más |
| Internet | Para instalar; después solo si usas el cerebro en la nube | |
| Micrófono y altavoces | Sí (también se puede escribir) | Cámara, opcional |

No hace falta tener Python, Node ni nada más instalado: el instalador trae su propio Python.

En Linux y macOS existen `instalar.sh` e `iniciar.sh`, pero **no están probados**; allí no hay app de
escritorio y el companion se abre en el navegador.

## 2. Instalar

Abre una terminal en la carpeta del proyecto y ejecuta **uno** de estos comandos:

PowerShell (Windows):

```powershell
powershell -ExecutionPolicy Bypass -File instalar.ps1
```

Bash (Git Bash en Windows, Linux o macOS):

```bash
bash instalar.sh
```

En Git Bash, `instalar.sh` simplemente llama a `instalar.ps1`.

La primera instalación descarga entre 6 y 15 GB según la PC y puede tardar de 10 a 40 minutos. Se puede
repetir cuantas veces haga falta: lo que ya está instalado se salta. Si el companion está abierto y hay que
rehacer su entorno, el instalador lo cierra.

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
| `-Voz ambas` | `--voz=ambas` | Las dos, para poder cambiar entre ellas en Ajustes |
| `-SinOllama` | `--sin-ollama` | No instala Ollama ni descarga un modelo: solo cerebro en la nube |
| `-SinModeloLocal` | `--sin-modelo-local` | Instala Ollama pero no descarga ningún modelo |
| `-NoRehacer` | `--no-rehacer` (Git Bash) | Conserva un `.venv` creado con un Python de fuera del proyecto |
| | `--instalar-ollama` | Linux y macOS: instala Ollama con su script oficial |

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

Los modelos «solo texto» no pueden mirar la cámara ni la pantalla. Esta tabla sale del cálculo de memoria;
solo se ha probado en una tarjeta de 16 GB.

## 3. Ejecutar

Doble clic en **`Companion.bat`**, o desde una terminal:

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
3. **Personaje**: Chica, Chico, Esfera, Mika o un VRM tuyo, con vista previa.
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

Todos escuchan solo en esta PC (127.0.0.1).

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
| El personaje responde solo con texto, sin voz | Voz completa: mira `data\voz.log`. O pasa a la voz ligera en Ajustes › Voz |
| «La voz ligera no está instalada» | Ajustes › Voz › botón de descarga, o `instalar.ps1 -Voz ambas` |
| El modelo local responde muy lento | No cabe en la tarjeta: elige uno más pequeño en Ajustes › Cerebro › «Modelo local», cierra juegos, o usa la nube |
| «Ollama no está abierto en esta PC» | Ábrelo desde el menú Inicio, o vuelve a ejecutar `iniciar.ps1` |
| No te oye | Revisa el micrófono elegido en Ajustes; la barra debe moverse al hablar |
| El companion no arranca | Mira las últimas líneas de `data\companion.log` |
| Algo quedó a medias en la instalación | Vuelve a ejecutar el instalador: retoma donde se quedó |

## 6. Actualizar y desinstalar

- **Actualizar**: reemplaza los archivos del proyecto y vuelve a ejecutar el instalador. `Companion.bat`
  reinicia solo el servidor si el código es más nuevo.
- **Liberar espacio**: `runtime\cache` se puede borrar sin problema.
- **Desinstalar**: cierra el companion y borra la carpeta. Ollama y sus modelos se quitan aparte
  (Configuración de Windows › Aplicaciones, y `ollama rm <modelo>`).

Más detalle sobre cómo funciona por dentro en [README.md](README.md).
