# Cambios

Cada versión se publica como un Release en GitHub con su instalador (`Companion-Setup-X.Y.Z.exe`). Para sacar una
nueva: sube la versión en `VERSION`, añade su apartado aquí arriba y publica la etiqueta (`git tag vX.Y.Z` y
`git push origin vX.Y.Z`); GitHub Actions crea el instalador y el Release.

## 0.5.1 — 2026-11-15 (solo Windows)

- **La voz completa arranca con drivers de NVIDIA anteriores a la serie 580** (laptop con RTX 3050). El
  instalador ponía siempre PyTorch para CUDA 13, que esos drivers no admiten: PyTorch no veía la tarjeta
  («cudaErrorNotSupported») y la voz intentaba cargar en el procesador sin llegar a sonar. Ahora mira qué CUDA
  admite el driver y, si es menor que 13, instala PyTorch para CUDA 12.6. Al actualizar se cambia solo.
- Si la voz completa no puede cargar, la frase suena con la voz ligera en vez de quedarse muda, y el registro de
  la voz (`voz.log`) explica el motivo.

## 0.5.0 — 2026-11-15

- **App para Mac con Apple Silicon** (macOS 14 o posterior): `Companion-0.5.0-mac.dmg`. Arrastra Companion a
  Aplicaciones y ábrela. La primera vez instala lo que falta, con una ventana de progreso, y con cada versión nueva
  copia solo lo que cambió. Funcionan:
  - la conversación por voz, el avatar y el modo flotante;
  - las dos voces: la completa usa la GPU del Mac;
  - el cerebro en la nube u Ollama para Mac;
  - compartir pantalla y cámara;
  - abrir apps, webs y carpetas, buscar archivos, temporizadores y volumen.

  Todavía no funcionan en el Mac: usar una aplicación por ti, controlar la música ni escuchar el sonido de lo
  compartido. La app no está firmada por un desarrollador de Apple: la primera vez, Ajustes del Sistema ›
  Privacidad y seguridad › «Abrir igualmente».
- **Voz completa en tarjetas de 4 GB**: para decidir si cabe, el companion ahora mide lo que usan los demás
  programas en la tarjeta (antes suponía 2 GB fijos). En una laptop con una RTX 3050 de 4 GB y el cerebro en la
  nube ya suena la completa; si un juego llena la tarjeta, pasa sola a la ligera. El instalador pone las dos
  voces desde 4 GB.

## 0.4.0 — 2026-11-15

- **Las dos voces se instalan** con cualquier tarjeta NVIDIA de 6 GB o más. Suena la **voz completa** y, si a la
  tarjeta le falta memoria de vídeo (un modelo local grande, o un juego abierto que la llena), **pasa sola a la voz
  ligera**. Con el cerebro en la nube vuelve la completa. Se puede apagar en Ajustes › Voz y sonido.
- Si la voz completa deja de responder a mitad de una respuesta, esa respuesta sigue con la ligera en vez de
  quedarse en texto.
- **Salida de audio y volumen**: elige por dónde suena (altavoces, auriculares…) y el volumen de la voz.
- **Ajustes por secciones**, más sencillos, con una «i» que explica cada opción.
- El botón para **flotar** sobre las ventanas pasa a la barra de abajo, junto a compartir pantalla y la cámara.

## 0.3.0 — 2026-11-15

- **Instalador `.exe`** con la misma ventana de siempre: instala en `C:\Program Files\Companion` (o la carpeta que
  elijas) y, si ya está instalado, lo encuentra y copia solo lo que cambió. Las descargas grandes (Python, el oído,
  las voces, PyTorch) no se repiten.
- Los tres personajes incluidos vienen en el instalador (antes, en otra PC solo aparecía la esfera).
- Compartir pantalla: **escuchar también el sonido** de la PC (interruptor al elegir qué compartir). Si Windows no
  entrega el sonido, se comparte la imagen igual y se avisa del motivo.
- Con el cerebro en la nube, el modelo local ya no le quita la memoria de vídeo a la voz completa.
- Voces propias desde una grabación, puerto libre automático al instalar y arrancar, e instalar y desinstalar con
  ventana y progreso en vivo.
