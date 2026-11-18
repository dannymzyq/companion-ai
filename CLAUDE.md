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
  etiqueta es publicar un Release: solo cuando el usuario lo pida. Si el título de la versión en `CHANGELOG.md`
  dice «(solo Windows)», el Release no crea la app para Mac.
- PyTorch de la voz completa (15 nov 2026): `instalar.ps1` lee en `nvidia-smi` el CUDA que admite el driver; con 13
  o más pone `+cu130` (las RTX 50 lo necesitan), con menos `+cu126` (con cu130, un driver anterior al 580 daba
  `cudaErrorNotSupported` en la laptop de la RTX 3050). `voz\servidor.py` no carga en el procesador si hay tarjeta
  NVIDIA que PyTorch no ve: da error y `tts.stream_speech` dice la frase con la voz ligera.
- App para Mac con Apple Silicon (15 nov 2026, decisión del usuario: «básico primero», sin firma de Apple):
  `scripts\crear_app_mac.sh` (solo en macOS) crea `dist\Companion-X.Y.Z-mac.dmg`: Electron darwin-arm64 con
  `desktop\` en `Resources/app` (arranca por `desktop\mac.js`) y lo de git + `manifest.json` en `Resources/programa`.
  `mac.js` copia solo lo cambiado a `~/Library/Application Support/Companion` (o `COMPANION_HOME`), ejecuta
  `instalar.sh` con `COMPANION_UI=1` en `instalando.html` (mismas marcas que `instalar.ps1`), arranca
  `iniciar.sh --sin-ventana` y carga `main.js` (`COMPANION_BOOTED=1`: el candado es suyo). Versiones fijas:
  `requirements-mac.lock` y `voz\requirements-mac.lock` (macOS 14, de los locks de Windows con `fijar_versiones.ps1`).
  En el Mac: memoria unificada (`llm._mac_memory`: dos tercios de la RAM para la GPU), oído en la GPU (CTranslate2
  `device="mps"`, 0,7 s por 4 s de habla; si falla, procesador con 10 hilos), voz completa en MPS (16 nov 2026:
  `voz_proc` pone `VOZ_NFE=16`, `VOZ_REF_CORTA=1` y `VOZ_LARGA=90`; `servidor.py` pasa F5 a float16 en MPS y usa el
  tramo `short` del .json de la muestra, de `scripts\recortar_muestras.py` / `voice_import.add_short`; primer audio
  ~3 s, antes 33 s de media; en la PC la muestra corta no gana nada) y sin la comprobación con Whisper (solo se hace
  con el oído en CUDA; sin comprobación, `Session._say` manda el audio según llega),
  acciones con `open` y `osascript`. No hay `controlar`, `multimedia` ni sonido de lo compartido (`CAN_AUDIO`).
  Cerebro local en el Mac (15 nov 2026, petición del usuario): Gemma 4 MLX de Ollama (`profile.MAC_MODELS`, RUNNER
  mlx en `ollama ps`); `config.for_this_pc` traduce los nombres de PC (`MLX_EQUIV`) en `.env` y en lo guardado. En
  MLX el E4B ocupa más que el 12B: el catálogo va por capacidad, no por memoria. Medidos con
  `scripts\medir_modelos_locales.py` en la MacBook del usuario (M5 Pro, 24 GB); `scripts\prueba_mlx.py` prueba el
  companion aislado con ellos (solo en el Mac).
  Se prueba en `.github\workflows\mac.yml` (macos-15; `release.yml` lo llama y adjunta el .dmg al Release). Nadie
  lo ha probado aún en un Mac con micrófono: el usuario lo probará.
  Pruebas de Electron en el Mac (17 nov 2026): `_prueba.ELECTRON` usa `desktop/electron/Electron.app` (Electron
  darwin-arm64 de la misma versión, o `COMPANION_ELECTRON`) y `_prueba.cerrar` cierra los procesos en los dos
  sistemas. macOS devuelve a la pantalla las ventanas creadas en x=-4000 y deja a 2 cuadros por segundo las que
  da por tapadas: con `COMPANION_TEST=1` en el Mac, main.js y mac.js usan `enableLargerThanScreen` (la flotante,
  sin marco), `showInactive` + `setPosition`, opacidad 0 y sin clics para las que tienen marco, y apagan el
  frenado de ventanas tapadas. `crear_app_mac.sh` copia todos los .js y .html de `desktop/`.
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
  de la voz (`voz.1.log`). Desde la 0.7.0 no llevan lo que se dice (`config.shown`: solo cuántos caracteres;
  `LOG_TEXT=1` en `.env` lo vuelve a escribir). Aun así, no los muestres ni los subas.
  La ventana (17 nov 2026) escribe `data\ventana.log` (anterior: `ventana.1.log`; en pruebas `data\prueba`): errores
  y avisos de la consola de la página, «no responde» y caídas de la página o de la tarjeta gráfica. El bucle de
  dibujo (`tick` en main.js) nunca se para por un error (`tickPart`), las cargas de modelo van de una en una
  (`loadSeq`, 90 s como mucho) y tras perder el contexto WebGL se recarga el modelo (`onContextRestored`).
- El panel de navegador de Claude bloquea el micrófono: ahí la interfaz se prueba escribiendo; el avatar,
  con `scripts\maniqui_vrm.py` (maniquí VRM 1.0 o `--v0`) y `window.companion.avatar` en la consola.
  Para el micrófono de verdad, `scripts\prueba_navegador.py` (Chrome oculto y en silencio, con un micrófono simulado).
- Modelos incluidos (decisión del usuario, 13 nov 2026): `avatar1` (`models\avatar1.vrm`, por defecto), `avatar2`
  y `avatar3` (la esfera), con nombres genéricos sin género. El modelo de Mika está retirado: no lo vuelvas a
  ofrecer. `models.LEGACY` traduce lo guardado antes (default/chica/chico/esfera). `mika.vrm`, `mika_base.vrm`,
  `chica.vrm` y `chico.vrm` siguen en disco sin usarse; no los borres sin que el usuario lo pida.
  No abras la ventana del companion sin avisar: el usuario suele estar jugando.
- Ventana y flotante (16 nov 2026): `desktop/main.js` tiene UNA página (`WebContentsView`) y al cambiar de modo la
  pasa de un `BaseWindow` a otro sin recargarla (`open`), y avisa a la página con `companion:mode`
  (`setMode` en `web/js/main.js`: `floating` cambia en caliente). Así no se corta la voz ni la conversación. No
  vuelvas a abrir una página nueva por modo. Cámara libre (`OrbitControls` sin límites de ángulo, con
  desplazamiento y zoom hacia el cursor); flotando: izquierdo mueve la ventana, derecho gira, central desplaza,
  Ctrl + rueda acerca (`avatar.zoom`), doble clic `avatar.resetView`. «Desvanecer los pies al flotar»
  (`companion.float.fade` en localStorage; apagado = `body.no-fade` + `avatar.setFullBody`, cuerpo entero).
  Prueba: `scripts\prueba_flotante.py` (sin cerebro: suena un tono y cambia de modo dos veces).
- Mascota de escritorio (16 nov 2026, solo flotando; Ajustes › «Escritorio (modo flotante)», `companion.pet` en
  localStorage): `desktop/pet.js` mueve la ventana (gravedad hasta la barra de tareas, paseos, sentarse sobre la
  ventana activa y seguirla, ir al lado de la ventana de una acción «controlar» y volver) y manda a la página
  `pet:event` (cursor, activity, workmode, gesture); la página pone las animaciones (`avatar.setActivity`:
  walk | carried | fall | sit | work, `ACTIVITIES` en avatar.js y su versión en orb.js; gestos internos `_toque` y
  `_aterrizar`) y le manda los puntos del personaje (`avatar.anchors`: pies, asiento, cabeza), el estado y las
  acciones. La ventana activa la da `GET /api/desktop/scene` (`companion/desktop_scene.py`: solo posición y estado,
  nunca título ni contenido; el sondeo no va al registro). `control_start`/`control_step` llevan `window` (dónde
  está) y `kind`/`point` del paso. Con algo a pantalla completa no pasea ni salta. Mientras trabaja, el modelo no
  recibe clics (los reales del control lo atravesarían). Mover la ventana flotante SIEMPRE con `setBounds` y el
  tamaño guardado: con escalado 150 %, `setPosition` o `getBounds` la hacen crecer en cada llamada (medido).
  Prueba: `scripts\prueba_mascota.py` (pantalla y ventanas inventadas en x=-4000, nunca las reales; hoja de
  poses en `data\prueba\mascota_poses.png`). Poses con cada modelo, incluidos los VRM propios del usuario (se copian
  solo a `data\prueba`): `scripts\hoja_modelos.py`. Sentada va DE COSTADO (`opts.side`) y con los muslos algo caídos:
  de frente y con muslos horizontales, faldas y vestidos atravesaban las piernas (16 nov 2026). Andar: `WALK_HZ`
  (avatar.js y pet.js, el mismo) y la ventana avanza según el largo de la pierna, para que no patine.
  Transparencia al flotar (`alpha` en `companion.pet`, `--pet-opacity`): con `.hover` (ratón encima o agarrándola)
  vuelve a opaca.
  Fluidez (17 nov 2026): en el proceso principal de Electron en Windows, `setInterval(16)` da un cuadro cada 31 ms
  (medido; el mínimo es 15,6 ms). Mientras algo se mueve, pet.js pide cuadros (`frames`) y la página llama a
  `desktop.pet.frame()` en cada requestAnimationFrame (`pageFrame` → `frame`); el temporizador de 8 ms es solo
  respaldo. Todo movimiento nuevo de la ventana va por `animate` o por `frame` con dt, nunca con su propio
  temporizador. Sentada, la escena se mira cada 150 ms y `followSeat` la sigue. `moving` → `body.pet-moving`
  (barra y subtítulos escondidos; `#asks` y `#control` nunca). `insets` → `--pet-cut-*` (lo que queda fuera del área
  de trabajo: la barra sube). Con los pies por debajo de la ventana, `A().feet` es el borde de abajo. `fitBar` (main.js)
  encoge la barra con `zoom` para que quepa en la ventana (mínimo 220 px de ancho).
  `prueba_mascota.py` mide los fps (`lastMoveFps`) y la barra con zoom (8b).
- Animación (`web/js/avatar.js`): muelles por hueso (`SPRING`), ruido suave en lo ocioso, dedos por separado
  (`ix` índice, `sp` abanico en `ARMS`). Para probar poses desde la consola: `await import('/js/avatar.js')` da
  `ARMS` editable en vivo; `avatar.sheet([...])` hace la hoja de contactos.
- Animaciones grabadas (17 nov 2026, petición del usuario: «como ZZZ»): `web/anim/clips.json` (Quaternius UAL 1 y 2,
  CC0, `web/anim/CREDITOS.md`) hecho con `scripts/convertir_animaciones.py` (giros respecto a la pose en T =
  espacio normalizado de three-vrm, en Euler XYZ). `web/js/clips.js` las muestrea; `applyLayer` las pone con
  máscara por zonas ANTES de lo procedural (reposo/hablar en `_buildPose`, andar, agacharse/arrodillarse en
  `pointerWork`, caer, `_aterrizar`, enfado = brazos cruzados). Solo clips CC0 o equivalentes: Mixamo no deja
  repartir sus archivos y Bandai Namco es no comercial. En la hoja: `{clip: 'walk', clipT}` muestra un clip y
  `{clips: false}` lo de antes; `avatar.clipOn = false` las apaga en vivo. Flotando, `_inertia` mueve las puntas
  de los muelles del VRM lo contrario a la ventana (`_currentTail`/`_prevTail` de three-vrm). `anchors().step`
  da el largo del paso a pet.js. Probado con los 3 incluidos y los 4 VRM del usuario (copias en `data\prueba`).
  Estilos (17 nov 2026, «aplica todo lo que se pueda»): `walk_<estilo>`/`idle_<estilo>` de 100STYLE (CC BY 4.0: hay
  que citar «The 100STYLE Dataset - Ian Mason»; Zenodo 8127870), con `--estilos` y `scripts/anim_bvh.py` (bucle
  recortado de cada toma, sin recorrido ni giro, cuello −15°). `EMO_STYLE`/`EMO_AMP`, `_styleNow` (emoción o
  personalidad), `styleW` (fundido), `_styled` (marcha a la par por `cycles`), `gait()` → `anchors().hz/speed` →
  pet.js. Pies: `_legIK` al final de `_applyPose` (clavados de pie con pasito, solo altura al andar; `ikOn`).
  Descartados por licencia: Bandai Namco, LAFAN1, ai4anim-webgpu (no comerciales).
- Cara ARKit (17 nov 2026, «lo añades»): `face.addParts` busca primero las 52 formas de ARKit (`ARKIT_NEED`, sin
  importar mayúsculas ni prefijos) y arma cada parte (`brw…`, `eye…`, `mth…`) con varias (`ARKIT_PARTS`), más partes
  propias `ak…` (media sonrisa, una ceja, labios apretados, mejillas, nariz, `LIP_PARTS` de los labios al hablar:
  `_face` las mueve con `mouth.oh/ou` y `lipClose`). `parts.kind` = 'arkit' | 'vroid'. Probado con Test-Chan (CC0,
  solo en `data\prueba`). Ningún VRM del usuario ni los incluidos tienen ARKit.
- Dedos y cara (17 nov 2026, «utiliza los repositorios… que se adapten mejor»): `HANDS`/`hs`/`p.hand` (cada dedo,
  `CASCADE`, `FINGER_RATE`, oposición del pulgar `THUMB`: en Y negativo, medido con primeros planos); gestos
  `pulgar` y `paz` (también en prompt.py y orb.js). `web/js/face.js`: partes de VRoid como expresiones `p_…`
  (`addParts`, solo si hay cejas, ojos y boca) + `EMO_PARTS` + `Micro` (ideas de TalkingHead, MIT; ninguno de los
  VRM del usuario tiene ARKit, así que Audio2Face y las caras de TalkingHead no sirven). `web/js/lipsync.js` adapta
  wawa-lipsync (MIT: el aviso va en `web/js/CREDITOS.md`). Primeros planos en la consola: proyectar un hueso dentro de
  `renderer.render` durante `sheet` y recortar. Triste: `idle_triste` con `spine` 0,4 y `head` 0,25.
- Pasatiempos y rubor (17 nov 2026): `HOBBIES`/`BORED_AFTER`/`wake`/`endHobby` en avatar.js (gestos `_…` largos;
  clip `spell` añadido a `WANTED`), interruptor «Se entretiene sola» (`companion.hobby`). Las pruebas que miran
  posiciones ponen `avatar.hobbyOn = false` (prueba_mascota). Rubor: `effects.attachBlush` (planos hijos de la
  cabeza, con profundidad) y `_onSkin` (rayo a la piel); la esfera sigue con los carteles.
- Sueño y peticiones (17 nov 2026): `SLEEP_AFTER`, `sleepNow`/`_sleepPose`. Lo normal es `lean` (petición del
  usuario: «que se recueste en la esquina… con una tablet o un celular hasta que se duerme»): `_leanPose` + `LEAN`
  (editable en vivo) + `web/js/props.js` (`Device`, `_placeDevice` después de `vrm.update`). Flotando espera a
  `restAt`: `onSleep(on, mode)` → `desktop.pet.rest` → pet.js `rest`/`walkTo` (va a la esquina aunque esté «dormida»)
  → evento `rest`. `body.sleeping` quita el degradado de pies. `nod` (seiza) y `nap` (`lay_up` al revés) quedan para
  la ventana. Postura (imagen de referencia del usuario, apoyada sobre un codo): base `lay_up` en `LEAN.base` 0,28,
  reflejada con `mirrorPose` para `side < 0` (la animación no es simétrica), `LEAN.roll` hacia el costado de apoyo, y
  `_leanIK` con `_ikChain` (IK de dos huesos con polo): manos a la pantalla delante del pecho (dormida, al pecho), codo
  de apoyo hacia el suelo detrás, pie de la pierna alta delante de la rodilla de la tendida (`LEAN.ik`). La tendida es
  la que da a la cámara (`ik.leanDown`), con la rodilla fijada algo hacia delante (si no, se doblaba al revés).
  Variantes (`LEAN.variants`: codo, rodillas, tumbada; `sl.variant`, al azar sin repetir; `float: false` = no en la
  ventana flotante): base y base dormida de `lay_up`, piernas (`extend`/`raise`/`knees`), puntos de pantalla y de
  descanso (`screen`/`rest`, desde chest, head o knees) y cabeza; `_leanIK` y `_placeDevice` (`_restPoint`) las usan.
  `hipsY`/`headY` se miden en la pose en T al cargar (medidas con el modelo anterior dormido salían mal).
  Recostada: `_legIK` con `ik.lean` (pierna izquierda tendida a ras de suelo hacia delante y algo hacia
  su lado, `LEAN.legSide`, con el pie siguiendo a la pierna; antes seguía a la animación y en algunos modelos quedaba
  cruzada bajo la otra; la derecha pisando). `LEAN.legReach` 0,75: la rodilla algo levantada (petición del usuario).
  Al dormirse se cierra el chat (`onSleep` → `showKeyboard(false)`); `pet-moving` no esconde `#text-form`.
  `LEAN.lift` (cadera a ~10 cm) y, flotando, `LEAN.rise` (todo el cuerpo algo arriba, que la pierna no se corte).
  Ropa: `_legColliders` (cápsulas en muslos y espinillas + suelo, en los huesos de verdad; `sb._isSortedJointsDirty`).
  Prueba: `prueba_mascota.py` 8d (captura en `data\prueba\mascota_recostada.png`). `onSleep` →
  `pet.state('sleep')`. Gestos públicos en `GESTURES` (alias de
  los `_…`) + `dormir`; en prompt.py `GESTURES` y la frase «Tienes cuerpo en la pantalla…»; `companion/play.py`
  (`guess`: imperativo, o «puedes/quiero que…» + infinitivo o subjuntivo; negaciones fuera) y `Session._speak` lo
  añade a la primera frase. Solo mueve al personaje: no es una acción en la PC.

- **El usuario puede tener el companion abierto.** No reinicies ni apagues el servidor real (puerto 8200): pídele
  que lo haga él (`detener.ps1`, o `Companion.bat`, que lo reinicia solo si el código o `.env` son más nuevos).
  Nunca llames a `DELETE /api/memory` contra él: borra su conversación y sus recuerdos. Las pruebas van
  contra el servidor aislado de `scripts\_prueba.py` (puerto 8201, `data\prueba`); con `--local` usan Ollama.
- Tarjetas pequeñas (18 nov 2026, «optimizar para 4-6 GB»), medido en esta PC: voz completa 1,03 GB en reposo y
  1,12 de pico (F5 ya va en float16 en CUDA); Whisper en GPU int8_float16: turbo 1,29 GB / 1,4 % de palabras
  perdidas, small 0,53 / 3-5 %, base 0,14 / 6-9 % (small en el procesador: 1,8 s por frase). `profile.ear_model`:
  small por debajo de `SMALL_EAR_BELOW` (6,5 GB) si está en `models\whisper\small` (lo trae `preparar_recursos.py
  --oido`, no en el Mac); `STT_MODEL` en `.env` manda. `EAR_MODELS`/`ear_gb()` en las cuentas. Avatar: los
  incluidos traen 8 texturas de 4096 px (~430 MB de vídeo); `avatar.setQuality` + `_shrinkTextures` (createImageBitmap
  al cargar) y `QUALITY`/`qualityNow` en main.js (≥7,8 GB alta, ≥5,5 media 2048 px, si no baja 1024 px; sin dato de
  tarjeta, media; `companion.quality` en localStorage, Ajustes › «Calidad del personaje»). Nube saturada: `Overloaded`
  (5xx, «high demand», sin respuesta) y `CLOUD_FIRST_S` 4,5 s al primer texto si quedan otros modelos → `_busy` (al
  final `CLOUD_BUSY_S` 10 min); la mirada en vivo calla si está saturado; `stt_cloud._busy` 5 min. Medido el 18 nov:
  gemini-3.6-flash daba 503 tras 8-49 s y Flash-Lite contestaba en 1 s. El plan Google AI Pro no sube los límites de
  la API (solo AI Studio). Herramientas para medir: no se guardaron en scripts (eran de una sesión).
  Laptop del usuario (RTX 3050 4 GB, i5-12500H, 16 GB; probada el 18 nov 2026 por Remote Control con la 0.8.3): F5
  tardaba 5,4–6,6 s por frase (GPU al 100 %); con 16 pasos + muestra corta + VOZ_LARGA 90, ~1,9 s y más rápido que
  tiempo real. `voz/servidor.py _medir_tarjeta`: tras calentar mide una frase corta; si pasa de `LENTA_S` (2,5 s,
  `VOZ_LENTA_S`) entra en modo rápido (`/health` → `fast`, `phrase_s`), salvo VOZ_NFE/VOZ_REF_CORTA fijados.
  `voz_proc.fast()` → `Session._checks_voice` no comprueba con Whisper en modo rápido. Todo junto ahí (turbo + voz
  + avatar + Brave): ~2,1 GB de 4; con la 0.8.4 (small), 1,3 GB. `STT_MODEL=large-v3-turbo` (el de los .env
  antiguos) cuenta como automático. La voz da `/health` tts=f5 solo con `estado["listo"]` (tras medir): con la 0.8.4
  la primera respuesta se pidió durante la medida y el primer audio llegó a los 30 s. Con la 0.8.5 allí: primera
  frase ~1,3 s y primer audio ~4,1 s (voz ~2,9 s), pero con pausas a mitad de respuesta; `Session._speak` en modo
  rápido junta frases de menos de `FAST_MERGE` (60) hasta `FAST_MERGE_MAX` (90) letras (`pending` guarda la que no
  cabe). Pruebas: `tests/test_voz_juntar.py`.
- Memoria de vídeo (16 GB): voz completa ~1 GB (`voz\servidor.py`) + Whisper ~1,3 GB + escritorio ~2,5 GB. El modelo local tiene que
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
  Auditoría (16 nov 2026, 0.7.0): `state.save` escribe en un temporal y lo cambia de una vez (con copia
  `settings.json.bak`, que `load` usa si el bueno está roto). Las claves (`cloud.key`, `ear.groq_key`) van cifradas
  con `companion/secret.py`: DPAPI en Windows (`dpapi:…`), Llavero en el Mac (`llavero:<cuenta>`, una entrada por
  carpeta de datos; las pruebas ponen `COMPANION_KEYCHAIN=0`). Para leer la clave en un script, `secret.reveal`
  sobre el json, nunca el json a mano. `state.protect_keys` cifra al arrancar las guardadas en claro.
  `TIMEZONE` vacío (o el `America/Lima` que copiaba el instalador) = la hora del sistema.
  Aviso de versión nueva: `companion/update.py` (`GET /api/update`, Releases de GitHub cada 12 h, solo etiquetas
  vX.Y.Z con el instalador de ese sistema; `UPDATE_CHECK=0` lo apaga, y las pruebas rápidas lo apagan).
  Textos en el Mac: `web/js/platform.js` adapta «esta PC», «tarjeta gráfica», «memoria de vídeo»… al Mac en toda
  la página (también lo que se escribe después); un texto nuevo de la interfaz no necesita nada más.
  Nube lenta (como en iOS): si un modelo tarda más de 8 s en dar el primer texto dos turnos seguidos, se empieza
  por el siguiente del relevo 30 min (`llm._note_wait`, `_by_speed`). En el Mac, un turno local es lento si cae por
  debajo del 45 % de lo mejor que ha ido ese modelo (`llm.slow_limit`); en la PC sigue `SLOW_TPS`.
  `abrir_carpeta` rechaza rutas de red (`\\servidor`, `//`, `smb://`, unidades de red) ANTES de comprobar si
  existen: comprobarlo ya conectaba con el servidor y Windows le daba una huella de la contraseña.
- El personaje se llama como la voz elegida (`profile.character`): `personas/mika.json` es la ficha común y su
  `name` solo sirve para el archivo del modelo por defecto. Voces y personajes no llevan etiquetas de género en
  la interfaz (decisión del usuario, 12 nov 2026); `speaks` en `voices.json` solo decide cómo habla de sí.
  Nunca llames a `POST /api/setup/reset` contra el servidor real: con `data` borra todo lo del usuario.
- Cambio de personalidad (17 nov 2026, «se queda pegada»): la interfaz enseña `#personality-busy` («Ajustando…»)
  y bloquea la sección mientras dura (`adjusting` en personality.js, 30 s como mucho); el servidor, con el cerebro
  local y la sesión libre, hace que Ollama lea ya el prompt nuevo (`Session.prime` → `llm.prime_local`, un token,
  mismo `num_ctx`; `_personality_ready` espera 20 s como mucho). Pruebas: `tests/test_personalidad.py` (Reajuste).
- Prompt «más persona» (17 nov 2026, petición del usuario): `personality_block` lleva opiniones (`opinions`) y
  reacciones (`reactions`) de la personalidad, «Antes de responder, lee el mensaje» (tono, intención, confianza) y
  «Tienes criterio» (permiso para discrepar, nunca condescendiente); «Cómo hablas» prohíbe frases de plantilla, la
  pregunta forzada al final y abusar de las muletillas; «Memoria viva» con ejemplos. Medido con gemma4 E4B contra el
  prompt anterior (casos fijos: tierra plana, día fatal, piropo, prisa, hambre, dejar el trabajo).
- Personalidades (16 nov 2026, Ajustes › Personalidad): `companion/personality.py` + `personas/personalidades.json`;
  `personality.apply` pone sobre la ficha rasgos, estilo, gustos y ejemplos (nunca nombre, edad, voz, límites ni
  +18) y `prompt.personality_block` los lleva al prompt de sistema (fijo mientras no se cambie). Las propias (`c_…`)
  en `settings.json`; personalizar una incluida la copia. Textos de la interfaz sin género (emociones como
  sustantivos: `EMOTION_NAMES` en `web/js/personality.js`). Ánimo entre turnos: `companion/mood.py` (va en
  `turn_context`, nunca en el prompt de sistema). Pruebas: `tests/test_personalidad.py`.
- Recursos: `profile.resources` reparte la memoria de vídeo (escritorio 2 GB + oído 1,1 GB + voz) y recomienda
  voz y modelo local; `profile.LOCAL_MODELS` es el catálogo (12B, E4B, E2B, Qwen 3 1.7B, Gemma 3 1B; los dos
  últimos no ven imágenes; `TOP_RECOMMENDED` es el mayor que se llega a recomendar). El modelo local que elige el usuario es el que se carga (`llm.choose_local`): no lo cambies
  por otro «que quepa» sin avisar; solo `_too_slow` baja de modelo, y lo dice. Prueba: `scripts\prueba_recursos.py`.
- Dos motores de voz (`settings.voice_engine`): `completa` = `voz\servidor.py` · `ligera` = Piper en el procesador
  (`companion/tts_light.py`, modelos en `models\piper`, sin memoria de vídeo). Una voz nueva en `voices.json`
  necesita también su `light`.
  Cambio automático (15 nov 2026, `voice_auto`, encendido por defecto): `settings.voice_engine` es el motor que
  suena; el elegido es `profile.voice_engine()`. `profile.engine_now` pasa a la ligera si la completa no cabe junto
  al modelo local (cuenta por el total de la tarjeta), y `llm._free_voice` lo hace antes de bajar de modelo cuando
  el local va lento por memoria (`profile._squeezed`; se borra al cambiar de cerebro o de modelo). El instalador
  pone las dos voces desde 4 GB (`profile.measured_others`: lo que ocupan los demás programas se MIDE con
  nvidia-smi, restando lo nuestro; la estimación fija de 2 GB hacía que en la laptop de 4 GB del usuario, una RTX
  3050, la completa nunca pareciera caber, 15 nov 2026). Salida de audio y volumen: `audio.js` (`setSinkId`; `companion.output` y
  `companion.volume` en localStorage; Electron permite `speaker-selection`).
- Ajustes (15 nov 2026): secciones `<details name="ajustes">` (una abierta a la vez) con resumen en la cabecera
  (`sum-…`) y una «i» por opción (`.info[data-tip]` abre su `.tip`; dentro de un interruptor no lo cambia). El
  botón de flotar está en la barra de abajo, junto a compartir pantalla.
- Acciones en la PC (`companion/actions.py`, decisión del usuario del 13 nov 2026): el modelo solo las PIDE con
  `[accion: nombre | dato]`; se ejecutan tras «Permitir» en la tarjeta, un «sí» del usuario o «permitir siempre».
  Catálogo cerrado y de poco riesgo: no añadas borrar, enviar, comprar, cambiar ajustes ni comandos libres sin
  que el usuario lo pida. Solo cuentan las de turnos con mensaje del usuario (nunca de la mirada en vivo, el
  saludo o un resultado). `actions.guess` reconoce órdenes claras del usuario. Prueba: `scripts\prueba_acciones.py`
  con `COMPANION_ACTIONS_DRY=1` (no abre nada). Nunca pruebes acciones reales en la PC del usuario sin pedírselo.
- Autorización (decisión del usuario, 13 nov 2026): su orden basta, sin tarjeta (`actions.config()["ask"]`
  apagado por defecto). Se mantienen: confirmar pasos delicados que la orden no pedía (`control.task_allows`) y
  tarjeta si la acción la eligió el modelo con pantalla o cámara compartidas. No quites esos dos frenos.
  Excepciones del usuario (16 nov 2026): «controlar» también admite «permitir siempre», y «Acceso total»
  (`actions.config()["full"]`, opcional, apagado por defecto) quita todas las tarjetas, también la segunda. Aun con
  acceso total se mantienen el catálogo cerrado, que solo cuenten turnos con mensaje suyo y la confirmación de pasos
  delicados (`task_allows`).
- Toques, miradas y mano de puntero (16 nov 2026): `avatar.react(zone)` por partes del cuerpo (`zoneAt`, con los
  huesos proyectados; en la ventana normal `pickAt` lee el píxel en el siguiente cuadro) y sube de tono al repetir
  (nivel 1-3, `setTemper` con la personalidad). `_watchView` detecta cara/pecho/piernas de cerca, desde abajo, por
  la espalda y giros. Ambos pueden mandar `touch`/`look` (solo un tipo fijo, nunca texto) y `Session._poke` lo
  comenta con `prompt.POKE` como mucho cada `POKE_GAP` (60 s con la nube). Flotando, cada paso de «controlar» con
  punto lleva la punta del índice derecho (`anchors().hand`) a él con postura según su altura (`pointerWork`:
  stand/crouch/kneel/reach). Chat flotante: `#text-form` como cápsula. Pruebas: `tests/test_toques.py` y
  `scripts/prueba_mascota.py` (7b, 9b).
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
- Arranque y cierre (15 nov 2026, `companion/lifecycle.py`): `iniciar.ps1` arranca el servidor y abre Electron SIN
  esperar (`COMPANION_SERVER_PID`); `desktop\main.js` enseña `cargando.html` hasta que responde y registra su pid
  (`POST /api/owner`: si muere, el servidor se apaga solo). La interfaz enseña `web/js/loading.js` con
  `GET /api/loading` al abrir y cuando cambia el oído, la voz o el cerebro. `detener.ps1` hace `POST /api/shutdown`,
  luego cierra el árbol (solo procesos de esta carpeta con «-m companion» o «servidor:app») y Ollama si está en
  `data\ollama.pid`. El apagado solo descarga los modelos que cargó ESE proceso (`llm._ours`): uno de prueba no
  debe tocar el Ollama del usuario. Pruebas: `scripts\prueba_carga.py`, que usa `detener.ps1 -PuertoPrueba 8201
  -SoloServidor`. PowerShell no distingue mayúsculas: un parámetro nunca puede llamarse como una variable del
  script (con `-Puerto` y `$puerto`, la prueba apagó el companion real del usuario, 15 nov 2026).
- Solo nube (15 nov 2026, `profile.cloud_only`, Ajustes › Cerebro): cerebro, oído (`ear.engine` «nube»,
  `stt_cloud.py`: Groq con `ear.groq_key` y luego Gemini `EAR_GEMINI_MODELS` con la clave del cerebro; si fallan,
  `Transcriber.local_model()` en CPU) y voz (motor «nube», `tts_cloud.py` con edge-tts; sin red cae a la ligera). Al
  encenderlo guarda `before_cloud_only` y al apagarlo lo devuelve; elegir algo local lo apaga (`profile.apply`).
  Quita el respaldo local del cerebro (`settings.local_fallback`). La clave de Groq nunca se devuelve a la interfaz.
  `scripts\prueba_nube.py` mide RAM, procesador y vídeo (`--turnos 0` no gasta cuota). La clave de Groq no se ha
  probado de verdad (no había una): solo con peticiones simuladas en `tests\test_nube.py`.
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
- No arranques el servidor con `STT_MODEL` distinto de los instalados (`models\whisper`: large-v3-turbo y small):
  faster-whisper descarga cualquier otro solo de Hugging Face.
- La interfaz se sirve con `Cache-Control: no-cache` y Electron vacía su caché al arrancar. Si una prueba se
  comporta como el código anterior, sospecha primero de JavaScript en caché (pasó el 11 nov 2026).
- Micrófono y cámara reales: `scripts\prueba_dispositivos.py` (Electron oculto con `COMPANION_TEST_REAL_MEDIA=1`,
  sin cerebro: nada llega a un modelo). Úsala solo cuando el usuario pida probar su dispositivo físico. La Brio
  deja mudo su micrófono al cerrar el vídeo: no cierres y reabras la cámara sin `audio.heal()`.
- Ollama tiene una sola cola (`-np 1`) y no aborta una petición hasta leer sus imágenes: toda petición en
  segundo plano (la mirada en vivo) tiene que ser ligera. No midas modelos en Ollama mientras el usuario
  conversa en local: le frena los turnos.
