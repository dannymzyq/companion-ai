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
- Releases (15 nov 2026): `VERSION` + `CHANGELOG.md`; la etiqueta `vX.Y.Z` dispara `.github/workflows/release.yml`,
  que crea `dist\Companion-Setup-X.Y.Z.exe` con `scripts\crear_instalador.ps1` (lanzador `instalador\Lanzador.cs`
  compilado con el csc.exe de Windows + `paquete.zip` con `manifest.json`: huella y tamaño de cada archivo de git).
  El .exe abre `ventana_instalar.ps1 -Paquete`: carpeta por defecto `C:\Program Files\Companion` (o la de
  `InstallLocation` en HKCU), admin una sola vez para crearla y dar Modificar al usuario (la app escribe ahí sus
  datos), luego `instalar_paquete.ps1` → `copiar_programa.ps1` (solo lo cambiado; borra lo que la versión anterior
  instaló y la nueva no trae; nunca toca lo que no está en un manifiesto) → `instalar.ps1` de la carpeta.
  Nunca escribe en una carpeta con `.git`. Prueba: `scripts\prueba_instalador.py --paquete`. Publicar una
  etiqueta es publicar un Release: solo cuando el usuario lo pida.
- Instalar y desinstalar con ventana (14 nov 2026): `Instalar.bat` → `scripts\ventana_instalar.ps1` (WPF) que ejecuta
  `instalar.ps1` con `COMPANION_UI=1` y lee sus marcas (`::paso::`, `::progreso::`, `::omitido::`, `::error::`,
  `::fin::`, de `scripts\comun_instalacion.ps1` y `preparar_recursos.py`). `Desinstalar.bat` →
  `scripts\ventana_desinstalar.ps1` → `desinstalar.ps1`. Si añades un paso al instalador, márcalo y añádelo a
  `$definicion` de la ventana. Pruébalas con `scripts\prueba_instalador.py` (ventanas fuera de pantalla y capturas;
  `--real` instala de verdad en una copia de `data\`, `--desinstalar` en una copia temporal). Nunca abras la ventana
  ni ejecutes el desinstalador contra esta carpeta sin que el usuario lo pida.
- Servidor: `.venv\Scripts\python.exe -m companion` (puerto 8200, o el `PORT` de `.env`: si otro programa usa el 8200,
  `instalar.ps1` e `iniciar.ps1` eligen uno libre con `Puerto-Libre` de `scripts\comun_instalacion.ps1`). `iniciar.ps1`
  lleva un candado (mutex) para que dos arranques a la vez no lancen dos servidores. `iniciar.ps1 -SinVentana` lo arranca sin abrir la ventana.
- Pruebas rápidas (segundos, sin GPU ni servidores, datos en una carpeta temporal): `.venv\Scripts\python.exe -m
  unittest discover -s tests -t .`. Córrelas tras cada cambio; cubren los frenos de acciones y control.
- Pruebas sin micrófono: `scripts\prueba_componentes.py` y `scripts\prueba_ws.py` (ver README).
- Los `.ps1` llevan BOM UTF-8: Windows PowerShell 5.1 lee sin ella los acentos como ANSI. Mantenla al crearlos.
- Versiones fijas: el instalador usa `requirements.lock` y `voz\requirements.lock` (uv 0.13.8 con su SHA-256).
  Tras cambiar dependencias y probar, rehazlos con `scripts\fijar_versiones.ps1`.
- Registros: `iniciar.ps1` guarda las tres sesiones anteriores (`data\companion.1.log`…) y `voz_proc` la anterior
  de la voz (`voz.1.log`). Llevan lo que transcribe del usuario: no los muestres ni los subas.
- El panel de navegador de Claude bloquea el micrófono: ahí la interfaz se prueba escribiendo; el avatar,
  con `scripts\maniqui_vrm.py` (maniquí VRM 1.0 o `--v0`) y `window.companion.avatar` en la consola.
  Para el micrófono de verdad, `scripts\prueba_navegador.py` (Chrome oculto y en silencio, con un micrófono simulado).
- Modelos incluidos (decisión del usuario, 13 nov 2026): `avatar1` (`models\avatar1.vrm`, por defecto), `avatar2`
  y `avatar3` (la esfera), con nombres genéricos sin género. El modelo de Mika está retirado: no lo vuelvas a
  ofrecer. `models.LEGACY` traduce lo guardado antes (default/chica/chico/esfera). `mika.vrm`, `mika_base.vrm`,
  `chica.vrm` y `chico.vrm` siguen en disco sin usarse; no los borres sin que el usuario lo pida.
  No abras la ventana del companion sin avisar: el usuario suele estar jugando.
- Animación (`web/js/avatar.js`): muelles por hueso (`SPRING`), ruido suave en lo ocioso, dedos por separado
  (`ix` índice, `sp` abanico en `ARMS`). Para probar poses desde la consola: `await import('/js/avatar.js')` da
  `ARMS` editable en vivo; `avatar.sheet([...])` hace la hoja de contactos.

- **El usuario puede tener el companion abierto.** No reinicies ni apagues el servidor real (puerto 8200): pídele
  que lo haga él (`detener.ps1`, o `Companion.bat`, que lo reinicia solo si el código o `.env` son más nuevos).
  Nunca llames a `DELETE /api/memory` contra él: borra su conversación y sus recuerdos. Las pruebas van
  contra el servidor aislado de `scripts\_prueba.py` (puerto 8201, `data\prueba`); con `--local` usan Ollama.
- Memoria de vídeo (16 GB): voz completa ~1 GB (`voz\servidor.py`) + Whisper ~1,1 GB + escritorio ~2,5 GB. El modelo local tiene que
  caber en lo que queda: `gemma4:e4b-it-qat` (4,8 GB, el recomendado) con respaldo `gemma4:e2b-it-qat`.
  `gemma4:12b` (10,6 GB) cabe desde que la voz es la propia (58–93 tokens/s, 13 nov 2026) y está en el catálogo
  con `recommend: False` (con un juego abierto no cabe); el usuario lo tiene elegido. `llm.py` mide la velocidad
  de cada turno y baja de modelo si va lento (12B → E4B → E2B, `llm.local_models`).
- Estado del servidor de voz: `tts.stream_speech` espera a que cargue (503) y `voz_proc.recover` lo relanza si
  se cayó. Los temporizadores viven en el servidor (`session._start_timer`), no en la conexión.
- El servidor rechaza peticiones cuyo Host no sea `127.0.0.1`/`localhost` (`TrustedHostMiddleware`, contra DNS
  rebinding). Un cliente de pruebas tiene que usar uno de esos nombres.
- Compartir pantalla: `desktop\main.js` abre `picker.html` (pantallas y ventanas). En las pruebas se comparte
  la ventana `desktop\tarjeta-prueba.html`, nunca una ventana real.
  Sonido de lo compartido (15 nov 2026): interruptor en `picker.html`. La imagen se comparte sola y DESPUÉS
  `vision.addDesktopSound` pide aparte `audio: 'loopback'` (toda la PC, junto a una pantalla cuya imagen se para;
  `companion:share-audio-next` evita el selector). Si el sonido falla, la imagen sigue y se avisa con el motivo
  (juntos, un fallo del sonido tumbaba también la imagen). → `audio.startScreen` (trozos de 1 s, nunca mientras
  suena Mika) → `screen_audio` → `companion/screen_audio.py` (Whisper `transcribe_media` cada ~6 s, solo en GPU) →
  nota de texto ajeno en el último mensaje y freno de acciones. El texto oído no va al registro. Prueba:
  `scripts\prueba_sonido_pantalla.py` (sin cerebro; con dispositivos simulados, que también simulan el sonido de la
  PC: la captura real de Windows solo se ha probado en la PC del usuario).
- App de escritorio: `desktop\` (Electron descargado por `scripts\instalar_escritorio.ps1`). `scripts\prueba_escritorio.py`
  la prueba con `COMPANION_TEST=1`: ventanas fuera de pantalla, sin sonido, micrófono y cámara simulados.
  No envíes a ningún LLM una captura real de la pantalla del usuario en una prueba.
- Cuota: la capa gratuita de Gemini da 20 peticiones al día por modelo en `gemini-3.6-flash`; cada prueba de
  conversación gasta varias. `llm.py` hace el relevo de modelos (`GEMINI_FALLBACK`: Flash-Lite y luego
  `gemma-4-26b-a4b-it`, con la misma clave) y, al final, a Ollama. El trabajo de fondo (resúmenes y pasos del
  control) va con `background=True`: primero `BACKGROUND_MODEL` (`gemma-4-26b-a4b-it`), luego el relevo.
  Con la nube elegida (15 nov 2026, tarjeta de 6 GB del usuario): el trabajo de fondo nunca cae al modelo local, y
  el respaldo de la charla va a la tarjeta solo si cabe en lo libre (`llm._fallback_place`); si no, al procesador
  (`num_gpu: 0`), para no quitarle memoria a la voz completa. Se descarga al volver la nube y al arrancar en nube.
- Memoria: los 8 resúmenes más recientes van en el prompt de sistema; los antiguos que comparten dos palabras con
  el mensaje van en el último mensaje (`store.relevant_summaries`). El resumen también saca líneas «DATO:»
  (`session.split_summary`, que descarta lo que parece privado).

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
  voz y modelo local; `profile.LOCAL_MODELS` es el catálogo (12B, E4B, E2B, Qwen 3 1.7B, Gemma 3 1B; los dos
  últimos no ven imágenes; `TOP_RECOMMENDED` es el mayor que se llega a recomendar). El modelo local que elige el usuario es el que se carga (`llm.choose_local`): no lo cambies
  por otro «que quepa» sin avisar; solo `_too_slow` baja de modelo, y lo dice. Prueba: `scripts\prueba_recursos.py`.
- Dos motores de voz (`settings.voice_engine`): `completa` = `voz\servidor.py` · `ligera` = Piper en el procesador
  (`companion/tts_light.py`, modelos en `models\piper`, sin memoria de vídeo). Una voz nueva en `voices.json`
  necesita también su `light`.
- Acciones en la PC (`companion/actions.py`, decisión del usuario del 13 nov 2026): el modelo solo las PIDE con
  `[accion: nombre | dato]`; se ejecutan tras «Permitir» en la tarjeta, un «sí» del usuario o «permitir siempre».
  Catálogo cerrado y de poco riesgo: no añadas borrar, enviar, comprar, cambiar ajustes ni comandos libres sin
  que el usuario lo pida. Solo cuentan las de turnos con mensaje del usuario (nunca de la mirada en vivo, el
  saludo o un resultado). `actions.guess` reconoce órdenes claras del usuario. Prueba: `scripts\prueba_acciones.py`
  con `COMPANION_ACTIONS_DRY=1` (no abre nada). Nunca pruebes acciones reales en la PC del usuario sin pedírselo.
- Autorización (decisión del usuario, 13 nov 2026): su orden basta, sin tarjeta (`actions.config()["ask"]`
  apagado por defecto). Se mantienen: confirmar pasos delicados que la orden no pedía (`control.task_allows`) y
  tarjeta si la acción la eligió el modelo con pantalla o cámara compartidas. No quites esos dos frenos.
- Usar ventanas (`companion/control.py` las piezas, `companion/control_task.py` el bucle de pasos; acción
  `controlar`): EN SEGUNDO PLANO (decisión del usuario, 13 nov:
  puede estar jugando). Cada paso escala por `attempt`: accesibilidad → mensajes a la ventana (PostMessage) →
  teclado y ratón reales solo si el usuario no los usa (`real_input`: 4 s sin tocar nada, nada a pantalla
  completa). Nunca traigas la ventana al frente al empezar. La captura es PrintWindow (la propia ventana, nunca
  la pantalla con el juego). Windows ignora SetForegroundWindow desde segundo plano: `bring_front` lo resuelve y
  lo comprueba. Solo con E4B, modelos mayores o la nube (`llm.can_control`).
  `scripts\prueba_control_real.py --si` usa el teclado y ratón reales: solo cuando el usuario lo pida.
  Pruébalo SOLO con `scripts\prueba_control.py`: ventana propia fuera de pantalla, `COMPANION_CONTROL_ONLY`
  (solo esa ventana) y `COMPANION_CONTROL_NO_INPUT=1` (sin teclado ni ratón reales; una vez se probó sin él y
  trajo la ventana al frente, quitándole el foco al usuario). Gemma 4 E4B cae en el texto trampa de la ventana:
  la confirmación de pasos delicados es la red de seguridad, no la quites.
- Voz fiel al subtítulo (13 nov 2026): `Session._say_checked` genera la frase entera, la escucha con Whisper
  (`voicecheck`, compara por cómo suena: «Danny»=«Dani», «cinco»=«5») y la repite si falta una palabra.
  `voz\servidor.py`: NFE 32, ritmo 0,9, duración mínima para frases cortas. Para medir cambios de voz usa un
  servidor aparte en el puerto 8211 (`TTS_URL`), nunca el 8210 del usuario.
- Pronunciación (13 nov 2026): `pronounce.for_voice` reescribe solo el texto de la voz (inglés → escrito a la
  española según `voices\pronunciacion.json`; «qu»+e/i → «k»). Whisper no sirve para juzgar si algo suena a
  inglés (corrige hacia la marca): `calibrar_pronunciacion.py` solo comprueba que se entienda. Una vocal con
  tilde al principio («Ápel») hace que F5 se la coma: mejor sin tilde («Apel»).
- Voces nuevas a partir de grabaciones: `scripts\importar_voces.py <carpeta>` y luego `scripts\grabar_muestras.py`.
- Voces propias del usuario (14 nov 2026): Ajustes › Voz › «Añadir una voz propia» → `POST /api/voices/custom`
  (`companion/voice_import.py`, mismas piezas que `importar_voces.py`). Viven en `data\voces` (ids `p_…`, fuera de
  git: no las subas) y `voz\servidor.py` las busca allí (`VOICES_CUSTOM_DIR`, que pasa `voz_proc`). Su voz ligera
  sale del tono (`LIGHT_BASES`, medido). La transcripción usa el Whisper del oído con su candado.
- El nodo de voz se queda con memoria de vídeo por cada voz que llega a usar (medido el 12 nov 2026: de ~5 a
  9,5 GB tras probar 15 voces) y no la suelta hasta reiniciarse; con la tarjeta llena, cada frase pasa de 1 s a
  14 s. Por eso: las muestras ▶ son archivos pregrabados (`voices\previews`, sin pasar por el nodo), al nodo solo
  se copia la voz elegida (`profile.install_voice`) y las muestras de referencia duran unos 8 s. No pruebes
  muchas voces contra el nodo mientras el usuario conversa. Las frases de una sola cláusula muy corta
  («Hola,») el nodo las dice mal: evítalas en textos fijos.
- Voces: catálogo en `voices.json`; muestras en `voices\` (`<voz>_es.wav` + `.json` con `ref_text`), que el
  servidor de voz lee en cada petición. Origen y licencias en `voices\CREDITOS.md`.
- Personajes incluidos: `models.BUILTIN` (avatar1, avatar2, avatar3 = la esfera). La esfera no es un VRM:
  `web/js/orb.js`; una emoción o gesto nuevo hay que añadirlo también ahí.
- Memoria: `store.py` (messages, memories, summaries); los resúmenes los hace `Session._summarize` en ratos de calma.

## Reglas
- Personaje siempre adulto. Los temas +18 solo existen con el LLM local, y ahí van implícitos, sin interruptor
  (`prompt.adult_active`: cerebro local + `adult.enabled` en la ficha + usuario mayor de edad según el año de
  nacimiento de la bienvenida; decisión del usuario del 11 nov 2026).
  Nunca los actives para la nube (tampoco cuando la nube cae al modelo local por cuota) ni quites los límites
  de `ADULT_HARD_LIMITS`.
- Nunca subas ni muestres `.env`, modelos `.vrm` ni `data/`. Excepción (decisión del usuario, 15 nov 2026):
  `models/avatar1.vrm` y `avatar2.vrm` (muestras de VRoid, licencia con redistribución) sí van en git, para que
  el instalador los traiga. `mika.vrm`, `chica.vrm`, `chico.vrm` y `mika_base.vrm` siguen fuera.
- Las poses de `web/js/avatar.js` están en convención VRM 1.0; los VRM 0.x se corrigen invirtiendo X y Z al aplicar.
- Etiquetas del LLM: `[emo:…]`, `[gesto:…]`, `[recordar: …]`, `[accion: …]`. Si añades una emoción o gesto, hazlo en
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
