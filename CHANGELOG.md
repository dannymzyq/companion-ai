# Cambios

Cada versión se publica como un Release en GitHub con su instalador (`Companion-Setup-X.Y.Z.exe`). Para sacar una
nueva: sube la versión en `VERSION`, añade su apartado aquí arriba y publica la etiqueta (`git tag vX.Y.Z` y
`git push origin vX.Y.Z`); GitHub Actions crea el instalador y el Release.

## 0.7.0 — 2026-11-16

Correcciones y mejoras de una revisión general del companion en Windows y en el Mac.

- **Seguridad: «abrir una carpeta» ya no acepta carpetas de red.** Con una ruta como `\\servidor\carpeta`, solo
  comprobar si existía hacía que Windows se conectara a ese servidor y le diera una huella de tu contraseña, antes
  de pedir permiso (por ejemplo, si el modelo la sacaba de un texto que se veía en la pantalla compartida).
- **Las claves de API se guardan cifradas**: en Windows con la protección de tu cuenta (copiadas a otra PC no
  sirven) y en el Mac en el Llavero. Las que ya tenías se cifran solas al arrancar.
- **Los ajustes ya no se pueden perder** si el companion se cierra justo al guardarlos (antes el archivo podía
  quedar a medias y se perdían la clave y la bienvenida). Queda además una copia del anterior.
- **La hora es la de tu PC.** Antes el instalador dejaba fija la de Lima en todas las PC.
- **Si Gemini va lento, pasa al siguiente modelo**: si un modelo tarda más de 8 s en empezar a responder dos
  veces seguidas, avisa y durante media hora empieza por el siguiente de la lista (hay días en que
  `gemini-3.6-flash` tarda 20–30 s y Flash-Lite responde en 3).
- **Aviso de versión nueva**: al abrir, si hay una versión publicada más nueva, lo dice y Ajustes › Estado trae
  el enlace para descargarla (una consulta anónima a GitHub como mucho cada 12 horas; `UPDATE_CHECK=0` la apaga).
- **Mac:** los textos ya hablan del Mac (no de «esta PC», «tarjeta gráfica» o «memoria de vídeo»), el estado
  dice que el oído va en la GPU del Mac (antes decía «CPU»), y un Mac con un chip más modesto ya no baja de modelo
  local sin motivo: allí «lento» se mide contra lo que suele ir ese modelo en ese Mac.
- **Privacidad:** los registros ya no guardan lo que dices ni lo que responde (solo cuántos caracteres;
  `LOG_TEXT=1` lo vuelve a activar), y «Borrar todo» compacta la base de datos para que lo borrado no quede dentro.
- Los resúmenes de la memoria no usan «él» ni «ella» cuando la conversación no deja claro tu género.
- Las ventanas se llaman «Companion» y la de compartir pantalla ya no nombra a un personaje fijo.
- La versión de Windows corre también las pruebas antes de publicarse.

## 0.6.2 — 2026-11-16

- **Mac: respuestas mucho más rápidas.** Con la voz completa, el companion empieza a hablar a los 3–4 s de que
  termines (antes, unos 33 s de media en una MacBook M5 Pro). El oído usa la GPU del Mac (0,3–0,7 s; si no puede,
  el procesador con más núcleos); la voz completa va en float16, con 16 pasos y un tramo de 4–5 s de la muestra de
  cada voz, y suena según se genera, sin esperar a la frase entera. Las frases largas se parten en las comas o antes
  de una conjunción, para que no queden huecos entre frases. En el Mac se vuelve a recomendar la voz completa.
- Las voces propias guardan también su tramo corto (las de antes se preparan solas al arrancar en el Mac).
- En la PC no cambia nada de la voz: allí ya tarda ~1,2 s por frase.

## 0.6.1 — 2026-11-16

- **Mac: modelos MLX.** En un Mac con Apple Silicon el cerebro local usa los Gemma 4 en versión MLX de Ollama
  (12B, E4B y E2B, recomendados en la lista de descarga): el doble de rápidos que los de PC en el mismo Mac y ven
  imágenes. Lo elegido antes con un nombre de PC pasa solo a su versión MLX. Necesita Ollama 0.31 o más reciente
  (si es anterior, el instalador lo dice y descarga la versión de PC).

## 0.6.0 — 2026-11-15

- **Pantallas de carga**: la ventana se abre al momento y enseña «Abriendo Companion» mientras arranca el
  servidor (si no llega a arrancar, dice por qué y deja ver el registro). Después, «Preparando a…» marca el
  oído, la voz, el cerebro y el personaje 3D según van quedando listos, y lo mismo al cambiar un ajuste que
  carga un modelo (el oído local, la voz completa, el modelo local).
- **Al cerrar la app se cierra todo**: el servidor se apaga en orden (para la voz completa y saca el modelo
  local de la memoria), se cierra lo que quede con sus procesos hijos y también Ollama si lo abrió el companion.
  Si la ventana se cuelga o se cierra desde el Administrador de tareas, el servidor lo nota y se apaga solo.
- **Solo nube** (Ajustes › Cerebro): cerebro, oído y voz en la nube, sin modelos en la PC. Medido: el servidor
  pasa de ~630 MB de RAM y 1,3 GB de vídeo a 62 MB y nada de vídeo. Al apagarlo vuelve lo de antes.
- **Oído en la nube** (Ajustes › Micrófono y cámara › Oído): Groq con una clave gratuita (unas 2.000 frases al
  día) o Gemini con la clave del cerebro; si falla, Whisper en el procesador.
- **Voz en la nube**: voces neuronales de Microsoft (Edge), gratis y sin clave. Sin internet suena la ligera.
- Incluye también la corrección de la 0.5.1 (voz completa con drivers de NVIDIA anteriores al 580).

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
