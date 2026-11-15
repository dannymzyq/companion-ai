# Cambios

Cada versión se publica como un Release en GitHub con su instalador (`Companion-Setup-X.Y.Z.exe`). Para sacar una
nueva: sube la versión en `VERSION`, añade su apartado aquí arriba y publica la etiqueta (`git tag vX.Y.Z` y
`git push origin vX.Y.Z`); GitHub Actions crea el instalador y el Release.

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
