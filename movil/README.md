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
| Cerebro | Gemma 4 E2B solo texto (`mlx-community/Gemma4-E2B-IT-Text-int4`) | 2,7 GB | 117–124 tokens/s; primer texto 0,06 s (5,5 s la primera vez: compila Metal) |
| Cerebro | Gemma 4 E2B (`mlx-community/gemma-4-e2b-it-4bit`) | 3,6 GB | 120–125 tokens/s |
| Cerebro | Gemma 4 E4B (`mlx-community/gemma-4-e4b-it-4bit`) | 5,2 GB | 72 tokens/s |
| Voz ligera | Piper `es_MX-claude-high` (sherpa-onnx, `csukuangfj/vits-piper-*`) | 81 MB | 0,14 s por 4,8 s de audio |
| Detector | Silero VAD de sherpa-onnx | ~2 MB | sin probar: el `silero_vad_v6.onnx` de faster-whisper no lo admite sherpa |

Por defecto se usan el oído turbo y el cerebro E2B solo texto. Con un Apple ID gratuito no se puede pedir el
permiso de más memoria (`increased-memory-limit` se activa en el portal de desarrolladores, que no está disponible
para cuentas gratuitas), así que el cerebro tiene que caber en el límite normal de una app en un iPhone de 8 GB.
E4B (5,2 GB) casi seguro no cabe.

En el simulador MLX no corre. El modo teléfono usa allí un cerebro simulado: el resto del flujo (oído WhisperKit en
el procesador, voz Piper, corte de turnos) es el de verdad.
Medido en el simulador:
- oído small: 7 s, con 4,3 s de primera carga;
- voz: 0,03–0,54 s por frase;
- primer audio a los 8,2 s del fin del habla.

## Probar en el iPhone (lo que el simulador no puede)
1. Instalar desde Xcode (fase 5) y elegir el modo teléfono.
2. Descargar los modelos con wifi.
3. Hablar. En los registros (Xcode › consola, o `log stream --predicate 'subsystem == "local.companion"'`) salen:
   - «Cerebro local: primer texto … s, … tokens/s»;
   - «Oído: … s»;
   - «Voz ligera: … s».
4. Si el cerebro se cierra por memoria (la app se cierra sola al cargarlo), elegir Whisper small o quedarse con E2B solo texto.
