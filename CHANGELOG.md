# Cambios

Cada versión se publica como un Release en GitHub con su instalador (`Companion-Setup-X.Y.Z.exe`). Para sacar una
nueva: sube la versión en `VERSION`, añade su apartado aquí arriba y publica la etiqueta (`git tag vX.Y.Z` y
`git push origin vX.Y.Z`); GitHub Actions crea el instalador y el Release.

## 0.8.1 — 2026-11-17

- **Cara ARKit**: los modelos que traen las 52 formas de ARKit («Perfect Sync», como Test-Chan) usan su cara
  completa: cada lado de la boca, mejillas, cejas y ojos por separado, con media sonrisa, una ceja levantada, labios
  apretados, mejillas hinchadas o la nariz arrugada según la emoción, y los labios redondeándose o apretándose al
  hablar. El companion lo detecta solo al cargar el modelo; los demás siguen igual (VRoid por partes o expresiones).
- **Cambiar de personalidad ya no parece colgado**: mientras se ajusta, una pequeña pantalla «Ajustando su
  personalidad…» encima de la lista (y no se puede pulsar dos veces). Con el cerebro local, el modelo lee ya el prompt
  nuevo durante ese rato, así que la primera respuesta tras el cambio no tarda más. Si algo no contesta en 30 s, se
  deja de esperar y se avisa.

## 0.8.0 — 2026-11-17

Todo lo nuevo funciona igual en Windows y en el Mac (la app del Mac se crea con el mismo código).

- **Animaciones grabadas**: el cuerpo se mueve ahora con animaciones de captura de movimiento (reposo, hablar,
  andar, agacharse, arrodillarse, aterrizar, cruzarse de brazos al enfadarse), adaptadas a cualquier VRM, también a
  los que cargues tú. Encima sigue lo de siempre: respiración, mirada, gestos al hablar, emociones y toques. Andar
  flotando avanza lo que mide su paso, sin patinar. Son de la Universal Animation Library de Quaternius (CC0).
- **Anda y está de pie según cómo se siente**: con alegría da pasos largos y mueve los brazos, triste arrastra
  los pies con la cabeza baja, tímida camina con pasitos cortos, y también enfadada, pensativa (manos a la espalda),
  enamorada (pasos ligeros) o nerviosa (de puntillas). Sin una emoción marcada, anda según su personalidad (más
  tímida u orgullosa). Al cambiar de emoción a media marcha pasa de un estilo a otro sin saltos. Son capturas de
  personas reales de The 100STYLE Dataset - Ian Mason (CC BY 4.0), algo exageradas, como en el anime.
- **Los pies se quedan en el suelo**: de pie ya no resbalan ni se hunden al mover la cadera; si el peso cambia
  mucho, da un pasito para recolocar el pie, como una persona. Andando, el pie de apoyo no atraviesa el suelo.
- **Movimiento fluido en el escritorio**: la caída, los saltos a una ventana, los paseos y el ir y venir de las
  acciones se veían a tirones (unos 30 cuadros por segundo); ahora van al ritmo de tu pantalla. Sentada sobre una
  ventana que mueves, la sigue con suavidad en vez de a saltos, y la mano llega al punto de una acción sin brincos.
- **Solo el personaje mientras se mueve**: al caer, saltar, pasear, cuando la llevas con el ratón o mientras hace una
  acción, se esconden la barra de botones y los subtítulos. Si tienes el chat abierto, se queda abierto (salvo cuando
  se va a dormir: entonces se cierra). Las tarjetas de permiso y el botón «Parar» siguen a la
  vista.
- **Faldas y vestidos que no atraviesan las piernas**: en todos los modelos (también los tuyos) la ropa con
  físicas choca ahora con los muslos y las espinillas y con el suelo: al recostarse, sentarse o levantar la rodilla,
  la falda cae por encima de la pierna en vez de atravesarla o quedarse tiesa, y la falda y el pelo largo se apoyan en
  el suelo en vez de hundirse.
- **Le entra sueño**: a los 3 minutos sin usar la app se recuesta en el suelo de una de tres maneras, hacia el lado
  izquierdo o el derecho de la pantalla: apoyada sobre un codo (al dormirse se desliza hasta quedar tumbada), sentada
  con las rodillas dobladas (al dormirse abraza las rodillas y apoya la cabeza) o tumbada boca arriba con el móvil
  sobre la cara (al dormirse lo baja al pecho; esta, solo en la ventana normal). En la primera, la pierna de
  abajo va casi estirada y la otra con la rodilla alta y saca una tablet o el móvil para ver algo (la pantalla se ve encendida); al rato le entra sueño, cabecea,
  deja la pantalla sobre el pecho y se duerme, con «Z» que suben. Flotando, antes va andando a la esquina de abajo
  más cercana y se recuesta con la espalda hacia el borde de la pantalla. A veces, en la ventana, se sienta sobre los
  talones a cabecear o se tumba a echar la siesta. En cuanto vuelves se despierta, guarda la pantalla, se levanta y a
  veces se despereza.
- **Puedes pedirle que haga cosas**: «¿puedes bailar?», «salta», «date una vuelta», «estírate», «haz un hechizo»,
  «canta algo», «bebe algo», «haz la V», «saluda», «aplaude», «duérmete»… y lo hace mientras te contesta. Si el
  modelo se olvida de hacerlo, el companion reconoce la petición y lo hace igual.
- **Se entretiene sola**: si pasas un rato (unos 50 s) sin hablarle, escribirle ni pasar el ratón por su ventana, de
  vez en cuando hace algo por su cuenta: baila, salta, da una vuelta, se estira y bosteza, tararea con notas
  musicales, hace un pequeño hechizo con destellos, bebe algo o curiosea a su alrededor. En cuanto vuelves, lo deja.
  Se apaga en Ajustes › Tú y tu personaje › «Se entretiene sola».
- **El rubor sigue la cara**: al girar la cabeza, el rubor de las mejillas se quedaba flotando sobre el pelo. Ahora
  está pegado a cada mejilla, gira con la cara, el pelo que cae delante lo tapa y la mejilla que no se ve no lo enseña.
- **Dedos uno a uno**: cada dedo se mueve por su cuenta y llega a su ritmo (el índice primero, el meñique el
  último); en reposo caen en cascada, como una mano de verdad. Posturas nuevas con cada dedo: mano suave al
  explicar, palma abierta, pinza u «OK» al precisar algo, señalar, puño. Dos gestos nuevos que puede hacer:
  pulgar arriba y la V de la paz junto a la cara.
- **Más gestos en la cara**: con los modelos de VRoid (los incluidos y muchos de los tuyos), cejas, ojos y boca se
  mueven por separado, así que cada emoción tiene su cara propia (ojos alegres con media sonrisa, cejas de pena con
  boca pequeña…). Encima hace microgestos: sube las cejas al recalcar algo, entrecierra los ojos, una sonrisita, a
  veces enseña el colmillo. Los demás modelos siguen con sus expresiones de siempre, también con microgestos.
- **La boca sigue mejor lo que dice**: distingue vocales y consonantes (en p, t, k cierra un instante; en s, f, ch
  deja los dientes juntos), con la técnica de wawa-lipsync (MIT).
- **Triste se le ve la cara**: antes se encorvaba tanto que de frente solo se veía la coronilla.
- **Con zoom, la barra se sigue viendo**: si alejas al personaje con Ctrl + rueda, la barra ya no se queda debajo de la
  barra de tareas; y si lo acercas tanto que los pies salen de la ventana, ya no se queda flotando en el aire. Con
  la ventana pequeña (rueda del ratón), la barra encoge para caber entera, sin cortar los botones de los lados.
- **El pelo y la ropa notan el movimiento de la ventana**: al arrastrarla, cuando anda o cae, se quedan atrás y
  vuelven, como si el cuerpo se moviera de verdad.
- **Cambiar a flotante ya no corta nada**: si está hablando, sigue hablando, y la conversación, el micrófono y
  la cámara siguen igual al pasar a flotante y al volver (antes se abría una página nueva y la respuesta se
  cortaba).
- **El modelo entero al flotar**: nueva opción en Ajustes › Tú y tu personaje, «Desvanecer los pies al flotar».
  Apagada, se ve el personaje completo, sin el degradado de abajo.
- **Cámara libre**: el modelo se gira por completo en horizontal y en vertical, se desplaza con el botón derecho
  y la rueda acerca o aleja hacia donde apunta el ratón. Flotando: botón derecho para girarlo, central para
  desplazarlo y Ctrl + rueda para acercar la cámara. Doble clic vuelve al encuadre de siempre.
- **Tu personaje vive en el escritorio** (modo flotante, nuevo apartado Ajustes › «Escritorio»):
  - te sigue con la mirada y reacciona al pasar el ratón, al tocarla (cabeza o cuerpo) y al arrastrarla;
  - gravedad: si la sueltas en el aire cae a la barra de tareas;
  - pasea de vez en cuando por el borde de abajo;
  - se puede sentar sobre la ventana activa y la sigue si la mueves;
  - cuando le pides algo en una aplicación, va al lado de esa ventana y se la ve trabajando de espaldas
    (teclea, señala, desplaza) y al terminar se da la vuelta y vuelve a su sitio.
  Con un juego o un vídeo a pantalla completa se queda quieta. Las ventanas solo se miran por su posición.
  - Sentada sobre una ventana se pone de costado, con las manos en el borde y la cara hacia ti, para que la ropa no
    se vea rara; andar tiene un ciclo de marcha natural y avanza al ritmo de sus pasos.
  - Transparencia al flotar: elige cuánto se transparenta; con el ratón encima o al agarrarla se ve entera.
- La opción «Desvanecer los pies al flotar» pasa a ese apartado.
- La mirada en vivo sin clave de la nube ya no dice que se agotó la cuota.
- **Personalidades** (nuevo apartado Ajustes › Personalidad): ocho incluidas (De confianza, Pura energía, Ironía
  fina, Corazón tímido, Modo profesional, Calma total, Orgullo y ternura, Caos simpático). «Personalizar» copia
  una para ajustarla (nueve rasgos, forma de hablar, muletillas, gustos, ánimo habitual, emociones y frases de
  ejemplo) y también se puede crear una desde cero. Las respuestas siguen la elegida: reacciona antes de ayudar,
  tiene opiniones y no suena genérica.
- **Estado de ánimo**: las emociones que muestra le dejan un ánimo que dura entre turnos y vuelve poco a poco al
  de siempre de su personalidad. Además nota cuánto hace que no hablabais.
- **Toques por partes del cuerpo**, también en la ventana normal (un clic corto sobre el personaje): cabeza,
  pecho, barriga, cadera, piernas, pies, brazos y manos reaccionan distinto, y al repetir sube de tono (corazones
  grandes en la cabeza; sorpresa, rubor, «no, no» y enfado en el pecho o las piernas; cosquillas en la barriga y
  los pies), según su personalidad.
- **Reacciona a cómo la miras** con la cámara libre: de muy cerca a la cara, al pecho o a las piernas, desde abajo,
  por la espalda o haciéndola girar. A veces te lo dice en voz alta, con su personalidad (Ajustes › Personalidad ›
  «Comentar toques y miradas»; como mucho uno por minuto con la nube).
- **Escribirle flotando**: el botón del teclado abre una cápsula bajo el personaje (Intro envía, Esc la cierra).
- **Hace ella las acciones flotando**: en cada paso al usar una aplicación se coloca para que su mano quede sobre
  lo que pulsa o escribe: de pie, en cuclillas o de rodillas si está abajo, de puntillas si está arriba.
- **Permisos**: «Permitir siempre» también para usar una aplicación, y nueva opción **Acceso total** (Ajustes ›
  Acciones en tu PC) para que no pregunte nunca. Los pasos delicados que no pediste se siguen confirmando.

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
