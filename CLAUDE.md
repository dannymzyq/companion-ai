# Companion PC – instrucciones para Claude Code

Companion de escritorio (solo esta PC, RTX 5070 Ti 16 GB, Windows 11) derivado de waifuv3 (`D:\waifuv3\waifu`).
Conversación por voz en tiempo real con Mika (avatar VRM). Ver `README.md` para el flujo y los ajustes.

## Cómo correr
- Todo vive en esta carpeta: `instalar.ps1` (o `bash instalar.sh`) trae uv y Python 3.13 a `runtime\`, crea
  `.venv` y `voz\.venv`, y baja las librerías 3D (`web\vendor`), Electron, Whisper (`models\whisper`), Piper
  (`models\piper`) y F5-TTS (`voz\modelos`). Solo Ollama queda fuera (programa del sistema). El Python 3.15 del
  sistema no tiene ruedas de CTranslate2; no hay Node en esta PC (la interfaz es ES modules sin compilar).
  En esta PC `.venv` sigue hecho con el Python de ComfyUI: `instalar.ps1` sin `-NoRehacer` lo rehace con el
  propio, pero para eso detiene el companion (hazlo solo si el usuario lo pide).
- Servidor: `.venv\Scripts\python.exe -m companion` (puerto 8200). `iniciar.ps1 -SinVentana` lo arranca sin abrir la ventana.
- Pruebas sin micrófono: `scripts\prueba_componentes.py` y `scripts\prueba_ws.py` (ver README).
- El panel de navegador de Claude bloquea el micrófono: ahí la interfaz se prueba escribiendo; el avatar,
  con `scripts\maniqui_vrm.py` (maniquí VRM 1.0 o `--v0`) y `window.companion.avatar` en la consola.
  Para el micrófono de verdad, `scripts\prueba_navegador.py` (Chrome oculto y en silencio, con un micrófono simulado).
- Modelo: `models\base\mika_base.vrm` es el original y no se toca; `models\mika.vrm` se genera con
  `scripts\vestir_vrm.py`. No abras la ventana del companion sin avisar: el usuario suele estar jugando.

- **El usuario puede tener el companion abierto.** No reinicies ni apagues el servidor real (puerto 8200): pídele
  que lo haga él (`detener.ps1`, o `Companion.bat`, que lo reinicia solo si el código o `.env` son más nuevos).
  Nunca llames a `DELETE /api/memory` contra él: borra su conversación y sus recuerdos. Las pruebas van
  contra el servidor aislado de `scripts\_prueba.py` (puerto 8201, `data\prueba`); con `--local` usan Ollama.
- Memoria de vídeo (16 GB): voz completa ~1 GB (`voz\servidor.py`) + Whisper ~1,1 GB + escritorio ~2,5 GB. El modelo local tiene que
  caber en lo que queda: `gemma4:e4b-it-qat` (4,8 GB) con respaldo `gemma4:e2b-it-qat`; `gemma4:12b` no cabe y se
  desborda a la RAM (lento, se cae). `llm.py` mide la velocidad de cada turno y cambia de modelo si va lento.
- Compartir pantalla: `desktop\main.js` abre `picker.html` (pantallas y ventanas). En las pruebas se comparte
  la ventana `desktop\tarjeta-prueba.html`, nunca una ventana real.
- App de escritorio: `desktop\` (Electron descargado por `scripts\instalar_escritorio.ps1`). `scripts\prueba_escritorio.py`
  la prueba con `COMPANION_TEST=1`: ventanas fuera de pantalla, sin sonido, micrófono y cámara simulados.
  No envíes a ningún LLM una captura real de la pantalla del usuario en una prueba.
- Cuota: la capa gratuita de Gemini da 20 peticiones al día por modelo en `gemini-3.6-flash`; cada prueba de
  conversación gasta varias. `llm.py` hace el relevo de modelos (`GEMINI_FALLBACK`: Flash-Lite y luego
  `gemma-4-26b-a4b-it`, con la misma clave) y, al final, a Ollama.

## Dependencias externas
- Voz completa: servidor propio `voz\servidor.py` (F5-TTS, puerto 8210, sin token, solo 127.0.0.1), con su
  entorno `voz\.venv`. Lo arranca y lo para el companion (`companion/voz_proc.py`) según la voz elegida; lee las
  muestras de `voices\` directamente. Ya no se usa el nodo de waifuv3 (puerto 8100): no lo toques ni lo edites,
  es otro proyecto del usuario.
- Cerebro: Gemini por su API compatible con OpenAI, u Ollama local.

- Bienvenida y ajustes guardados: `companion/profile.py` + `state.py` → `data/settings.json` (perfil, proveedor
  y clave, modelo local, voz). Lo guardado manda sobre `.env`. La clave nunca se devuelve a la interfaz ni se
  imprime en las pruebas (ni siquiera sus últimos caracteres). `_prueba.Servidor()` arranca con la bienvenida
  hecha; `Servidor(nuevo=True)` la deja pendiente.
- El personaje se llama como la voz elegida (`profile.character`): `personas/mika.json` es la ficha común y su
  `name` solo sirve para el archivo del modelo por defecto. Voces y personajes no llevan etiquetas de género en
  la interfaz (decisión del usuario, 12 nov 2026); `speaks` en `voices.json` solo decide cómo habla de sí.
  Nunca llames a `POST /api/setup/reset` contra el servidor real: con `data` borra todo lo del usuario.
- Recursos: `profile.resources` reparte la memoria de vídeo (escritorio 2 GB + oído 1,1 GB + voz) y recomienda
  voz y modelo local; `profile.LOCAL_MODELS` es el catálogo (E4B, E2B, Qwen 3 1.7B, Gemma 3 1B; los dos últimos
  no ven imágenes). El modelo local que elige el usuario es el que se carga (`llm.choose_local`): no lo cambies
  por otro «que quepa» sin avisar; solo `_too_slow` baja de modelo, y lo dice. Prueba: `scripts\prueba_recursos.py`.
- Dos motores de voz (`settings.voice_engine`): `completa` = `voz\servidor.py` · `ligera` = Piper en el procesador
  (`companion/tts_light.py`, modelos en `models\piper`, sin memoria de vídeo). Una voz nueva en `voices.json`
  necesita también su `light`.
- Voces nuevas a partir de grabaciones: `scripts\importar_voces.py <carpeta>` y luego `scripts\grabar_muestras.py`.
- El nodo de voz se queda con memoria de vídeo por cada voz que llega a usar (medido el 12 nov 2026: de ~5 a
  9,5 GB tras probar 15 voces) y no la suelta hasta reiniciarse; con la tarjeta llena, cada frase pasa de 1 s a
  14 s. Por eso: las muestras ▶ son archivos pregrabados (`voices\previews`, sin pasar por el nodo), al nodo solo
  se copia la voz elegida (`profile.install_voice`) y las muestras de referencia duran unos 8 s. No pruebes
  muchas voces contra el nodo mientras el usuario conversa. Las frases de una sola cláusula muy corta
  («Hola,») el nodo las dice mal: evítalas en textos fijos.
- Voces: catálogo en `voices.json`; muestras en `voices\` (`<voz>_es.wav` + `.json` con `ref_text`), que el
  servidor de voz lee en cada petición. Origen y licencias en `voices\CREDITOS.md`.
- Personajes incluidos: `models.BUILTIN` (chica, chico, esfera) + `default` (Mika). La esfera no es un VRM:
  `web/js/orb.js`; una emoción o gesto nuevo hay que añadirlo también ahí.
- Memoria: `store.py` (messages, memories, summaries); los resúmenes los hace `Session._summarize` en ratos de calma.

## Reglas
- Personaje siempre adulto. Los temas +18 solo existen con el LLM local, y ahí van implícitos, sin interruptor
  (`prompt.adult_active`: cerebro local + `adult.enabled` en la ficha + usuario mayor de edad según el año de
  nacimiento de la bienvenida; decisión del usuario del 11 nov 2026).
  Nunca los actives para la nube (tampoco cuando la nube cae al modelo local por cuota) ni quites los límites
  de `ADULT_HARD_LIMITS`.
- Nunca subas ni muestres `.env`, modelos `.vrm` ni `data/`.
- Las poses de `web/js/avatar.js` están en convención VRM 1.0; los VRM 0.x se corrigen invirtiendo X y Z al aplicar.
- Etiquetas del LLM: `[emo:…]`, `[gesto:…]`, `[recordar: …]`. Si añades una emoción o gesto, hazlo en
  `companion/prompt.py` y en `web/js/avatar.js` a la vez (y los efectos de la emoción, en `web/js/effects.js`).
- Poses del avatar: se revisan con `window.companion.avatar.sheet([...])` (hoja de contactos) en el panel de
  navegador contra el servidor de prueba. Los brazos se escriben para el izquierdo y se reflejan.
- El prompt de sistema no debe llevar nada que cambie por turno (hora, lo que ve): eso va en `turn_context` y en
  las notas de imagen del último mensaje, para que el modelo local reutilice su caché.
- No arranques el servidor con `STT_MODEL` distinto del instalado: faster-whisper lo descarga solo de Hugging Face.
- La interfaz se sirve con `Cache-Control: no-cache` y Electron vacía su caché al arrancar. Si una prueba se
  comporta como el código anterior, sospecha primero de JavaScript en caché (pasó el 11 nov 2026).
- Micrófono y cámara reales: `scripts\prueba_dispositivos.py` (Electron oculto con `COMPANION_TEST_REAL_MEDIA=1`,
  sin cerebro: nada llega a un modelo). Úsala solo cuando el usuario pida probar su dispositivo físico. La Brio
  deja mudo su micrófono al cerrar el vídeo: no cierres y reabras la cámara sin `audio.heal()`.
- Ollama tiene una sola cola (`-np 1`) y no aborta una petición hasta leer sus imágenes: toda petición en
  segundo plano (la mirada en vivo) tiene que ser ligera. No midas modelos en Ollama mientras el usuario
  conversa en local: le frena los turnos.
