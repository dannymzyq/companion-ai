# Companion para el teléfono

App de iOS (Android después) con dos modos: **todo en la nube** o **todo dentro del teléfono**.

## Cómo está hecha
- `core/`: el núcleo en JavaScript, que también se usará en Android.
  - `boot.js` sustituye el servidor de la PC: `/ws` es un WebSocket falso y `/api/*` es un fetch propio. Así `web/` funciona casi sin cambios.
  - `session.js`, `prompt.js`, `tags.js` y `store.js` son el port de los `.py` del mismo nombre.
  - `vad.js` hace el corte de turnos de `Session._frame`.
  - `llm.js` es el cerebro: el relevo de Gemini o el del teléfono.
  - `ear_cloud.js`, `voice_cloud.js` y `edge_token.js` son el oído y la voz en la nube.
  - `local.js` y `modelos.js` son los motores y las descargas del modo teléfono.
- `ios/`: proyecto de XcodeGen (`project.yml`; el `.xcodeproj` no va en git). Partes:
  - `Companion/`: SwiftUI + WKWebView. Sirve `web/` desde el paquete por `app://`. Puente nativo con:
    - kv y llavero;
    - HTTP sin CORS (las claves las pone el nativo y nunca vuelven al JS);
    - el WebSocket de la voz de Edge;
    - las descargas.
  - `Motores/`: motores del modo teléfono:
    - WhisperKit (oído);
    - mlx-swift-lm con Gemma 4 (cerebro);
    - sherpa-onnx 1.13 con Piper (voz ligera) y Silero (detector de voz).
  - `ProbarMotores/`: herramienta del Mac que mide esos mismos motores.
- `scripts/`:
  - `vendor.sh`: librerías 3D de la interfaz, fuera de git.
  - `bundle_web.sh`: fase de compilación.
  - `piper_sherpa.py`: convierte una voz Piper al formato de sherpa-onnx, solo para pruebas.

## Pruebas
`node movil/core/pruebas.mjs` comprueba sin teléfono:
- que el bloque +18 nunca va con la nube ni con menores;
- que en el modo teléfono un fallo del cerebro no sale a la red;
- que en el modo nube sin cuota no se usa un cerebro local.

## Compilar
```
movil/scripts/vendor.sh                  # una vez (o con la carpeta web/vendor de una instalación)
xcodebuild -downloadComponent MetalToolchain   # una vez: MLX compila sombreadores de Metal
cd movil/ios && xcodegen
xcodebuild -project Companion.xcodeproj -scheme Companion -sdk iphonesimulator -skipMacroValidation build
```
sherpa-onnx va fijo en 1.13.8: la 2.0 quitó espeak-ng y las voces Piper ya no hablarían sin un fonetizador aparte.

## Modo teléfono: modelos (16 nov 2026)
Se bajan dentro de la app (`/api/phone`):
- con el tamaño antes de empezar;
- con progreso;
- se pueden cancelar y reanudar (por Range);
- solo con wifi, salvo que se permitan los datos móviles.

Probado en el simulador: se canceló a 152 de 646 MB, se reanudó y los 22 archivos quedaron idénticos a los de Hugging Face.

| Pieza | Modelo | Tamaño | Mac M5 Pro (ProbarMotores) |
|---|---|---|---|
| Oído | Whisper large-v3 turbo (`argmaxinc/whisperkit-coreml`, `…turbo_632MB`) | 646 MB | 0,47 s por 4,6 s de habla; primera carga 2 min (compila CoreML, una vez); texto exacto |
| Oído | Whisper small (`…small_216MB`) | 217 MB | 0,32 s; se equivoca («Cien años de solegad») |
| Cerebro | **Llama 3.2 3B** (`mlx-community/Llama-3.2-3B-Instruct-4bit`), por defecto | 1,8 GB | 93 tokens/s; respuestas cortas y naturales, etiquetas bien |
| Cerebro | LFM2 2.6B (`mlx-community/LFM2-2.6B-4bit`) | 1,45 GB | 132 tokens/s; buen español, se alarga |
| Cerebro | (descartados: Qwen3.5 2B se enreda; Qwen3 1.7B entra en bucle) | | |
| Cerebro | Gemma 4 E2B solo texto (`mlx-community/Gemma4-E2B-IT-Text-int4`) | 2,7 GB | 117–124 tokens/s; primer texto 0,06 s (5,5 s la primera vez: compila Metal) |
| Cerebro | Gemma 4 E2B (`mlx-community/gemma-4-e2b-it-4bit`) | 3,6 GB | 120–125 tokens/s |
| Cerebro | Gemma 4 E4B (`mlx-community/gemma-4-e4b-it-4bit`) | 5,2 GB | 72 tokens/s |
| Voz ligera | Piper `es_MX-claude-high` (sherpa-onnx, `csukuangfj/vits-piper-*`) | 81 MB | 0,14 s por 4,8 s de audio |
| Detector | Silero VAD de sherpa-onnx (`asr-models/silero_vad.onnx`) | 0,6 MB | 143 tramas en 0,01 s; en la app, 3 ms por trama con el puente. El `silero_vad_v6.onnx` de faster-whisper no lo admite sherpa |

En el iPhone 16 Pro del usuario (8 GB, Apple ID gratuito), medido el 16 nov 2026:
- iOS deja **3,5 GB** a la app (jetsam «per-process-limit» a ~3,3 GiB);
- Gemma 4 E2B solo texto ocupó 2,9 GB (1,08 veces el archivo): con el oído encima, iOS cerró la app al generar;
- el E2B iba a 16-21 tokens/s, con el primer texto en 2,4-10 s (unos 1.600 tokens de entrada).

Por eso el cerebro por defecto es Llama 3.2 3B. Un cerebro solo se ofrece si deja sitio al oído más pequeño
(cerebro: × 1,08 + 0,3 GB; oído: × 1,4 + 0,1 GB). En Ajustes › Cerebro › Modelos del teléfono se
puede elegir el E2B completo (3,6 GB; entiende imágenes, pero la app aún no usa la cámara) o el E4B (con aviso de
memoria). Silero manda en los dos modos si está bajado; si falla, el detector por energía. Con un Apple ID gratuito no se puede pedir el
permiso de más memoria (`increased-memory-limit` se activa en el portal de desarrolladores, que no está disponible
para cuentas gratuitas), así que el cerebro tiene que caber en el límite normal de una app en un iPhone de 8 GB.
E4B (5,2 GB) casi seguro no cabe.

En el simulador MLX no corre. El modo teléfono usa allí un cerebro simulado: el resto del flujo (oído WhisperKit en
el procesador, voz Piper, corte de turnos) es el de verdad.
Medido en el simulador:
- oído small: 7 s, con 4,3 s de primera carga;
- voz: 0,03–0,54 s por frase;
- primer audio a los 8,2 s del fin del habla.

## Modo «En vivo» (Gemini Live, 21 nov 2026)
El modo recomendado en el teléfono: una sola conversación de voz con Gemini Live (te oye, piensa y habla en la nube).
No descarga ni carga ningún modelo (ni WhisperKit, ni MLX, ni Piper).
- `core/live.js`: port de `companion/gemini_live.py` y de la parte en vivo de `session.py` (`LiveSession`, con la
  misma forma que `Session`). Prompt de la ficha + `liveRecap` + hora al final (nunca como mensaje aparte), herramienta
  `expresar` (NON_BLOCKING, respuesta SILENT) y `guessEmotion` mientras llega el texto. Sin `ejecutar_accion`: en el
  teléfono no hay acciones. Nunca +18 (`llm.isCloud()` es cierto en «vivo»).
- `ios/Companion/LiveSocket.swift`: el WebSocket lo abre el nativo (`live.open` / `live.send`; se cierra con
  `stream.cancel`) y pone la clave en la dirección; solo conecta con `generativelanguage.googleapis.com`. La clave es
  la propia de En vivo (`live_key`) o la del cerebro (`cloud_key`) si el cerebro es Gemini; nunca vuelve al JS.
- La sesión de audio no se toca al conectar: pasarla a `.voiceChat` dejaba la voz de la página en «interrupted»
  (la cancelación de eco la da WebKit con `echoCancellation`).
- Ajustes › Cerebro y voz: tarjetas En vivo, Nube y Todo en el teléfono (la de «Nube + voz en tu PC» se esconde).
  Ajustes guardados: `mode` = `vivo` | `nube` | `telefono`.
- Medido en el simulador con la clave real: primer audio 2,8 s en el primer turno (con la conexión), y 1,0 s después
  de acabar de hablar en un turno por voz (micrófono simulado con una grabación).

### Probarlo en el iPhone
1. Instala como siempre (sección siguiente) desde la rama `ios`.
2. Ajustes › Cerebro y voz › «En vivo». Si el cerebro ya tiene tu clave de Gemini, se activa al momento; si no,
   pega la clave en «Con quién habla en vivo» y pulsa «Guardar y activar».
3. Habla con el altavoz (sin auriculares): comprueba que no se interrumpe sola con su propia voz (eco) y que puedes
   cortarla hablando encima.
4. Prueba también escribirle, y cambiar a «Nube» y volver: la conversación sigue sin recargar.

## Cámara, pantalla compartida y ventana flotante (0.2.0, 22 nov 2026)
- **Cámara:** apagada al abrir la app. Vista previa vertical (sin pedir ancho ni alto: con ellos WebKit da 1280×720
  en horizontal; sin ellos, 480×640 en vertical, medido en un iPhone 16 Pro). Solo dos cámaras: la frontal y la
  trasera virtual (triple o doble), con zoom de 0,5× a 10× (pellizcar o tocar la vista previa). `ui_movil.js`.
- **Compartir pantalla:** extensión de transmisión de ReplayKit (`ios/Pantalla/SampleHandler.swift`, objetivo
  `Pantalla`). Manda una imagen cada ~0,8 s (JPEG, 1280 px como mucho) a la app por 127.0.0.1:47621
  (`ReceptorPantalla.swift`, sin App Groups, que un Apple ID gratuito no siempre puede firmar); la página la pasa a
  la conversación como la pantalla compartida de la PC (`frame` con `source: 'screen'`: En vivo a Gemini, en Nube con
  el mensaje). El simulador no tiene transmisión de pantalla: solo se prueba en el iPhone.
- **Ventana flotante (picture in picture):** encendida de serie, se abre sola al salir de la app y se cierra al
  volver (`VentanaFlotante.swift`, 9:16). Interruptor en Ajustes › Dispositivos. Para que la página siga animando y
  hablando fuera de la app: audio en silencio desde el nativo (si no, iOS suspende la app) y
  `_setThrottleStateForTesting:` de WKWebView (método interno; sin él WebKit duerme la página a los ~5 s). Si una
  versión de iOS lo quita, la ventana repite los últimos 4 s en bucle.
- **Micrófono y salida:** siempre los que el iPhone usa en ese momento; si cambian (auriculares), se reabre el
  micrófono predeterminado. Con el permiso de iOS ya dado, la app empieza sin la tarjeta «Permitir micrófono».

## iOS 0.9.2 (22 nov 2026)
Misma versión que la PC. El icono pasa al nuevo de la 0.9.2 (`scripts/crear_icono.py`, dibujado a sangre: sin
esquinas redondeadas ni transparencia, que iOS recorta solo). Incluye los arreglos compartidos con Android: la cámara
pide permiso solo al encenderla, el teclado no tapa la bienvenida y textos del teléfono.

## Android (0.2.0, 22 nov 2026)
`movil/android`: la misma interfaz (web/) y el mismo núcleo (movil/core) en un WebView, con un puente nativo que tiene
los mismos comandos que el de iOS (`Bridge.kt` ↔ `Bridge.swift`). Lo que cambia:
- **Archivos:** `assets/www` (lo copia `bundle_web.sh` antes de cada compilación) servido en
  `https://appassets.androidplatform.net` con `WebViewAssetLoader`; los VRM propios en `/propios/`.
- **Puente:** `addWebMessageListener` (solo ese origen) + `window.companionNative.post` (el shim de `Bridge.SHIM`);
  `boot.js` va con `addDocumentStartJavaScript`. Hace falta un «Android System WebView» actual.
- **Claves:** cifradas con el almacén de Android (Keystore, `Secretos.kt`); la página nunca las ve.
- **En vivo y Nube:** OkHttp (`LiveSocket.kt`, `SocketCollect.kt`, flujos en `Bridge.kt`).
- **Ventana flotante:** el picture in picture de Android es la propia app en pequeño (9:16, se abre sola al salir con
  la ventana encendida): el personaje sigue en directo sin mandar cuadros. `body.en-pip` deja solo el personaje.
- **Compartir pantalla:** MediaProjection en un servicio de primer plano (`ServicioPantalla.kt`), una imagen cada
  ~0,8 s a la página (los mismos avisos `pantalla`/`pantallaEstado` que en iOS).
- **Teclado:** `adjustNothing` + el alto del teclado a `window.__teclado` (como en iOS).
- **Todavía no:** el modo «Todo en el teléfono» (MLX, WhisperKit y Piper son de Apple); su tarjeta se esconde.

Probado en el emulador (Android 17, API 37): bienvenida, Nube (primera frase 3,8 s y voz de Edge), En vivo, cámara
vertical con frontal y trasera, ventana flotante y pantalla compartida.

### Compilar e instalar
Hace falta Android Studio (trae el JDK y el SDK). En el Mac:
```
cd movil/android
JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" ./gradlew assembleRelease
adb install -r app/build/outputs/apk/release/app-release.apk
```
O abre `movil/android` en Android Studio y pulsa ▶ con el teléfono conectado (depuración USB activada). La versión
«release» se firma con la clave de depuración: sirve para instalarla tú, no para Play Store.

## Instalarla en tu iPhone (Apple ID gratuito, sin TestFlight)
Hace falta:
- un Mac con Xcode 27 (y el Metal Toolchain);
- un iPhone 15 Pro o más nuevo con iOS 17 o superior;
- su cable;
- tu Apple ID.

1. En el Mac, dentro del repo, en la rama `ios`:
   ```
   movil/scripts/vendor.sh
   cd movil/ios && xcodegen && open Companion.xcodeproj
   ```
2. Xcode › Settings › Accounts › «+» › Apple ID: inicia sesión con tu cuenta. Esto lo haces tú.
3. En el proyecto: objetivo **Companion** › Signing & Capabilities.
   - **Team**: «(tu nombre) (Personal Team)».
   - Si Xcode dice que el identificador ya está en uso, cambia **Bundle Identifier** por uno tuyo, por ejemplo `com.tunombre.companion`.
   - Lo mismo en el objetivo **Pantalla** (compartir pantalla), con el mismo Team. Su identificador tiene que ser el
     de la app seguido de `.pantalla`.
4. En el iPhone: conéctalo con el cable y pulsa «Confiar» en este ordenador.
5. Ajustes › Privacidad y seguridad › **Modo de desarrollador** › activar. El iPhone se reinicia; al volver, confirma.
6. En Xcode, Product › Scheme › Edit Scheme › Run › Build Configuration: **Release**. En Debug, MLX va muchas veces más lento.
7. Elige tu iPhone arriba (junto a «Companion») y pulsa ▶. La primera compilación tarda varios minutos.
8. La primera vez, iOS no la abrirá: Ajustes › General › VPN y gestión de dispositivos › tu Apple ID › **Confiar**. Vuelve a pulsar ▶.
9. En la app:
   - la bienvenida;
   - la clave de Gemini para el modo nube;
   - o «Prefiero todo dentro del teléfono» y **Descargar**, con wifi: unos 3,4 GB con el oído turbo y el cerebro E2B.

Con un Apple ID gratuito:
- la app deja de abrirse a los **7 días**: conecta el iPhone y pulsa ▶ otra vez (no se pierden los datos ni los modelos);
- caben **3 apps** a la vez instaladas así.

## Probar en el iPhone (lo que el simulador no puede)
1. Instalar desde Xcode (fase 5) y elegir el modo teléfono.
2. Descargar los modelos con wifi.
3. Hablar. En los registros (Xcode › consola, o `log stream --predicate 'subsystem == "local.companion"'`) salen:
   - «Cerebro local: primer texto … s, … tokens/s»;
   - «Oído: … s»;
   - «Voz ligera: … s».
4. Si el cerebro se cierra por memoria (la app se cierra sola al cargarlo), elegir Whisper small o quedarse con E2B solo texto.
