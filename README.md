# Companion

Un personaje 3D (avatar VRM o una esfera animada) con el que hablas como en una llamada: te escucha, responde con su
voz, se mueve, reacciona y recuerda lo que le cuentas. Puede vivir en una ventana o suelto por el escritorio como una
mascota, ver tu pantalla o tu cámara si se lo pides y hacer cosas sencillas en tu PC con tu permiso.

```
micrófono ─► detección de voz ─► oído (Whisper) ─► cerebro (LLM) ─► frases + etiquetas ─► voz ─► altavoces
                                                    │                                          │
                               nube (Gemini, OpenAI…) u Ollama local       avatar 3D: boca, emoción, gestos
                    ── o, en modo «En vivo», todo en una sola conexión de voz en tiempo real (Gemini Live…) ──
```

Solo sale de tu equipo lo que necesita el cerebro en la nube que elijas. El historial, los recuerdos y las claves
(cifradas) se quedan en tu equipo.

## Ediciones

| Edición | Para quién | Dónde está | Cómo se publica |
| --- | --- | --- | --- |
| **PC (Windows)** | La completa: voz e IA locales o en la nube, ventana y mascota de escritorio (Electron) | raíz del repositorio | `Companion-Setup-X.Y.Z.exe` (etiqueta `vX.Y.Z`) |
| **Mac (Apple Silicon)** | La misma, adaptada al Mac (MLX, Llavero) | la misma; `desktop/mac.js` | `Companion-X.Y.Z-mac.dmg` (mismo Release) |
| **Companion Live (Rust)** | PCs con pocos recursos: un `.exe` portable, solo modo «En vivo», sin Python ni Electron | [`rust-live/`](rust-live/README.md) | `Companion-Live.exe` (etiqueta `rust-live-vX.Y.Z`) |
| **iOS y Android** | El teléfono: modo «En vivo» y nube, la misma interfaz en un WebView | [`movil/`](movil/README.md) | `.ipa` y `.apk` (etiquetas `ios-vX.Y.Z`, `android-vX.Y.Z`) |

Todas comparten la interfaz de [`web/`](web/) y salen bajo el mismo número de versión.

## Instalar y usar

- **Instalar:** descarga el instalador de la última versión en
  [Releases](https://github.com/dannymzyq/companion-ai/releases) y ábrelo. Detalles, requisitos y opciones en
  [documentacion/instalacion.md](documentacion/instalacion.md).
- **Abrir:** el acceso «Companion» del escritorio o del menú Inicio (desde el código: `Companion.bat`).
- **Usar:** la primera vez te guía una bienvenida. Todo lo demás está en
  [documentacion/uso.md](documentacion/uso.md).

## Documentación

| Guía | Contenido |
| --- | --- |
| [instalacion.md](documentacion/instalacion.md) | Requisitos, instalador, qué se recomienda según la tarjeta, `.env`, problemas frecuentes, actualizar y desinstalar |
| [uso.md](documentacion/uso.md) | Bienvenida, modos de cerebro y voz, memoria, personalidad, modo flotante y mascota, acciones en la PC, cámara y pantalla |
| [personaje.md](documentacion/personaje.md) | Modelos 3D, ropa, animaciones, emociones y gestos |
| [desarrollo.md](documentacion/desarrollo.md) | Estructura del código, ajustes, pruebas, registros y cómo publicar versiones |
| [CHANGELOG.md](CHANGELOG.md) | Cambios de cada versión |
| [movil/README.md](movil/README.md) · [rust-live/README.md](rust-live/README.md) | Las ediciones de teléfono y la ligera en Rust |
| [CLAUDE.md](CLAUDE.md) | Instrucciones para agentes de código (Claude Code) |

## Estructura del repositorio

```
Companion.bat, iniciar/detener/instalar/desinstalar(.ps1/.sh), Instalar.bat, Desinstalar.bat
                     lanzadores (se quedan en la raíz: los accesos directos instalados apuntan a ellos)
companion/           servidor en Python (FastAPI): conversación, cerebro, oído, voz, memoria, acciones
web/                 interfaz (HTML + ES modules sin compilar): avatar 3D, audio, ajustes
desktop/             app de escritorio Electron (Windows y Mac): ventanas, mascota, selector de pantalla
voz/                 servidor de la voz completa (F5-TTS) con su propio entorno
personas/            ficha del personaje y personalidades
voices/, voices.json voces (muestras, previas y créditos)
models/              modelos 3D incluidos
rust-live/           edición ligera en Rust
movil/               apps de iOS y Android (núcleo JS común en movil/core)
instalador/          lanzador del instalador .exe
scripts/instalacion/ instalador, paquete, app del Mac, icono, versiones fijas
scripts/pruebas/     pruebas completas (servidor aislado en el puerto 8201, Electron fuera de pantalla)
scripts/herramientas/ voces, animaciones, mediciones
tests/               pruebas rápidas (segundos, sin GPU ni red)
documentacion/       guías
docs/                web de presentación (GitHub Pages) y demo web
```

No van en git: `data/` (tu conversación, ajustes y registros), `.env`, `models/` descargados, `runtime/`, `.venv`,
`dist/`.
