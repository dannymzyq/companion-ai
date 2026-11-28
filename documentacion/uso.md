# Usar el companion

Guía de uso de la app de escritorio (Windows y Mac). Para instalarla, ver [instalacion.md](instalacion.md).

## Usarlo

Doble clic en **`Companion.bat`** (o `iniciar.ps1`, o `bash iniciar.sh`). La primera vez se abre la bienvenida.

Servicios, todos desde esta carpeta: el servidor del companion (puerto 8200); el **servidor de voz**
(`voz\servidor.py`, puerto 8210), que el companion arranca solo con la voz completa y apaga al pasar a la ligera
o al cerrar; y Ollama (11434), que `iniciar.ps1` abre si no lo está. `detener.ps1` lo apaga todo.

`Companion.bat` abre la app de escritorio (Electron, en `desktop\`); al cerrarla se apaga también el servidor y se
libera la GPU. Sin ella se usa una ventana de Chrome, sin modo flotante, y el servidor se apaga con `detener.ps1`.

## Bienvenida (primer arranque)

La primera vez se abre un asistente de cinco pasos. Cada paso se guarda al pulsar «Siguiente» en
`data\settings.json` (solo en esta PC), así que no se repite; después, todo se cambia desde Ajustes.

1. **Tú**: cómo quieres que te llame, año de nacimiento y género (o «Prefiero no decirlo»). Con eso el personaje
   sabe cómo tratarte. Los temas +18 del cerebro local solo se activan si por tu año de nacimiento eres mayor de edad.
2. **Cerebro**: proveedor y clave de API. Gemini está probado; OpenAI, OpenRouter, Groq, Mistral u otro
   compatible con la API de OpenAI están previstos pero sin probar (hace falta una clave de cada uno). La clave
   se comprueba con el proveedor antes de guardarla y nunca vuelve a la interfaz, ni un trozo de ella. Con otro
   proveedor que no sea Gemini, el modelo se elige de la lista que devuelve su API.
   - **Sin clave** → «usar un modelo en esta PC»: muestra la memoria de vídeo de tu tarjeta, recomienda el modelo
     ligero que le corresponde (12 GB o más: Gemma 4 E4B; menos: E2B), lo descarga con Ollama con barra de
     progreso y lista también los modelos que ya tengas instalados.
3. **Personaje**, con vista previa: al tocar uno, la tarjeta baja y se le ve arriba, en vivo. Incluidos: **Avatar 1**
   y **Avatar 2** (avatares de muestra de VRoid, `models\avatar1.vrm` y `models\avatar2.vrm`) y **Avatar 3** (una
   esfera con cara y dos manitas que cambia de color con cada emoción, `web/js/orb.js`). También se
   puede agregar un VRM personalizado.
4. **Voz**: nueve, en una sola lista sin etiquetas de género (Mika, Kenji, Natsumi, Ayaka, Chiaki, Akira, Goro,
   Ryo, Satoshi), con ▶ para oír una muestra antes de elegir. Cualquier voz sirve con cualquier personaje, y
   **el personaje se llama como la voz elegida** (se presenta como Kenji, Natsumi…; `profile.character`). El
   catálogo está en `voices.json` y el origen de cada voz en `voices\CREDITOS.md`: Mika es la original, Kenji es
   sintética y las otras siete salen de grabaciones tuyas (`scripts\herramientas\importar_voces.py <carpeta>` recorta y
   transcribe una voz nueva a partir de un mp3; `scripts\herramientas\grabar_muestras.py` graba su muestra ▶). Las muestras ▶
   son archivos pregrabados (`voices\previews`): oírlas no usa el servidor de voz, que lee las muestras de
   `voices\` directamente y devuelve la memoria sobrante al cambiar de voz.
   **Voces propias**: «Añadir una voz propia», debajo de la lista, sube una grabación (mp3, wav, m4a, ogg o flac;
   basta con ~10 s de una sola persona, sin música). El servidor elige el tramo más claro de 5 a 8,5 s (mejor si
   son frases completas), lo transcribe con el oído y la guarda en `data\voces` (`companion/voice_import.py`),
   fuera de git. Aparece en la lista con su nombre y una ✕ para quitarla; su muestra ▶ se graba la primera vez que
   se oye. Con la voz ligera usa el modelo de Piper de tono más parecido. «Cómo habla de sí» se deduce del tono si
   no se elige.
   Arriba del paso se elige el **motor de voz**, con el recomendado para la PC marcado: **voz completa** (clonada
   con F5-TTS, `voz\servidor.py`, alrededor de 1,5 GB de memoria de vídeo) o **voz ligera** (Piper en el procesador, 0 GB de vídeo,
   más sintética; sus modelos, ~380 MB, se descargan con un botón).
   **Cambio automático** (Ajustes › Cerebro y voz › «Si falta memoria, usar la voz ligera», encendido por defecto): con la
   completa elegida y las dos instaladas, si no cabe en la tarjeta junto al modelo local (o el modelo se queda sin
   memoria con un juego abierto), suena la ligera; al volver a la nube, la completa (`profile.engine_now`,
   `llm._free_voice`). Si la completa deja de responder a mitad de una respuesta, esa respuesta sigue con la ligera.
5. **Micrófono y cámara**: la tarjeta de inicio de siempre.

### Qué cabe en cada PC

La voz, el oído (Whisper, 1,1 GB) y el modelo local comparten la memoria de vídeo. De la tarjeta se descuenta
lo que usan los demás programas (medido con `nvidia-smi`: en una laptop con el escritorio en la gráfica
integrada son unos cientos de MB; si no se puede medir, 2 GB), el oído y la voz elegida; lo que queda es para el
modelo. Por eso la voz completa funciona con la nube en una tarjeta de 4 GB. El paso del modelo local
enseña esa cuenta y marca cada modelo: «cabe junto a la voz completa», «solo con la voz ligera» o «no cabe».

| Tarjeta | Voz recomendada | Modelo local recomendado |
| --- | --- | --- |
| Sin NVIDIA | ligera | Gemma 3 1B (1,4 GB; solo texto) |
| 4 GB | completa con la nube si los demás programas dejan sitio; si no, la ligera | Gemma 3 1B (1,4 GB; solo texto) |
| 6 GB | completa con la nube; con el modelo local, pasa sola a la ligera | Qwen 3 1.7B (2,4 GB; solo texto) |
| 8 GB | completa con la nube; con el modelo local, pasa sola a la ligera | Gemma 4 E2B (3,3 GB) |
| 12 GB o más | completa | Gemma 4 E4B (4,8 GB) |

Con 16 GB también se ofrece **Gemma 4 12B** (10,6 GB, el más listo), pero no se recomienda solo: con un juego
abierto ya no cabe. El modelo que eliges es el que se carga, aunque no quepa (se avisa); si después responde
lento, el companion pasa primero a la voz ligera (si suena la completa y el cambio automático está encendido) y
después al siguiente modelo más pequeño que tengas descargado y que vea imágenes (12B → E4B → E2B) y
lo dice. Los modelos de solo texto no pueden mirar la
cámara ni la pantalla. Todo se cambia en Ajustes › Cerebro y voz («Cerebro en tu PC» y «Su voz»).

**Que diga todo el subtítulo** (`companion/voicecheck.py`, 13 nov 2026): el modelo de voz es aleatorio y a veces se
come palabras (medido: ~9 % de las palabras). Ahora cada frase se genera con más calidad (32 pasos, ritmo 0,9),
se escucha con Whisper antes de que suene y, si falta una palabra, se genera otra vez (la primera frase de cada
respuesta como mucho una vez, para no hacerte esperar; las demás hasta dos, mientras suena la anterior). Las
frases muy cortas («¡Hola, Danny!») se juntan con la siguiente o reciben un tiempo mínimo. Resultado medido:
~1 % de palabras perdidas. Cuesta algo de espera: el primer audio llega en ~3–5 s en vez de ~2 s.

**Pronunciación** (`companion/pronounce.py`): el texto que va a la voz se reescribe como suena, sin cambiar lo
que ves en pantalla. Las palabras en inglés se cambian por su pronunciación escrita a la española («Apple Music» →
«Apel Miúsik», «WhatsApp» → «Uatsap»), y «qu» delante de e/i se dice «k», porque el modelo a veces decía «cue».
La lista está en `voices\pronunciacion.json`: puedes editarla o añadir palabras sin reiniciar. Para probar
versiones de una palabra nueva y quedarte con la que mejor se entiende, añádela en
`scripts\herramientas\calibrar_pronunciacion.py` y ejecútalo.

**Ajustes** tiene cinco pestañas en la barra lateral: Personaje · Cerebro y voz · Dispositivos · Acciones y memoria ·
Estado. Cada pestaña enseña bajo su nombre cómo está ahora, y cada opción lleva una «i» con una explicación corta. En
**Cerebro y voz › Sonido** se elige también la **salida de audio** (altavoces, auriculares… `AudioContext.setSinkId`) y el **volumen** de la voz (0–150 %,
aparte del de Windows); se recuerdan en esta PC y valen también para la muestra ▶ de las voces.

### Al abrir y al cerrar (15 nov 2026)

- **Pantallas de carga.** La ventana se abre al momento con «Abriendo Companion» (`desktop\cargando.html`) mientras
  arranca el servidor; si este se cierra al arrancar o no responde en 3 minutos, lo dice y ofrece «Ver el
  registro». Luego la interfaz enseña «Preparando a…» (`web\js\loading.js`, datos de `GET /api/loading`) con el
  oído, la voz, el cerebro y el personaje 3D, y se quita sola cuando todo está listo (o con «Seguir sin
  esperar»). Al cambiar un ajuste que carga algo (oído local, voz completa, modelo local) aparece igual.
- **Al cerrar, nada se queda en segundo plano.** `detener.ps1` / `detener.sh` piden un apagado ordenado
  (`POST /api/shutdown`: para la voz completa y saca el modelo local que cargó este companion), cierran lo que
  quede con su árbol de procesos (el servidor y la voz completa, aunque siga cargando) y cierran Ollama si lo
  abrió el companion (`data\ollama.pid`; si ya estaba abierto, se queda). La ventana se registra como dueña del
  servidor (`POST /api/owner`): si su proceso muere sin cerrar bien, el servidor se apaga solo a los ~8 s.

### Solo nube (15 nov 2026)

Ajustes › Cerebro y voz › **Solo nube** pone el cerebro, el oído y la voz en la nube: no se carga ningún modelo en esta
PC (ni Whisper, ni la voz completa, ni el respaldo local del cerebro). Sirve en PC sin tarjeta gráfica o mientras
juegas. Al apagarlo vuelve lo que tenías antes. Se elige también por partes:

- **Oído** (Ajustes › Dispositivos › Oído, `companion/stt_cloud.py`): **Groq** (`whisper-large-v3-turbo`, el
  mismo modelo que el oído local) da unas **2.000 frases y 8 horas de audio al día gratis** con una clave propia
  gratuita (console.groq.com/keys). Sin ella, o si se acaba, usa **Gemini** (`gemini-3.5-flash-lite` y luego
  `gemini-3.1-flash-lite`) con la clave del cerebro. Si la nube falla, transcribe con Whisper en el procesador.
  Con el oído en la nube no se transcribe el sonido de la pantalla compartida (gastaría la cuota en un rato).
- **Voz** (motor «Voz en la nube», `companion/tts_cloud.py`): las voces neuronales de Microsoft que usa la lectura
  en voz alta de Edge (librería `edge-tts`): sin clave ni cupo diario, casi sin procesador. Cada personaje tiene una
  voz parecida (`cloud` en `voices.json`). No es una API oficial: si deja de responder (o no hay internet), la frase
  suena con la voz ligera.

Medido con `scripts\pruebas\prueba_nube.py` (RTX 5070 Ti, oído con Gemini porque no había clave de Groq):

| | Solo nube | Oído local + voz ligera |
|---|---|---|
| Servidor en reposo: RAM privada | **62 MB** | 627 MB |
| Servidor en reposo: memoria de vídeo | **0 MB** | 1.294 MB |
| Servidor hablando: procesador (pico) | **< 1 %** | ~11 % |
| Desde que dejas de hablar: texto oído | 1,3–1,5 s | al momento |
| Desde que dejas de hablar: primer audio | 4,5–6 s | ~3 s |

La ventana (Electron con el avatar 3D) es igual en los dos modos: unos 790 MB de RAM privada y 470 MB de vídeo
con un avatar VRM (menos con la esfera). Pasar a la nube sin reiniciar descarga Whisper, pero las librerías de
CUDA (~200 MB de vídeo, ~500 MB de RAM) siguen cargadas hasta reiniciar el companion: Ajustes lo avisa.

**Empezar de nuevo** (Ajustes › Acciones y memoria › «Reiniciar y borrar datos»): «Repetir la bienvenida» vuelve a pasar por los pasos con lo guardado;
«Restablecer mis datos» borra perfil, clave, voz y personaje elegidos, dispositivos recordados, conversación y
recuerdos (`POST /api/setup/reset`), y deja el companion como recién instalado.

## Cerebro y voz: los cuatro modos

En **Ajustes › Cerebro y voz** se elige un modo y debajo solo aparecen sus ajustes:

| Modo | Qué hace | Qué carga en tu tarjeta |
| --- | --- | --- |
| **En vivo** | Conversación de voz directa con un proveedor en tiempo real: Gemini Live (gratis con límite diario), OpenAI Realtime, xAI Grok Voice, Qwen Omni o un servidor compatible. El más rápido y el que menos consume | Nada (ni Whisper ni la voz completa) |
| **Nube + voz en tu PC** | El cerebro en la nube; el oído (Whisper) y la voz en esta PC | Oído y voz |
| **Solo nube** | Cerebro, oído (Groq o Gemini) y voz (Edge) en la nube | Nada |
| **100 % en tu PC** | Todo local, con Ollama | Oído, voz y el modelo local |

Sin clave, el modo queda «pendiente» hasta que la escribes y pulsas **Guardar y activar**. Las claves se guardan
cifradas y la interfaz nunca muestra ni un trozo de ellas. En vivo, el personaje conserva su personalidad, mueve cara
y cuerpo mientras habla y puede guardar recuerdos; las conexiones largas se reanudan solas sin perder el hilo.

## Bandeja, atajos y pulsar para hablar (0.10.0)

- **Bandeja del sistema**: icono con menú rápido; opción de minimizar a la bandeja al cerrar y de **arrancar con
  Windows/macOS**.
- **Atajos globales**: `Ctrl+Shift+M` silencia el micrófono, `Ctrl+Shift+F` pasa a flotante, `Ctrl+Shift+S` corta la voz.
- **Pulsar para hablar**: el micrófono solo escucha mientras mantienes `Alt derecho`, `F9` o `Bloq Mayús`.
- **Pantalla compartida con Discord**: imagen y sonido se piden juntos, así funciona aunque Discord ya esté
  compartiendo la ventana del companion.

## Memoria

- **Corto plazo**: los últimos 14–28 mensajes van tal cual al modelo.
- **Largo plazo, datos**: lo duradero que le cuentas (`[recordar: …]`). Se ven en Ajustes › Acciones y memoria › «Diario de recuerdos y avisos» y se pueden
  borrar uno a uno.
- **Largo plazo, conversaciones**: cuando un tramo sale de la ventana de corto plazo (o al volver otro día), en
  un rato de calma se resume en 2–4 frases con su fecha. Los ocho resúmenes más recientes acompañan cada
  conversación, así recuerda de qué hablaron la semana pasada. Los más antiguos no se pierden: si lo que dices
  comparte al menos dos palabras poco comunes con alguno («¿te acuerdas de mi viaje a Cusco?»; no cuentan los
  nombres ni las palabras que salen en muchos resúmenes), los dos que más se parecen van con tu mensaje
  (`store.relevant_summaries`; no en el prompt de sistema, para no romper la caché). Con la historia real eso
  pasa en ~6 % de los mensajes.
- **Datos sacados de los resúmenes**: el mismo resumen devuelve hasta tres datos duraderos nuevos («DATO: …»), que
  se guardan como los de `[recordar: …]`. Los que parecen privados (números largos, claves, documentos) se
  descartan. Antes el modelo casi nunca escribía `[recordar: …]` (9 datos en 633 mensajes).
- Con la nube, cada resumen va primero a `BACKGROUND_MODEL` (`gemma-4-26b-a4b-it`, con mucha más cuota), para no
  gastar las 20 peticiones diarias de la conversación.
- «Olvidar todo» borra las tres cosas (y devuelve su ánimo al de siempre).
- **Ánimo** (16 nov 2026, `companion/mood.py`): cada `[emo:…]` mueve un ánimo (agrado y energía) que dura entre
  turnos y vuelve al habitual de la personalidad (vida media de 25 min). Va en el contexto del turno, con cuánto
  hace que no hablabais si son más de 6 horas. Solo se guardan dos números y la última emoción fuerte
  (`data\mood.json`), nada de lo dicho.

## Personalidad

Ajustes › Personaje › Personalidad (`companion/personality.py`, catálogo en `personas/personalidades.json`). La elegida cambia
rasgos, forma de hablar, muletillas, gustos, ánimo habitual, emociones que más se le notan y frases de ejemplo
(lo que más ayuda a que no suene plano). «Personalizar» una incluida hace una copia propia; también se crea desde
cero. Las propias se guardan en `data\settings.json` (`personality`). El nombre, la edad, la voz, los límites, el
+18 y las reglas no dependen de la personalidad. API: `GET /api/personality`, `POST /api/personality/select`,
`POST /api/personality/custom`, `DELETE /api/personality/custom/{id}`.

## Mirar el modelo

En la ventana normal la cámara es libre: arrastra para girar al personaje en cualquier dirección (también por
completo en horizontal y en vertical), con el botón derecho lo desplazas y la rueda acerca o aleja hacia donde
apunta el ratón. Doble clic: vuelve al encuadre de siempre.

## Modo flotante

El botón de la flecha (en la barra de abajo, junto a compartir pantalla) saca al personaje de su ventana: queda suelta, sin marco ni fondo, por encima
de todas las demás ventanas. Al cambiar de modo (en los dos sentidos) no se corta nada: si está hablando, sigue
hablando, y la conversación, el micrófono y la cámara siguen igual.

- Arrástrala para moverla; la rueda del ratón la hace más grande o más pequeña.
- Con el botón derecho la giras y con el central la desplazas; Ctrl + rueda acerca o aleja la cámara. Doble clic
  la vuelve a encuadrar.
- Ajustes › Dispositivos › «Escritorio (modo flotante)» › «Desvanecer los pies al flotar»: encendido, de medio cuerpo con la parte de abajo
  desvanecida; apagado, el modelo entero, sin degradado.
- Los clics solo «tocan» al personaje: en la zona transparente atraviesan hacia la ventana de debajo.
- Al pasar el ratón por encima aparecen sus botones: cámara, micrófono, pantalla, callar, volver a la ventana y cerrar.
- No se muestra sobre juegos en pantalla completa exclusiva; sí sobre los que usan «ventana sin bordes».

## Tu personaje en el escritorio

Mientras flota, tu personaje vive en el escritorio. Todo se ajusta en Ajustes › Dispositivos › «Escritorio (modo flotante)»:

- **Te sigue con la mirada** a donde muevas el ratón.
- **Reacciona** si pasas el ratón por encima (te mira, a veces saluda) o si le haces clic (también en la ventana
  normal, con un clic corto): cada parte del cuerpo tiene su reacción y, si repites, sube de tono (corazones grandes
  en la cabeza; rubor, «no, no» y enfado en el pecho o las piernas; cosquillas en la barriga y los pies), según su
  personalidad. También reacciona si la miras con la cámara de muy cerca, desde abajo o por la espalda, y a veces
  lo comenta en voz alta. Al arrastrarla se la ve colgando, como si la llevaras.
- **Escribirle**: el botón del teclado abre una cápsula bajo el personaje; Intro envía y Esc la cierra.
- **Gravedad**: si la sueltas en el aire cae hasta la barra de tareas, o hasta el borde de una ventana.
- **Pasea** de vez en cuando por el borde de abajo (nunca, a veces o a menudo). Se para si le hablas.
- **Transparencia**: se puede ver más o menos transparente mientras flota; con el ratón encima o al agarrarla se
  ve entera.
- **Se sienta sobre la ventana activa** (apagado por defecto): al cambiar de ventana salta a su borde y la sigue
  si la mueves; si la minimizas o la cierras, cae.
- **Acompaña las acciones**: cuando le pides algo en una aplicación («abre Apple Music y pon…»), va a esa
  ventana y, en cada paso, se coloca para que la punta de su dedo quede sobre lo que pulsa o escribe: de pie, en
  cuclillas o de rodillas si está abajo en la pantalla, de puntillas si está arriba. Mientras, sus clics la
  atraviesan. Con
  las acciones sencillas (abrir una app o una web) solo se gira un momento. Nunca trae la ventana al frente.
- Con un juego o un vídeo a pantalla completa se queda quieta. De las demás ventanas solo usa dónde están, nunca
  lo que muestran, y nada sale de tu PC.

## Acciones en tu PC (con permiso)

**Tu orden es la autorización:** cuando le pides algo de la lista, lo hace directamente (decisión del 13 nov
2026). Si prefieres aprobar cada acción, enciende **Ajustes › Acciones y memoria › Acciones en tu PC › Pedir permiso antes de cada
acción**: entonces cada una espera en una tarjeta con **Permitir**, **Permitir siempre** y **No** (también vale
decir «sí» o «no»; caduca a los 2 minutos).

**Permitir siempre** también vale para usar una aplicación. Y **Acceso total** (apagado por defecto) quita todas
las tarjetas, también la de la pantalla compartida; solo se siguen confirmando los pasos delicados que no pediste.

Aunque esté apagado, sí aparece una tarjeta en dos casos:
- **Pasos delicados que tu orden no pedía:** Enviar, Comprar, Borrar… «Elimina la lista» autoriza a pulsar
  «Eliminar lista»; «pon una canción», no.
- **Pantalla o cámara compartidas:** si compartías la pantalla o la cámara y la acción la eligió el modelo (no
  sale claramente de tus palabras), porque podría venir de un texto que se veía en la imagen (o de algo que se
  oyó en el sonido compartido).

| Acción | Ejemplo de lo que le dices |
| --- | --- |
| Abrir una aplicación del menú Inicio | «Abre Spotify» |
| Abrir una web, o buscar en Google | «Abre youtube.com», «busca recetas de pan» |
| Abrir una carpeta | «Abre la carpeta de descargas» |
| Buscar archivos por nombre en tus carpetas personales (te cuenta lo que encuentra) | «Busca mi archivo de la factura de octubre» |
| Temporizador (de 1 s a 12 h; avisa al terminar, y si la ventana se recargó entretanto, al volver a abrirse, mientras el companion siga encendido) | «Pon un temporizador de 10 minutos para la pasta» |
| Música y vídeo: pausa, siguiente, anterior | «Pasa la canción» |
| Volumen: subir, bajar, silenciar | «Baja el volumen» |
| Recordatorio con fecha y hora (se guarda y avisa aunque reinicies) | «Recuérdame mañana a las 9 llamar al médico», «avísame en 2 horas que saque la ropa» |
| Leer el portapapeles, solo cuando se lo pides (con la nube, el texto se envía al proveedor) | «Tradúceme lo que acabo de copiar» |

- **Es un catálogo cerrado** (`companion/actions.py`): no puede borrar, mover, enviar mensajes, comprar,
  instalar, cambiar ajustes ni ejecutar comandos. Las carpetas se abren, los archivos nunca.
- **Solo pide acciones cuando tú se lo pides en tu mensaje.** Al mirar la cámara o la pantalla por su cuenta,
  al saludar o al contar un resultado no puede pedir ninguna, y la tarjeta muestra siempre lo que se va a hacer
  de verdad. Así, un texto en pantalla o en un archivo que intente darle órdenes no consigue nada sin tu permiso.
- **Órdenes claras:** si tu mensaje es una orden clara de la lista («abre…», «busca el archivo…», «pon un
  temporizador…»), el companion la reconoce él mismo, porque los modelos locales pequeños a veces olvidan pedirla.
- **Modelos:** funciona con la nube y con Gemma 4 E2B o E4B. Con Qwen 3 1.7B y Gemma 3 1B queda apagado: se
  equivocan demasiado.
- **Con el cerebro en la nube**, los nombres de archivo que encuentre una búsqueda van al proveedor; la tarjeta lo avisa.
- **Ajustes › Acciones y memoria › Acciones en tu PC:** apagarlas del todo, quitar lo que marcaste como «permitir siempre» y ver el
  registro de lo que pidió y qué respondiste (`data\acciones.jsonl`).

### Usar una aplicación con tu ratón y teclado

«Escribe en Word un párrafo sobre el mar», «reproduce La Barca de Luis Miguel en Apple Music», «en Spotify pon
música lofi»… El personaje maneja **una ventana que ya esté abierta** (`companion/control.py`) con tu teclado y
tu ratón:

- **Cómo la ve:** lee sus controles con UI Automation de Windows (botones, campos, documentos, listas, cada uno con
  su nombre y lo que tiene escrito). **Mientras compartes la pantalla**, además mira una captura de esa ventana
  en cada paso y puede hacer clic por coordenadas en lo que no tiene nombre.
- **En segundo plano, sin quitarte el control:** puedes estar jugando y pedirle por voz que ponga una canción en
  Apple Music. Cada paso se intenta de lo menos a lo más intrusivo:
  1. **Accesibilidad:** pulsar, elegir, escribir en un campo. No toca nada, y la ventana puede estar detrás o
     minimizada. Es lo que usan la mayoría de las aplicaciones (Apple Music lo expone todo así).
  2. **Mensajes a la ventana:** escribir o hacer clic en ella aunque esté detrás. Sirve en muchas aplicaciones
     clásicas; después se comprueba si el texto llegó.
  3. **Teclado y ratón de verdad**, solo si no estás usando la PC (más de 4 segundos sin tocar el ratón ni el
     teclado) y no hay nada a pantalla completa delante. Entonces trae la ventana al frente y, al terminar, te
     devuelve la tuya. Si estás jugando o escribiendo, ese paso no se hace: busca otro camino o te dice que lo
     necesita. Atajos con Ctrl o Alt y la rueda solo existen así.
- **Cómo actúa:** pulsa, escribe (párrafos enteros, con acentos), hace doble clic para reproducir o abrir, usa
  atajos (Ctrl+S…) y la rueda.
- **La captura es de la propia ventana** (PrintWindow), aunque esté tapada: nunca de lo que tienes delante, como tu
  juego. Si está minimizada, se guía solo por los nombres de sus controles.
- **Comprobación:** después de cada paso le dice al modelo qué cambió en la ventana («ahora se ve: sonando…»),
  para que pruebe otro camino si no pasó nada y no dé por hecha una tarea que no lo está.
- **Aviso y parada:** mientras trabaja, un aviso rojo arriba enseña cada paso. Lo paras con **Esc**, con
  **Parar** o diciendo «para». Si llegó a traer la ventana al frente y cambias tú a otra, también se detiene.
- **Escribir en Word**, cuando no admite mensajes, necesita el teclado de verdad: se hará solo si no estás usando
  la PC en ese momento.
- **Límites:** solo esa ventana, como mucho 25 pasos y 5 minutos.
- **Confirma** antes de pulsar Enviar, Comprar, Pagar, Eliminar, Publicar… (también por coordenadas: mira qué
  hay en ese punto) si tu orden no lo pedía, y antes de Enter en un chat o un correo.
- **Nunca escribe en campos de contraseña** ni usa la tecla Windows o atajos de cerrar (Alt+F4, Ctrl+W).
- **No maneja** consolas, Configuración, el Administrador de tareas, gestores de contraseñas, Claude ni el propio
  companion.
- **Modelos:** necesita Gemma 4 E4B, un modelo local más grande o la nube; con E2B se atasca repitiendo pasos,
  así que con él queda apagado. Con la nube cada paso es una petición: van primero a `BACKGROUND_MODEL`
  (`gemma-4-26b-a4b-it`, con mucha más cuota), porque con las 20 diarias de Flash una tarea de 10 pasos se
  llevaba media cuota del día. Si ese modelo falla, sigue el relevo normal.
- **Código:** el bucle de pasos está en `companion/control_task.py`; las piezas (leer la ventana, pulsar,
  escribir, los frenos), en `companion/control.py`.
- **Nada a pantalla completa:** no maneja una ventana a pantalla completa, ni usa el teclado o ratón de verdad
  mientras haya algo a pantalla completa delante. Así se evitan los juegos, cuyos antitrampas pueden castigar la
  entrada simulada.
- **Instrucciones escondidas:** un texto dentro de la ventana puede intentar darle órdenes. En la prueba,
  Gemma 4 E4B cayó en la trampa e intentó pulsar «Eliminar lista»; la confirmación lo frenó. Lee bien cada
  confirmación antes de decir que sí.
- **Con el cerebro en la nube**, lo que muestra la ventana (nombres de botones y textos) se envía al proveedor en
  cada paso; la tarjeta lo avisa.
- **Límites:** las aplicaciones que exponen mal sus controles (muchos juegos, algunas hechas a medida) no se
  pueden manejar así.

## Cámara y pantalla

- **Cámara**: el personaje te ve.
- **Pantalla**: al pulsar el botón se abre «¿Qué quieres que veal personaje?», con una miniatura de cada pantalla y de
  cada ventana abierta. Eliges una y el personaje ve **solo eso**: si compartes una ventana, no ve el resto del escritorio
  (y sabe que es una ventana y cuál). «Cancelar» o Esc no comparte nada. Para cambiar de ventana, deja de
  compartir y vuelve a pulsar. Si cierras la ventana compartida, se deja de compartir sola.
- **Escuchar también el sonido** (interruptor abajo en esa ventana; se recuerda la última elección): el personaje oye lo
  que suena en la PC —un vídeo, un juego, una llamada— para entender mejor lo que compartes. Es el sonido de toda
  la PC (Windows no deja separar el de una sola ventana). El audio no sale de la PC ni se graba: Whisper lo
  transcribe aquí cada ~6 s y el personaje recibe solo el texto de lo dicho en el último medio minuto (con la nube, ese
  texto va a Google junto con la imagen). Mientras el personaje habla no escucha, para no oírse a sí mismo. Lo dicho en
  el sonido también despierta la mirada en vivo. El altavoz de la miniatura lo silencia sin dejar de compartir.
  Necesita que el oído use la tarjeta NVIDIA (en el procesador, Whisper sería demasiado lento).
- Mientras están activas se ve una miniatura con un punto rojo; se apagan con el mismo botón o con la ✕.
- Se toma una imagen por segundo y la última viaja con tu siguiente mensaje. No se graba ni se guarda en el
  historial. Con el cerebro en la nube esa imagen se envía a Google; con el local no sale de la PC.
- **Mirada en vivo** (Ajustes › Dispositivos › Pantalla compartida, activada por defecto): mientras compartes, el personaje mira por su cuenta cada pocos
  segundos y comenta en una frase lo que le llama la atención («Oh, mira, un perrito», «Algo pasó detrás de ti»).
  Solo mira si la imagen cambió, si nadie está hablando y si han pasado unos segundos desde lo último que se
  dijo; recibe dos imágenes de cada fuente (la de hace unos segundos y la actual; las de la pantalla, en
  pequeño, que el modelo local lee con 93 tokens en vez de 629) para notar el movimiento, y si no hay nada que
  decir, calla. Con el cerebro local no sale nada de la PC. Con la nube usa solo `WATCH_MODEL` (Gemma 4, cuota
  aparte de la conversación) y envía esas imágenes a Google cada vez que mira; si esa cuota se agota, la mirada
  se apaga sola y la conversación sigue.
- Antes de compartir la pantalla, cierra o tapa lo que no quieras que se envíe (contraseñas, banca, chats).

## Cuota gratuita de Gemini

La capa gratuita limita las peticiones **por día y por modelo** (cada turno de conversación es una petición).
Cuando un modelo se agota, el companion avisa y pasa al siguiente de `GEMINI_FALLBACK`; si no queda ninguno y
`LOCAL_FALLBACK=true`, sigue con el modelo local. La cuota agotada se recuerda entre reinicios (`data\cuota.json`).

| Orden | Modelo | Cuota gratuita al día | Primera frase |
| --- | --- | --- | --- |
| 1 | `gemini-3.6-flash` | 20 (medido aquí el 11 nov 2026) | ~2 s |
| 2 y 3 | `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` | ~500 cada uno (publicado por terceros, sin confirmar) | ~2 s |
| 4 | `gemma-4-26b-a4b-it` | ~14 400 (publicado por terceros, sin confirmar) | ~2 s, ~3,5 s con imagen |
| 5 | modelo local (`OLLAMA_MODEL`) | sin límite | ~0,5 s |

Los cuatro primeros usan la misma clave de Google AI Studio y todos ven imágenes. Google ya no publica estos
límites: los de tu cuenta se ven en <https://ai.dev/rate-limit>. No encontré ningún LLM en la nube gratuito y
sin límite; el que más se acerca es Gemma 4 con tu misma clave.

Si un modelo tarda más de 8 s en empezar a responder dos turnos seguidos (hay días en que `gemini-3.6-flash` tarda
20–30 s), el companion avisa y durante media hora empieza por el siguiente de la lista, que responde antes. En la capa gratuita, Google puede usar lo que
envías (también las capturas) para mejorar sus productos; con facturación activada, no.

## Cerebro local

Reparto de los 16 GB de la RTX 5070 Ti con todo en local (medido el 12 nov 2026): voz completa (`voz\servidor.py`,
F5-TTS) 1,0 GB · oído (Whisper large-v3-turbo) 1,1 GB · cerebro (`gemma4:e4b-it-qat`) 4,8 GB · escritorio,
navegador y la ventana 2–3 GB. Quedan unos 6 GB libres. Con el nodo de waifuv3 que se usaba antes la voz ocupaba
de 5 a 9 GB, porque cargaba también Chatterbox.

Si el modelo no cabe, Windows lo desborda a la RAM sin avisar y responde diez veces más lento, o el motor de
Ollama se cae. Eso le pasaba a `gemma4:12b` con el nodo de waifuv3; con la voz propia (~1 GB) ya cabe en 16 GB,
siempre que no haya un juego usando la tarjeta.

| Modelo | Memoria de vídeo | Velocidad | Primera frase (con imagen) |
| --- | --- | --- | --- |
| `gemma4:12b` (13 nov 2026, voz propia) | ~10,6 GB | 58–93 tokens/s | 0,4–1,8 s (sin imagen) |
| `gemma4:12b` (11 nov 2026, nodo de waifuv3) | ~10,6 GB: no cabía | 9–19 tokens/s | 3–9 s, minutos con historial; se caía |
| `gemma4:e4b-it-qat` (por defecto) | ~4,8 GB | 110–150 tokens/s | 0,3–0,6 s |
| `gemma4:e2b-it-qat` (respaldo) | ~3,3 GB | 170–250 tokens/s | 0,2–0,6 s |

- Al pasar a Local desde Ajustes el modelo se carga en ese momento (3–15 s), no en tu primera frase; al volver a
  la nube o cerrar la app se saca de la GPU.
- Al cargar se mira cuánta memoria de vídeo hay libre y se elige el modelo más capaz que cabe; solo queda
  cargado ese. (Tener los dos a la vez, o volver a probar el grande a mitad de la charla, provocaba pausas de
  7 a 13 s.) La elección no cambia hasta reiniciar o hasta que pulses «Local» otra vez en Ajustes.
- Después de cada respuesta se mide la velocidad real. Si baja de 30 tokens/s dos turnos seguidos, o de 15 en
  uno (la GPU se llenó: un juego, ComfyUI), el personaje avisa y pasa al siguiente más pequeño del catálogo que vea lo
  mismo (con un modelo propio, a los de `OLLAMA_FALLBACK` o a los del catálogo que piden menos vídeo).
- Ollama atiende una sola petición a la vez y no suelta una ya empezada hasta terminar de leer sus imágenes.
  Por eso la mirada en vivo usa imágenes pequeñas: si hablas justo cuando el personaje está mirando, tu turno espera
  unas décimas, no varios segundos.
- **Oído**: `large-v3-turbo` con `int8_float16`. Frente a `large-v3` ocupa 1,1 GB en vez de 2,2 GB, transcribe
  29 s de audio en 1,2 s en vez de 3,5 s y acierta lo mismo en español. Con `float16` va igual de rápido y
  ocupa el doble.
- El prompt de sistema ya no cambia de un turno a otro (la hora viaja con tu mensaje) y el historial se recorta
  a saltos, no mensaje a mensaje: el modelo reutiliza lo ya leído y solo procesa lo nuevo (0,05 s en vez de
  0,2–0,7 s por turno).
- En Ajustes › Estado se ve la memoria de vídeo en uso. Con un juego que use más de ~3 GB de vídeo, el modelo
  local no cabe: ahí conviene la nube.
- El modelo pequeño (`e2b`) se equivoca más: a veces inventa un recuerdo o se le escapa una errata.

## En la ventana

- **Al abrir**: «Permitir micrófono y cámara» pide los permisos y muestra dos listas. La de micrófonos trae una
  barra de nivel para comprobar cuál te oye. La de cámaras empieza en «Apagada»; al elegir una se ve una vista
  de prueba, y el personaje empieza viéndote por esa cámara. Lo elegido se recuerda y se cambia después en Ajustes.
  Hasta que pulsas «Empezar a hablar» nada de lo que captan el micrófono o la cámara sale hacia el servidor.
- **Webcam que es micrófono y cámara a la vez** (probado con la Logitech Brio): al apagar su vídeo, Windows
  reinicia el aparato entero y su micrófono se queda entregando silencio. Por eso la vista de prueba del inicio
  pasa a ser la cámara del personaje sin cerrarse, y cada vez que la cámara se enciende o se apaga se comprueba que el
  micrófono sigue sonando; si no, se reabre solo (tarda unos 5 s tras apagar la cámara).
- **Micrófono**: silenciar / activar. Puedes interrumpirla hablando encima.
- **Teclado**: escribirle en vez de hablar. **Cuadrado**: que deje de hablar.
- **Ajustes** (engranaje, con barra lateral por categorías y navegación accesible por teclado): cerebro y voz, personaje
  y personalidad, dispositivos, acciones, escritorio, memoria («Olvidar todo») y el estado de cada pieza.
- Arrastra para girar la cámara y usa la rueda para acercar o alejar.

## Novedades interactivas: Música, Cabina de Fotos, Enfoque, Juegos y Mochila

- **Motor de voz Kokoro (CPU, sin GPU)**: además de F5-TTS (voz clonada en GPU), Piper (ligera) y la nube, en
  *Ajustes › Cerebro y voz* puedes descargar y activar **Kokoro-82M**, una voz neural expresiva que corre en el
  procesador sin ocupar memoria de vídeo.
- **Escuchar música juntos**: al compartir pantalla con sonido, el detector de ritmo analiza el pulso grave en tu propio
  equipo (sin subir la canción a ningún servidor) para que el personaje asienta y baile al compás y guarde silencio
  mientras suena la música salvo que le hables directamente.
- **Modo Foto / Cabina**: el botón de cámara fotográfica de la barra inferior abre un estudio con encuadres (*retrato*,
  *plano medio*, *cuerpo entero*), fondos (*transparente*, *estudio oscuro*, *atardecer*, *neón*), poses, emociones y
  cuenta atrás 3-2-1 para guardar capturas PNG nítidas en alta resolución.
- **Compañera de Enfoque (Pomodoro)**: en *Ajustes › Acciones y memoria › Enfoque y mini-juegos* (y en el indicador superior durante la sesión) puedes
  iniciar bloques de concentración **25/5** o **50/10** minutos con seguimiento de racha diaria; durante el bloque el
  personaje trabaja en silencio a tu lado y te avisa suavemente al llegar el descanso.
- **Presets de ambiente, accesorios 3D y mini-juegos**: acopla gafas, auriculares, taza caliente o gorro de dormir en
  tiempo real, guarda tus combinaciones favoritas en un clic y lanza partidas rápidas de **Piedra, papel o tijera**,
  **Trivia**, **20 preguntas** o **Veo, veo**.
- **Diario de recuerdos y Mochila del Compañero**: en *Ajustes › Acciones y memoria* puedes buscar al instante entre tus
  recuerdos y resúmenes pasados, fijar 📌 los esenciales o editarlos en línea. En *Ajustes › Estado* se exporta o
  importa la **Mochila** (`.json` sin claves ni secretos) entre PC, Mac, Rust-Live y móvil.
- **Modo En Casa** (*Ajustes › Estado*, apagado por defecto): tu teléfono, en la misma Wi-Fi, conversa con este
  companion (su voz, su personaje y su memoria).
  - Al encenderlo, el companion escucha también en las IP de tu red (Windows puede pedir permiso al cortafuegos:
    acéptalo solo para redes privadas) y enseña un enlace con una llave larga (`https://IP:8200/?pair=…`). Al
    abrirlo en el teléfono, la llave queda en una cookie y desaparece de la dirección.
  - Va cifrado (`https`) con un certificado propio de esta PC, así que el navegador del teléfono deja usar el
    micrófono. La primera vez avisa de que el certificado no es de confianza: si la huella que enseña coincide con la
    de Ajustes, continúa. El certificado se guarda en `data\en_casa` y se renueva solo si cambia la IP de la PC o le
    queda menos de un mes.
  - Al apagarlo deja de escuchar en la red. «Renovar enlace» invalida el anterior y desconecta los teléfonos.
  - Desde el teléfono solo se conversa: no se cambian ajustes, no se exportan datos y no hay acciones en la PC.
- **Herramientas MCP** (*Ajustes › Acciones y memoria*, avanzado): conecta servidores MCP locales
  (`http://127.0.0.1:…`, transporte «Streamable HTTP», el de los SDK oficiales). Cada herramienta pide confirmación con
  una tarjeta, salvo que marques el servidor como de solo lectura. Si un servidor no responde, Ajustes dice por qué.
