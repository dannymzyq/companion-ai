# Companion Live — Ejecutable Portable Ultra-Ligero en Rust

Versión nativa y **100 % portable en Rust** de Companion PC diseñada para el **modo Live API** (Gemini Live, OpenAI Realtime, xAI Grok Voice, Qwen Omni Realtime y proveedores compatibles) en equipos de **muy pocos recursos** (sin Python, sin Electron, sin PowerShell, sin Node, sin PyTorch, sin Whisper local, sin Ollama).

## Qué lleva dentro
- **Ejecutable portable (`Companion-Live.exe`)** con toda la interfaz `web/` (HTML, CSS, JS, Three.js, three-vrm, animaciones) y las personalidades `personas/` **embebidas en memoria dentro del propio binario** (arranque instantáneo, 0 I/O de disco para la UI).
- **Motor nativo en Rust** (`axum` + `tokio` + `tao` + `wry` / WebView2) con ventana limpia sin consola negra.
- **Datos portables**: guarda `data/` junto al ejecutable (o en `%LOCALAPPDATA%\CompanionLive` si la carpeta es de solo lectura).
- **Proveedores Live API integrados**:
  - **Google Gemini Live** (`BidiGenerateContent` WSS: audio PCM 16 kHz / 24 kHz, transcripción, interrupciones, visión en vivo, herramientas `expresar`, `recordar` y `ejecutar_accion`).
  - **OpenAI Realtime** (GA), **xAI Grok Voice**, **Qwen Omni Realtime** (beta) y URL `wss://` personalizada, con remuestreo PCM en Rust puro.
- **Modo ultra-ligero (`--lite`)**: desactiva Three.js/WebGL y usa el orbe CSS reactivo al sonido (0 % GPU).
- **Modo navegador (`--browser`)**: abre en tu navegador del sistema sin abrir WebView2.
- **Ventana flotante transparente y siempre encima** (`desktop.float`) sin recargar la página ni cortar la llamada.
- **Personalidades**, **ánimo persistente**, **memoria**, **gestos por voz**, **modelos VRM 0.x/1.0**, **acciones seguras en la PC** y **escena de escritorio Win32**.

## Cómo usarlo
Haz doble clic en **`dist\Companion-Live\Companion-Live.exe`** (puedes copiar la carpeta `dist\Companion-Live` a cualquier PC o USB).

### Opciones opcionales por línea de comandos
| Opción | Descripción |
|---|---|
| `--lite` / `--ligero` | Modo ultra-ligero sin 3D/WebGL (0 % GPU) |
| `--float` / `--flotante` | Arranca directamente en modo ventana flotante |
| `--browser` / `--navegador` | Abre en el navegador del sistema |
| `--no-window` / `--sin-ventana` | Solo arranca el servidor HTTP/WS local |
| `--port <N>` | Puerto local (por defecto `8200` o el primer puerto libre) |

## Compilar desde código fuente
```bash
cd rust-live
cargo build --release
```
*(En Windows con toolchain MSVC / GitHub Actions, `WebView2LoaderStatic.lib` se enlaza estáticamente y el resultado es un único `.exe` sin ningún DLL externo; con toolchain GNU/LLVM-MinGW requiere `WebView2Loader.dll` de 162 KB junto al `.exe`.)*
