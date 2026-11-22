# Companion Live — Edición Ultra-Ligera en Rust

Versión nativa en **Rust** de Companion PC diseñada específicamente para el **modo Live API** (Gemini Live, OpenAI Realtime, xAI Grok Voice, Qwen Omni Realtime y proveedores compatibles) en equipos de **muy pocos recursos** (sin Python, sin Electron, sin PyTorch, sin Whisper local, sin Ollama).

## Qué incluye
- **Un solo binario nativo** (`companion-live.exe`, ~5–10 MB en release con LTO y `strip`) usando **Axum + Tokio + `tao` + `wry`** (WebView2 nativo de Windows, WKWebView en macOS).
- **Reutiliza la interfaz `web/` y los datos `data/` / `personas/` / `models/`** del proyecto actual.
- **Proveedores Live API integrados**:
  - Google Gemini Live (`BidiGenerateContent` WSS: audio PCM 16 kHz entrada / 24 kHz salida, transcripción, interrupciones, visión en vivo, llamadas a herramientas `expresar` y `ejecutar_accion`).
  - OpenAI Realtime (protocolo GA), xAI Grok Voice, Qwen Omni Realtime (protocolo beta) y URL `wss://` personalizada, con remuestreo PCM 16 kHz ↔ 24 kHz en Rust puro.
- **Modo ultra-ligero (`--lite`)**: desactiva por completo Three.js/WebGL y usa el orbe CSS reactivo al sonido (0 % GPU, mínimo consumo de CPU y RAM).
- **Modo navegador (`--browser`)**: abre en tu navegador del sistema sin siquiera abrir WebView2.
- **Ventana flotante transparente y siempre encima** (`desktop.float`), cambio entre ventana normal y flotante **sin recargar la página ni cortar la llamada**, arrastre, redimensionado y click-through.
- **Personalidades** (catálogo `personas/personalidades.json` + CRUD de personalidades propias), **ánimo persistente** (`data/mood.json`), **memoria y conversación** (`data/live_memory.json`), **gestos por voz** (`play.rs`) y **modelos VRM 0.x/1.0** (validación GLB + carga/subida de modelos propios).
- **Acciones seguras en la PC** (`abrir_app`, `abrir_web`, `abrir_carpeta`, `buscar_archivo`, `temporizador`, `multimedia`, `volumen`) con sistema de permisos y registro en `data/acciones.jsonl`.
- **Escena de escritorio nativa Win32** (`GET /api/desktop/scene`) para modo flotante.

## Compilar y ejecutar
```powershell
cd rust-live
cargo build --release
.\target\release\companion-live.exe
```

### Opciones de línea de comandos
| Opción | Descripción |
|---|---|
| `--lite` / `--ligero` | Modo ultra-ligero sin 3D/WebGL (ideal para PCs sin GPU dedicada o con poca RAM) |
| `--float` / `--flotante` | Arranca directamente en modo ventana flotante transparente |
| `--browser` / `--navegador` | Abre en el navegador del sistema (sin WebView) |
| `--no-window` / `--sin-ventana` | Solo arranca el servidor HTTP/WebSocket local |
| `--port <N>` | Puerto local (por defecto `8200` o el primer puerto libre) |
| `--root <RUTA>` | Carpeta raíz del proyecto donde están `web/`, `personas/`, `models/` |

También puedes usar **`Companion-Live.bat`** o **`iniciar-rust.ps1`** desde la raíz del repositorio.
