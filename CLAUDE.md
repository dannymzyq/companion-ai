# Companion – instrucciones para Claude Code

Companion de voz con avatar 3D (VRM o la esfera). PC del usuario: RTX 5070 Ti 16 GB, Windows 11. Laptop de pruebas:
RTX 3050 4 GB. MacBook M5 Pro 24 GB (sesión «Mac — Companion para Mac», que lleva las subsesiones de iOS y Android).

- **Mapa y ediciones:** `README.md`. Guías: `documentacion/` (instalacion, uso, personaje, desarrollo).
- **Detalle técnico por tema, con fechas y mediciones:** `documentacion/notas-tecnicas.md`. Léelo antes de tocar una
  pieza (voz, mascota, animación, control de ventanas, instalador, Mac, nube, en vivo…) y actualiza su apartado después.
- Esta sesión de la PC es la principal: tras cada cambio, manda a la sesión Mac lo que cambió para iOS y Android; las
  versiones salen con el mismo número en todas las ediciones.

## Estructura
- `companion/` servidor Python (FastAPI) · `web/` interfaz (ES modules sin compilar; no hay Node en esta PC) ·
  `desktop/` Electron · `voz/` servidor F5-TTS (8210) · `personas/`, `voices/`, `voices.json`, `models/`.
- `rust-live/` edición ligera en Rust (solo modo en vivo, `.exe` portable) · `movil/` iOS y Android (`movil/core` JS).
  El instalador de PC y el `.dmg` NO empaquetan `movil/`, `rust-live/` ni `docs/`.
- `scripts/instalacion/` · `scripts/pruebas/` (`_prueba.py` y `prueba_*.py`) · `scripts/herramientas/` · `tests/`.
- Raíz: solo lanzadores (`Companion.bat`, `iniciar/detener/instalar/desinstalar.ps1|.sh`, `Instalar.bat`,
  `Desinstalar.bat`), que los accesos directos instalados usan: no los muevas.
- `docs/` es la web de GitHub Pages (con `docs/demo`); la documentación va en `documentacion/`.

## Cómo correr y probar
- Instalar: `instalar.ps1` (uv y Python 3.13 en `runtime\`, `.venv`, `voz\.venv`, Electron, Whisper, Piper, F5). En esta
  PC `.venv` es el de ComfyUI: rehacerlo detiene el companion (solo si el usuario lo pide).
- Servidor: `.venv\Scripts\python.exe -m companion` (8200 o `PORT` de `.env`). `iniciar.ps1 -SinVentana` sin ventana.
- **Pruebas rápidas tras cada cambio:** `.venv\Scripts\python.exe -m unittest discover -s tests -t .`
- Pruebas completas en `scripts\pruebas\` contra el servidor aislado (8201, `data\prueba`; `--local` usa Ollama).
  Si una prueba se comporta como el código anterior, sospecha de JavaScript en caché.
- El panel de navegador de Claude bloquea el micrófono: ahí se prueba escribiendo; micrófono simulado con
  `prueba_navegador.py`; avatar con `maniqui_vrm.py` y `window.companion.avatar` (`sheet([...])` para poses).
- Versiones fijas: `requirements.lock`, `voz\requirements.lock` (y `-mac`); rehazlos con
  `scripts\instalacion\fijar_versiones.ps1` tras cambiar dependencias.
- Publicar: `VERSION` + `CHANGELOG.md` + etiqueta `vX.Y.Z` (crea `.exe` y `.dmg`). **Una etiqueta publica un Release:
  solo cuando el usuario lo pida.** Commit y push, también solo cuando lo pida.

## Reglas
**Datos y privacidad**
- Nunca subas ni muestres `.env`, `data/`, registros ni `.vrm` (salvo `models/avatar1.vrm` y `avatar2.vrm`, que sí van
  en git). `mika.vrm`, `mika_base.vrm`, `chica.vrm`, `chico.vrm` siguen en disco sin usarse: no los borres sin pedirlo.
- Las claves nunca se devuelven a la interfaz ni se imprimen (ni sus últimos caracteres). Para leerlas en un script,
  `secret.reveal`. Se guardan cifradas (`companion/secret.py`: DPAPI / Llavero).
- Los registros no llevan lo que se dice (`config.shown`; `LOG_TEXT=1` lo activa). No escribas texto del usuario, de
  recuerdos ni de lo oído en el registro.
- No envíes a ningún LLM una captura real de la pantalla del usuario en una prueba.

**El companion del usuario**
- Puede estar abierto (y suele estar jugando). No reinicies ni apagues el servidor real (8200): que lo haga él
  (`detener.ps1` o `Companion.bat`). Nunca llames contra él a `DELETE /api/memory` ni a `POST /api/setup/reset`.
- No abras ventanas visibles sin avisar. Las pruebas de escritorio van fuera de pantalla (`COMPANION_TEST=1`) y al
  compartir pantalla usan `desktop\tarjeta-prueba.html`, nunca una ventana real.
- Voz: para medir usa un servidor en el 8211 (`TTS_URL`), nunca el 8210. No pruebes muchas voces seguidas.
- Ollama tiene una sola cola: no midas modelos mientras el usuario conversa en local; lo de fondo, ligero.
- No arranques con un `STT_MODEL` que no esté en `models\whisper` (descargaría de Hugging Face).
- El modelo local que elige el usuario es el que se carga: no lo cambies sin avisar.
- Micrófono y cámara reales (`prueba_dispositivos.py`) solo si lo pide. La Brio: no cierres y reabras la cámara sin
  `audio.heal()`.
- No toques waifuv3 (`D:\waifuv3`, nodo de voz del 8100): es otro proyecto.

**Seguridad de acciones y control**
- Catálogo de acciones cerrado y de poco riesgo: no añadas borrar, enviar, comprar, cambiar ajustes ni comandos libres
  sin que el usuario lo pida. Solo cuentan las de turnos con mensaje del usuario (nunca de la mirada, el saludo, un
  resultado o un temporizador).
- No quites la confirmación de pasos delicados (`control.task_allows`) ni la tarjeta cuando la acción la eligió el
  modelo con pantalla o cámara compartidas; en vivo, si la pantalla sonó hace poco (`_live_mixed`), toda acción va con
  tarjeta. Se mantienen aun con «Acceso total».
- Probar acciones: `prueba_acciones.py` con `COMPANION_ACTIONS_DRY=1`. Control de ventanas: SOLO
  `prueba_control.py` (`COMPANION_CONTROL_ONLY`, `COMPANION_CONTROL_NO_INPUT=1`); `prueba_control_real.py --si`
  únicamente si lo pide. Nunca traigas una ventana al frente al empezar.
- `abrir_carpeta` rechaza rutas de red ANTES de comprobar si existen.
- El servidor rechaza un `Host` que no sea `127.0.0.1`/`localhost` (DNS rebinding): un cliente de pruebas usa esos nombres.

**Personaje y contenido**
- Personaje siempre adulto. Los temas +18 solo con el cerebro local (`prompt.adult_active`), nunca con la nube (tampoco
  si la nube cae al local); no quites `ADULT_HARD_LIMITS`.
- Personajes y voces sin etiquetas de género en la interfaz. El modelo de Mika está retirado: no lo vuelvas a ofrecer.
- Etiquetas `[emo:…]`, `[gesto:…]`, `[recordar: …]`, `[accion: …]`: una emoción o gesto nuevo va en `prompt.py`,
  `avatar.js`, `orb.js` (y efectos en `effects.js`).
- Poses en convención VRM 1.0 (los 0.x invierten X y Z); los brazos se escriben para el izquierdo y se reflejan.
- Animaciones solo CC0 o equivalentes (no Mixamo, Bandai Namco, LAFAN1). 100STYLE exige citar «The 100STYLE Dataset - Ian Mason».
- El prompt de sistema no lleva nada que cambie por turno (va en `turn_context` o en el último mensaje).

**Código**
- Los `.ps1` llevan BOM UTF-8. No edites archivos con `Get-Content`/`Set-Content` (corrompen acentos).
- Un parámetro de PowerShell nunca puede llamarse como una variable del script (no distingue mayúsculas).
- Ventana flotante: muévela siempre con `setBounds` y el tamaño guardado; todo movimiento por `animate`/`frame` con dt.
  No vuelvas a leer píxeles ni escribir estilos en cada cuadro; no abras una página nueva por modo.
- Instalador: un paso nuevo se marca (`::paso::`…) y se añade a `$definicion` de la ventana. El lanzador
  (`instalador\Lanzador.cs`) nunca lleva `-ExecutionPolicy Bypass` ni `-WindowStyle Hidden`. Nunca abras la ventana
  del instalador ni el desinstalador contra esta carpeta sin pedirlo.
- Descargas: pide permiso; Python sobre archivos descargados, con `-I`.
- `rust-live/`: replica las mismas reglas de seguridad que el servidor de Python (Host, claves cifradas, rutas de red,
  freno de pantalla en vivo).
