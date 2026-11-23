# Desarrollo

Cómo está hecho, cómo probarlo y cómo publicar una versión. Las reglas para agentes (Claude Code) están en
[`CLAUDE.md`](../CLAUDE.md).

## Cómo está hecho

**Servidor (`companion/`, Python + FastAPI, puerto 8200, solo 127.0.0.1):**

| Módulo | Qué hace |
| --- | --- |
| `server.py`, `__main__.py` | API HTTP y WebSocket; rechaza peticiones de otros orígenes o con otro `Host` |
| `session.py` | La conversación: turnos, voz por frases, temporizadores, recordatorios, modo en vivo |
| `llm.py` | Cerebro: Gemini y otros proveedores compatibles con OpenAI, u Ollama; relevo de modelos |
| `gemini_live.py`, `realtime.py` | Conversación en vivo (Gemini Live y protocolo OpenAI Realtime) |
| `stt.py`, `stt_cloud.py`, `vad.py`, `voicecheck.py` | Oído: Whisper local o en la nube, detección de voz, comprobación de lo dicho |
| `tts.py`, `tts_light.py`, `tts_cloud.py`, `voz_proc.py`, `pronounce.py` | Voz completa (F5, `voz/`), ligera (Piper) y en la nube (Edge) |
| `prompt.py`, `tags.py`, `personality.py`, `mood.py`, `play.py` | Personaje: prompt, etiquetas `[emo:…]`/`[gesto:…]`, personalidades, ánimo, gestos por voz |
| `store.py` | SQLite: mensajes, recuerdos, resúmenes, recordatorios |
| `actions.py`, `control.py`, `control_task.py`, `desktop_scene.py` | Acciones en la PC (catálogo cerrado) y uso de ventanas en segundo plano |
| `profile.py`, `state.py`, `secret.py`, `config.py` | Ajustes guardados, recursos de la tarjeta, claves cifradas (DPAPI / Llavero), `.env` |
| `models.py`, `vrm.py` | Modelos 3D incluidos y propios |
| `lifecycle.py`, `update.py` | Arranque, apagado y aviso de versión nueva |

**Interfaz (`web/`):** `main.js` (todo lo demás lo arranca), `avatar.js` + `face.js` + `clips.js` + `lipsync.js` +
`effects.js` + `props.js` (personaje VRM), `orb.js` (la esfera), `audio.js` + `mic-worklet.js`, `vision.js` (cámara y
pantalla), `onboarding.js`, `personality.js`, `loading.js`, `platform.js` (textos del Mac).

**Escritorio (`desktop/`, Electron):** `main.js` (una sola página que pasa entre la ventana y la flotante, bandeja,
atajos, permisos), `pet.js` (mascota), `picker.html` (qué compartir), `mac.js` (arranque de la app del Mac),
`cargando.html`, `instalando.html`.

**Voz completa (`voz/servidor.py`):** F5-TTS en el puerto 8210, con su propio `voz\.venv`; lo arranca y apaga el companion.

## Scripts

- `scripts/instalacion/`: `comun_instalacion.ps1` (piezas comunes), `setup.ps1` y `preparar_recursos.py` (descargas),
  `instalar_escritorio.ps1` (Electron), `ventana_instalar.ps1` / `ventana_desinstalar.ps1` / `ventana_comun.ps1`
  (ventanas WPF), `crear_instalador.ps1` + `instalar_paquete.ps1` + `copiar_programa.ps1` (el `.exe`),
  `crear_app_mac.sh` (el `.dmg`), `fijar_versiones.ps1` (los `.lock`), `crear_icono.py`.
- `scripts/pruebas/`: `_prueba.py` (servidor aislado en el 8201 con `data\prueba`) y las `prueba_*.py`;
  `maniqui_vrm.py` y `hoja_modelos.py` para el avatar.
- `scripts/herramientas/`: voces (`importar_voces`, `grabar_muestras`, `recortar_muestras`, `generar_voces`,
  `calibrar_pronunciacion`), animaciones (`convertir_animaciones`, `anim_bvh`), `vestir_vrm`, mediciones (`medir_*`).

## Publicar una versión

1. Sube `VERSION` y añade su apartado arriba en `CHANGELOG.md` (si dice «(solo Windows)», no se crea la app del Mac).
2. `git tag vX.Y.Z` y `git push origin vX.Y.Z`: `.github/workflows/release.yml` crea el Release con el `.exe` y llama a
   `mac.yml` para el `.dmg`.
3. Las demás ediciones salen con el mismo número: `rust-live-vX.Y.Z` (`release-rust-live.yml`) y `ios-vX.Y.Z` /
   `android-vX.Y.Z` (se compilan en el Mac; ver [movil/README.md](../movil/README.md)).

## Ajustes (`.env`)

| Clave | Para qué |
| --- | --- |
| `LLM_PROVIDER` | `gemini` (nube) o `local` (Ollama en esta PC) |
| `GEMINI_MODEL` | `gemini-3.6-flash` (estable) o `gemini-3.5-flash-lite` (más rápido) |
| `GEMINI_FALLBACK` | Modelos de la API de Google a los que pasar cuando el principal agota su cuota diaria |
| `LOCAL_FALLBACK` | `true`: si no queda ningún modelo en la nube, sigue con el local |
| `OLLAMA_MODEL` | Modelo local, por defecto `gemma4:e4b-it-qat` (tiene que caber en la GPU junto a la voz) |
| `OLLAMA_FALLBACK` | Modelo local más pequeño para cuando el principal no cabe, por defecto `gemma4:e2b-it-qat` |
| `OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_TIMEOUT` | Contexto (8192), tiempo que el modelo queda cargado (15m) y espera máxima sin respuesta (45 s) |
| `WATCH_INTERVAL`, `WATCH_GAP`, `WATCH_MODEL` | Mirada en vivo: segundos entre miradas (7), mínimo entre comentarios (20) y modelo que la hace con la nube (`gemma-4-26b-a4b-it`) |
| `BACKGROUND_MODEL` | Con la nube, modelo que hace primero el trabajo de fondo: resúmenes de la memoria y cada paso al usar una ventana (`gemma-4-26b-a4b-it`). Si falla, sigue el relevo normal |
| `PERSONA` | Personalidad y voz (`personas/mika.json`) |
| `END_SILENCE_MS` | Silencio que marca el fin de tu turno (más bajo = responde antes, pero corta más) |
| `BARGE_IN` | `false` si usas altavoces y Mika se interrumpe con su propia voz |
| `TIMEZONE` | Vacío: la hora de esta PC. Solo para forzar otra zona (`Europe/Madrid`…) |
| `LOG_TEXT` | `1`: los registros guardan también lo que se dice (para buscar un fallo). Por defecto, no |
| `UPDATE_CHECK` | `0`: no mirar en GitHub si hay versión nueva (por defecto mira como mucho cada 12 h) |

Los cambios hechos desde Ajustes duran hasta reiniciar; para dejarlos fijos, edita `.env`. Si el servidor ya
estaba en marcha, `Companion.bat` lo reinicia solo cuando `.env` o el código son más nuevos que él.

## Reglas que el código hace cumplir

- El personaje es siempre adulto (`age ≥ 18` o no arranca).
- Los temas +18 no tienen interruptor: van implícitos con el cerebro local (si tú los propones, Mika puede
  seguirte) siempre que el personaje lo permita en su ficha (`adult.enabled` en `personas/mika.json`).
  Con el cerebro en la nube nunca se activa (`companion/prompt.py: adult_active`).
- Los límites duros del modo +18 de waifuv3 se mantienen tal cual.
- El servidor solo escucha en `127.0.0.1` y rechaza peticiones de otras páginas web: cambios y conversación
  solo desde su propio origen, y cualquier petición que no llame al servidor por `127.0.0.1` o `localhost` (una
  página con un truco de DNS, «DNS rebinding») recibe un 400, también al leer los recuerdos.
- Las claves de API se guardan cifradas en `data\settings.json`: en Windows con la protección de tu cuenta
  (DPAPI: copiadas a otra PC no sirven), en el Mac en el Llavero.
- «Abrir una carpeta» solo abre carpetas de este equipo, nunca de la red.
- «Borrar todo» compacta la base de datos: lo borrado no queda dentro del archivo.

## Registros

- `data\companion.log`: lo que hizo el companion en esta sesión. Cada arranque guarda las tres anteriores
  (`companion.1.log` es la última), así que si se cerró por un error, el motivo sigue ahí. No guardan lo que
  dices ni lo que responde (solo cuántos caracteres), salvo con `LOG_TEXT=1` en `.env`.
- `data\voz.log` (y `voz.1.log`, la vez anterior): el servidor de la voz completa. Si se cae, el companion lo
  vuelve a arrancar en la siguiente frase; al arrancar, la primera frase espera a que cargue (hasta un minuto)
  en vez de quedarse sin voz.

## Pruebas

**Rápidas** (44 pruebas en unos 3 s, sin GPU, micrófono, Ollama, nube ni servidores; no tocan nada tuyo):
etiquetas, pronunciación, comprobación de la voz, acciones y los frenos del control de ventanas, recomendación
por tarjeta, relevo de modelos, memoria, seguridad local, voz que espera al cargar, temporizadores y el bucle de
control con piezas simuladas. Conviene correrlas después de cada cambio:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Las pruebas de conversación levantan su propio servidor (puerto 8201, datos en `data\prueba`): no tocan tu
conversación, tus recuerdos ni tus modelos, y no reinician el companion real. Gastan cuota de Gemini, salvo con
`--local` (admitido por `prueba_escritorio.py`, `prueba_ws.py` y `prueba_navegador.py`), que usa el cerebro local.
Para «compartir una ventana» la prueba abre su propia tarjeta (`desktop\tarjeta-prueba.html`), nunca una tuya.

```powershell
.venv\Scripts\python.exe scripts\pruebas\prueba_escritorio.py       # app de escritorio: modelos, cámara, selector de pantalla o ventana y modo flotante (sin ventanas visibles)
.venv\Scripts\python.exe scripts\pruebas\prueba_escritorio.py --local   # lo mismo con el cerebro local
.venv\Scripts\python.exe scripts\pruebas\prueba_bienvenida.py       # la bienvenida completa, que se guarda, no se repite y se edita desde Ajustes (sin GEMINI_API_KEY en .env, por el camino del modelo local)
.venv\Scripts\python.exe scripts\pruebas\prueba_acciones.py         # acciones con permiso, en modo simulado: no abre ni pulsa nada en la PC (cerebro local)
.venv\Scripts\python.exe scripts\pruebas\prueba_control.py [modelo] # usar una ventana: solo su propio reproductor falso, fuera de pantalla, sin teclado ni ratón de verdad
.venv\Scripts\python.exe scripts\pruebas\prueba_control.py --mensajes # ídem solo con mensajes a la ventana (escribir y reproducir en segundo plano)
.venv\Scripts\python.exe scripts\pruebas\prueba_control_real.py --si  # ídem con TECLADO Y RATÓN DE VERDAD y captura: la ventana a la vista, ~2 min sin usar la PC
.venv\Scripts\python.exe scripts\pruebas\prueba_memoria.py          # memoria a largo plazo: conversación larga, sesión nueva y pregunta sobre lo anterior (cerebro local)
.venv\Scripts\python.exe scripts\pruebas\prueba_componentes.py      # etiquetas, voz, detección de voz, Whisper
.venv\Scripts\python.exe scripts\pruebas\prueba_ws.py               # conversación hablada completa, sin interfaz
.venv\Scripts\python.exe scripts\pruebas\prueba_carga.py            # pantallas de carga, apagado si muere la ventana y detener.ps1 (solo el servidor de prueba)
.venv\Scripts\python.exe scripts\pruebas\prueba_nube.py             # «solo nube»: conversación hablada y medición de RAM, procesador y vídeo (--turnos 0: sin gastar cuota)
.venv\Scripts\python.exe scripts\pruebas\prueba_ws.py --interrumpir # hablarle encima
.venv\Scripts\python.exe scripts\pruebas\prueba_navegador.py        # permiso y selector de micrófono en un Chrome oculto
.venv\Scripts\python.exe scripts\pruebas\prueba_dispositivos.py --mic BRIO --cam BRIO   # micrófono y cámara FÍSICOS (enciende la luz de la cámara; nada llega a un modelo)
.venv\Scripts\python.exe scripts\pruebas\maniqui_vrm.py data\maniqui.vrm  # maniquí de cajas para probar el avatar
.venv\Scripts\python.exe scripts\herramientas\medir_llm.py gemini-3.6-flash:minimal gemini-3.5-flash-lite:minimal   # latencia del cerebro
.venv\Scripts\python.exe scripts\herramientas\medir_llm.py local/gemma4:e4b-it-qat local/gemma4:e2b-it-qat          # ídem, modelos locales
```

## Latencia medida (11 nov 2026)

Desde que dejas de hablar hasta que suena la voz: **3–4 s con la nube** y **~2 s con el modelo local**.
Se reparte así: 0,55 s de silencio para confirmar el fin del turno (la transcripción se adelanta dentro de ese
tiempo), ~2 s hasta la primera frase de Gemini (igual en Flash, Flash-Lite y Gemma 4) o ~0,5 s con el modelo
local, y ~1 s de síntesis de voz. El primer turno tras arrancar tarda más.
