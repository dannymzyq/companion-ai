# Companion PC

Mika como asistente personal en tu PC: le hablas como en una llamada y ella responde con su voz,
se mueve y reacciona. Nació de waifuv3, pero ya no depende de él: todo vive en esta carpeta y corre en esta PC,
salvo el cerebro, que puede estar en la nube.

```
micrófono ─► detección de voz (Silero) ─► Whisper (GPU) ─► LLM ─► frases + etiquetas ─► voz de Mika ─► altavoces
                                                           │                        (voz\servidor.py o Piper)
                                              Gemini (nube) u Ollama (local)                     │
                                                                                 avatar 3D: boca, emoción, gestos
```

Solo el **texto** de la conversación sale de la PC (y solo con el cerebro en la nube). La voz, el oído,
el historial y los recuerdos se quedan aquí.

## Instalar

Un solo comando deja todo dentro de esta carpeta (lo que ya está, se salta):

```
powershell -ExecutionPolicy Bypass -File instalar.ps1        # Windows
bash instalar.sh                                             # Git Bash (llama al anterior), Linux o macOS
```

| Qué | Dónde | Tamaño |
| --- | --- | --- |
| uv y Python 3.13 propios | `runtime\` | ~0,1 GB (más la caché de descargas, que se puede borrar: `runtime\cache`) |
| Entorno del companion | `.venv` | 2,3 GB |
| Librerías 3D y app de escritorio (Electron) | `web\vendor`, `desktop\electron` | 0,3 GB |
| Oído: Whisper large-v3-turbo | `models\whisper` | 1,5 GB |
| Voz ligera: Piper (procesador) | `models\piper` | 0,4 GB |
| Voz completa: PyTorch + F5-TTS y su modelo (solo con tarjeta NVIDIA) | `voz\.venv`, `voz\modelos` | 4,9 GB |
| Cerebro local: Ollama y el modelo recomendado para la tarjeta | programa del sistema (lo único fuera de la carpeta) | 1–6 GB |

Opciones: `-Voz auto|completa|ligera|ambas` (auto: según la tarjeta), `-SinOllama` (solo cerebro en la nube),
`-SinModeloLocal`, `-NoRehacer` (no rehace un `.venv` creado con un Python de fuera; rehacerlo detiene el
companion). En bash: `--voz=…`, `--sin-ollama`, `--sin-modelo-local`, `--instalar-ollama`.
Probado en Windows 11; la parte de Linux y macOS de `instalar.sh`/`iniciar.sh` está escrita pero sin probar
(allí no hay app de escritorio: se abre en el navegador).

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
   se comprueba con el proveedor antes de guardarla y nunca vuelve a la interfaz (solo sus cuatro últimos
   caracteres). Con otro proveedor que no sea Gemini, el modelo se elige de la lista que devuelve su API.
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
   sintética y las otras siete salen de grabaciones tuyas (`scripts\importar_voces.py <carpeta>` recorta y
   transcribe una voz nueva a partir de un mp3; `scripts\grabar_muestras.py` graba su muestra ▶). Las muestras ▶
   son archivos pregrabados (`voices\previews`): oírlas no usa el servidor de voz, que lee las muestras de
   `voices\` directamente y devuelve la memoria sobrante al cambiar de voz.
   Arriba del paso se elige el **motor de voz**, con el recomendado para la PC marcado: **voz completa** (clonada
   con F5-TTS, `voz\servidor.py`, alrededor de 1,5 GB de memoria de vídeo) o **voz ligera** (Piper en el procesador, 0 GB de vídeo,
   más sintética; sus modelos, ~380 MB, se descargan con un botón).
5. **Micrófono y cámara**: la tarjeta de inicio de siempre.

### Qué cabe en cada PC

La voz, el oído (Whisper, 1,1 GB) y el modelo local comparten la memoria de vídeo. De la tarjeta se descuentan
unos 2 GB del escritorio, el oído y la voz elegida; lo que queda es para el modelo. El paso del modelo local
enseña esa cuenta y marca cada modelo: «cabe junto a la voz completa», «solo con la voz ligera» o «no cabe».

| Tarjeta | Voz recomendada | Modelo local recomendado |
| --- | --- | --- |
| Sin NVIDIA o 4 GB | ligera | Gemma 3 1B (1,4 GB; solo texto) |
| 6 GB | ligera (completa si el cerebro es la nube) | Qwen 3 1.7B (2,4 GB; solo texto) |
| 8 GB | ligera (completa si el cerebro es la nube) | Gemma 4 E2B (3,3 GB) |
| 12 GB o más | completa | Gemma 4 E4B (4,8 GB) |

Con 16 GB también se ofrece **Gemma 4 12B** (10,6 GB, el más listo), pero no se recomienda solo: con un juego
abierto ya no cabe. El modelo que eliges es el que se carga, aunque no quepa (se avisa); si después responde
lento, el companion pasa al siguiente más pequeño que tengas descargado y que vea imágenes (12B → E4B → E2B) y
lo dice. Los modelos de solo texto no pueden mirar la
cámara ni la pantalla. Todo se cambia en Ajustes › Cerebro › «Modelo local» y Ajustes › Voz.

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
`scripts\calibrar_pronunciacion.py` y ejecútalo.

**Empezar de nuevo** (al final de Ajustes): «Repetir la bienvenida» vuelve a pasar por los pasos con lo guardado;
«Restablecer mis datos» borra perfil, clave, voz y personaje elegidos, dispositivos recordados, conversación y
recuerdos (`POST /api/setup/reset`), y deja el companion como recién instalado.

## Memoria

- **Corto plazo**: los últimos 14–28 mensajes van tal cual al modelo.
- **Largo plazo, datos**: lo duradero que le cuentas (`[recordar: …]`). Se ven en Ajustes › Memoria y se pueden
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
- «Olvidar todo» borra las tres cosas.

## Modo flotante

El botón de la flecha (arriba a la derecha) saca a Mika de su ventana: queda sola, sin marco ni fondo, por encima
de todas las demás ventanas, y la conversación sigue sin cortes.

- Arrástrala para moverla; la rueda del ratón la hace más grande o más pequeña.
- Los clics solo «tocan» a Mika: en la zona transparente atraviesan hacia la ventana de debajo.
- Al pasar el ratón por encima aparecen sus botones: cámara, micrófono, pantalla, callar, volver a la ventana y cerrar.
- No se muestra sobre juegos en pantalla completa exclusiva; sí sobre los que usan «ventana sin bordes».

## Acciones en tu PC (con permiso)

**Tu orden es la autorización:** cuando le pides algo de la lista, lo hace directamente (decisión del 13 nov
2026). Si prefieres aprobar cada acción, enciende **Ajustes › Acciones en tu PC › Pedir permiso antes de cada
acción**: entonces cada una espera en una tarjeta con **Permitir**, **Permitir siempre** y **No** (también vale
decir «sí» o «no»; caduca a los 2 minutos).

Aunque esté apagado, sí aparece una tarjeta en dos casos:
- **Pasos delicados que tu orden no pedía:** Enviar, Comprar, Borrar… «Elimina la lista» autoriza a pulsar
  «Eliminar lista»; «pon una canción», no.
- **Pantalla o cámara compartidas:** si compartías la pantalla o la cámara y la acción la eligió el modelo (no
  sale claramente de tus palabras), porque podría venir de un texto que se veía en la imagen.

| Acción | Ejemplo de lo que le dices |
| --- | --- |
| Abrir una aplicación del menú Inicio | «Abre Spotify» |
| Abrir una web, o buscar en Google | «Abre youtube.com», «busca recetas de pan» |
| Abrir una carpeta | «Abre la carpeta de descargas» |
| Buscar archivos por nombre en tus carpetas personales (te cuenta lo que encuentra) | «Busca mi archivo de la factura de octubre» |
| Temporizador (de 1 s a 12 h; avisa al terminar, y si la ventana se recargó entretanto, al volver a abrirse, mientras el companion siga encendido) | «Pon un temporizador de 10 minutos para la pasta» |
| Música y vídeo: pausa, siguiente, anterior | «Pasa la canción» |
| Volumen: subir, bajar, silenciar | «Baja el volumen» |

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
- **Ajustes › Acciones en tu PC:** apagarlas del todo, quitar lo que marcaste como «permitir siempre» y ver el
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

- **Cámara**: Mika te ve.
- **Pantalla**: al pulsar el botón se abre «¿Qué quieres que vea Mika?», con una miniatura de cada pantalla y de
  cada ventana abierta. Eliges una y Mika ve **solo eso**: si compartes una ventana, no ve el resto del escritorio
  (y sabe que es una ventana y cuál). «Cancelar» o Esc no comparte nada. Para cambiar de ventana, deja de
  compartir y vuelve a pulsar. Si cierras la ventana compartida, se deja de compartir sola.
- Mientras están activas se ve una miniatura con un punto rojo; se apagan con el mismo botón o con la ✕.
- Se toma una imagen por segundo y la última viaja con tu siguiente mensaje. No se graba ni se guarda en el
  historial. Con el cerebro en la nube esa imagen se envía a Google; con el local no sale de la PC.
- **Mirada en vivo** (Ajustes, activada por defecto): mientras compartes, Mika mira por su cuenta cada pocos
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
sin límite; el que más se acerca es Gemma 4 con tu misma clave. En la capa gratuita, Google puede usar lo que
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
  uno (la GPU se llenó: un juego, ComfyUI), Mika avisa y pasa al siguiente más pequeño del catálogo que vea lo
  mismo (con un modelo propio, a los de `OLLAMA_FALLBACK` o a los del catálogo que piden menos vídeo).
- Ollama atiende una sola petición a la vez y no suelta una ya empezada hasta terminar de leer sus imágenes.
  Por eso la mirada en vivo usa imágenes pequeñas: si hablas justo cuando Mika está mirando, tu turno espera
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
  de prueba, y Mika empieza viéndote por esa cámara. Lo elegido se recuerda y se cambia después en Ajustes.
  Hasta que pulsas «Empezar a hablar» nada de lo que captan el micrófono o la cámara sale hacia el servidor.
- **Webcam que es micrófono y cámara a la vez** (probado con la Logitech Brio): al apagar su vídeo, Windows
  reinicia el aparato entero y su micrófono se queda entregando silencio. Por eso la vista de prueba del inicio
  pasa a ser la cámara de Mika sin cerrarse, y cada vez que la cámara se enciende o se apaga se comprueba que el
  micrófono sigue sonando; si no, se reabre solo (tarda unos 5 s tras apagar la cámara).
- **Micrófono**: silenciar / activar. Puedes interrumpirla hablando encima.
- **Teclado**: escribirle en vez de hablar. **Cuadrado**: que deje de hablar.
- **Ajustes** (engranaje): cerebro en la nube o local, mirada en vivo, modelo 3D, micrófono, cámara, estado de
  cada pieza y «Olvidar todo».
- Arrastra para girar la cámara y usa la rueda para acercar o alejar.

## Ajustes (`.env`)

| Clave | Para qué |
| --- | --- |
| `LLM_PROVIDER` | `gemini` (nube) o `local` (Ollama en esta PC) |
| `GEMINI_MODEL` | `gemini-3.6-flash` (estable) o `gemini-3.5-flash-lite` (más rápido) |
| `GEMINI_FALLBACK` | Modelos de la API de Google a los que pasar cuando el principal agota su cuota diaria |
| `LOCAL_FALLBACK` | `true`: si no queda ningún modelo en la nube, sigue con el local |
| `OLLAMA_MODEL` | Modelo local, por defecto `gemma4:e4b-it-qat` (tiene que caber en la GPU junto a la voz) |
| `OLLAMA_FALLBACK` | Modelo local más pequeño para cuando el principal no cabe, por defecto `gemma4:e2b-it-qat` |
| `OLLAMA_NUM_CTX`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_TIMEOUT` | Contexto (8192), tiempo que el modelo queda cargado (15m) y espera máxima sin respuesta (45 s) |
| `WATCH_INTERVAL`, `WATCH_GAP`, `WATCH_MODEL` | Mirada en vivo: segundos entre miradas (7), mínimo entre comentarios (20) y modelo que la hace con la nube (`gemma-4-26b-a4b-it`) |
| `BACKGROUND_MODEL` | Con la nube, modelo que hace primero el trabajo de fondo: resúmenes de la memoria y cada paso al usar una ventana (`gemma-4-26b-a4b-it`). Si falla, sigue el relevo normal |
| `PERSONA` | Personalidad y voz (`personas/mika.json`) |
| `END_SILENCE_MS` | Silencio que marca el fin de tu turno (más bajo = responde antes, pero corta más) |
| `BARGE_IN` | `false` si usas altavoces y Mika se interrumpe con su propia voz |

Los cambios hechos desde Ajustes duran hasta reiniciar; para dejarlos fijos, edita `.env`. Si el servidor ya
estaba en marcha, `Companion.bat` lo reinicia solo cuando `.env` o el código son más nuevos que él.

## Reglas que el código hace cumplir

- El personaje es siempre adulto (`age ≥ 18` o no arranca).
- Los temas +18 no tienen interruptor: van implícitos con el cerebro local (si tú los propones, Mika puede
  seguirte) siempre que el personaje lo permita en su ficha (`adult.enabled` en `personas/mika.json`).
  Con el cerebro en la nube nunca se activa (`companion/prompt.py: adult_active`).
- Los límites duros del modo +18 de waifuv3 se mantienen tal cual.
- El servidor solo escucha en `127.0.0.1` y rechaza peticiones de otras páginas web: cambios y conversación
  solo desde su propio origen, y cualquier petición que no llame al servidor por `127.0.0.1` o `localhost` (una
  página con un truco de DNS, «DNS rebinding») recibe un 400, también al leer los recuerdos.

## Registros

- `data\companion.log`: lo que hizo el companion en esta sesión. Cada arranque guarda las tres anteriores
  (`companion.1.log` es la última), así que si se cerró por un error, el motivo sigue ahí. Llevan lo que
  transcribe de lo que dices: están solo en esta PC, como todo `data\`.
- `data\voz.log` (y `voz.1.log`, la vez anterior): el servidor de la voz completa. Si se cae, el companion lo
  vuelve a arrancar en la siguiente frase; al arrancar, la primera frase espera a que cargue (hasta un minuto)
  en vez de quedarse sin voz.

## Pruebas

**Rápidas** (44 pruebas en unos 3 s, sin GPU, micrófono, Ollama, nube ni servidores; no tocan nada tuyo):
etiquetas, pronunciación, comprobación de la voz, acciones y los frenos del control de ventanas, recomendación
por tarjeta, relevo de modelos, memoria, seguridad local, voz que espera al cargar, temporizadores y el bucle de
control con piezas simuladas. Conviene correrlas después de cada cambio:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Las pruebas de conversación levantan su propio servidor (puerto 8201, datos en `data\prueba`): no tocan tu
conversación, tus recuerdos ni tus modelos, y no reinician el companion real. Gastan cuota de Gemini, salvo con
`--local` (admitido por `prueba_escritorio.py`, `prueba_ws.py` y `prueba_navegador.py`), que usa el cerebro local.
Para «compartir una ventana» la prueba abre su propia tarjeta (`desktop\tarjeta-prueba.html`), nunca una tuya.

```powershell
.venv\Scripts\python.exe scripts\prueba_escritorio.py       # app de escritorio: modelos, cámara, selector de pantalla o ventana y modo flotante (sin ventanas visibles)
.venv\Scripts\python.exe scripts\prueba_escritorio.py --local   # lo mismo con el cerebro local
.venv\Scripts\python.exe scripts\prueba_bienvenida.py       # la bienvenida completa, que se guarda, no se repite y se edita desde Ajustes (sin GEMINI_API_KEY en .env, por el camino del modelo local)
.venv\Scripts\python.exe scripts\prueba_acciones.py         # acciones con permiso, en modo simulado: no abre ni pulsa nada en la PC (cerebro local)
.venv\Scripts\python.exe scripts\prueba_control.py [modelo] # usar una ventana: solo su propio reproductor falso, fuera de pantalla, sin teclado ni ratón de verdad
.venv\Scripts\python.exe scripts\prueba_control.py --mensajes # ídem solo con mensajes a la ventana (escribir y reproducir en segundo plano)
.venv\Scripts\python.exe scripts\prueba_control_real.py --si  # ídem con TECLADO Y RATÓN DE VERDAD y captura: la ventana a la vista, ~2 min sin usar la PC
.venv\Scripts\python.exe scripts\prueba_memoria.py          # memoria a largo plazo: conversación larga, sesión nueva y pregunta sobre lo anterior (cerebro local)
.venv\Scripts\python.exe scripts\prueba_componentes.py      # etiquetas, voz, detección de voz, Whisper
.venv\Scripts\python.exe scripts\prueba_ws.py               # conversación hablada completa, sin interfaz
.venv\Scripts\python.exe scripts\prueba_ws.py --interrumpir # hablarle encima
.venv\Scripts\python.exe scripts\prueba_navegador.py        # permiso y selector de micrófono en un Chrome oculto
.venv\Scripts\python.exe scripts\prueba_dispositivos.py --mic BRIO --cam BRIO   # micrófono y cámara FÍSICOS (enciende la luz de la cámara; nada llega a un modelo)
.venv\Scripts\python.exe scripts\maniqui_vrm.py data\maniqui.vrm  # maniquí de cajas para probar el avatar
.venv\Scripts\python.exe scripts\medir_llm.py gemini-3.6-flash:minimal gemini-3.5-flash-lite:minimal   # latencia del cerebro
.venv\Scripts\python.exe scripts\medir_llm.py local/gemma4:e4b-it-qat local/gemma4:e2b-it-qat          # ídem, modelos locales
```

## Latencia medida (11 nov 2026)

Desde que dejas de hablar hasta que suena la voz: **3–4 s con la nube** y **~2 s con el modelo local**.
Se reparte así: 0,55 s de silencio para confirmar el fin del turno (la transcripción se adelanta dentro de ese
tiempo), ~2 s hasta la primera frase de Gemini (igual en Flash, Flash-Lite y Gemma 4) o ~0,5 s con el modelo
local, y ~1 s de síntesis de voz. El primer turno tras arrancar tarda más.

## Modelo 3D y ropa

- **Incluidos** (nombres genéricos, sin género): **Avatar 1** (`models\avatar1.vrm`) y **Avatar 2**
  (`models\avatar2.vrm`), avatares de muestra de VRoid, y **Avatar 3**, la esfera (`web/js/orb.js`, sin archivo).
  Avatar 1 es el de por defecto. No se pueden borrar ni sobrescribir desde la interfaz.
- El modelo de Mika se retiró del catálogo el 13 nov 2026. Lo que tuvieras guardado como Mika, Chica, Chico o Esfera
  pasa solo a Avatar 1, 2 o 3. Sus archivos (`models\mika.vrm`, `models\base\mika_base.vrm`) siguen en disco sin
  usarse, igual que `chica.vrm` y `chico.vrm`, que se quedaron para no romper un companion abierto con el código
  anterior; se pueden borrar.
- `models\custom\` guarda los **modelos propios**. Se suben desde Ajustes › Modelo 3D › «Subir un modelo .vrm» o
  arrastrando el archivo a la ventana; el recién subido queda activo. En la misma lista se cambia entre ellos o se
  quita uno propio. Un modelo cambia solo el cuerpo: el nombre y la voz son los de la voz elegida.

Si un modelo trae expresiones más o menos marcadas, los pesos están en `EMOTIONS` y `setVoice` de `web/js/avatar.js`.
(`scripts\vestir_vrm.py`, que vestía el modelo de Mika, queda como herramienta suelta.)

## Movimiento y emociones

Todo el movimiento es procedural sobre el esqueleto humanoide normalizado, así que vale para cualquier VRM:

- **Cómo se mueve** (pulido el 13 nov 2026): cada hueso va hacia su postura como un muelle, con inercia y un pequeño
  rebote (la mano llega un instante después que el antebrazo); los movimientos ociosos usan ruido suave en vez de
  ciclos fijos, para que no se note que se repiten; los dedos se mueven por separado (índice estirado para contar,
  palmas abiertas en abanico).
- **Ojos y cabeza**: parpadeo con cierre rápido y apertura más lenta (a veces lento si está tierna o triste), que
  también llega con los desvíos de mirada y los cambios de emoción; la cabeza acompaña a los ojos con retraso
  cuando miran lejos; al hablar aparta la mirada más a menudo y al escuchar casi nada.
- **Respiración**: su ritmo depende de la emoción; toma aire al empezar a hablar y en cada pausa.
- **En reposo**: brazos colgando cerca del cuerpo con el codo algo doblado y los dedos relajados; respiración;
  descansa sobre una pierna y cada 5–12 s cambia a la otra (la cadera se ladea, el tronco compensa, la rodilla
  libre se dobla); los brazos siguen al cuerpo con retraso; de vez en cuando mira a un lado, ladea la cabeza o
  mueve los hombros.
- **Al hablar**: encadena gestos de manos (explica con la palma hacia arriba, con las dos, abre las palmas, mano al
  pecho, cuenta con el índice, se encoge); cada gesto arranca con un énfasis de la voz y lo marca con el ritmo,
  igual que la cabeza y los hombros.
- **Al escuchar y pensar**: se inclina y asiente; si tarda en responder, se lleva la mano a la barbilla.
- **Emociones** (14): `neutral`, `feliz`, `emocionada`, `timida`, `sonrojada`, `triste`, `molesta`,
  `sorprendida`, `pensativa`, `carinosa`, `enamorada`, `nerviosa`, `asustada`, `confundida`. Cada una cambia la
  cara, la postura (manos juntas, puños, encogida, respingo, temblor…) y añade efectos dibujados junto a la
  cabeza: rubor en las mejillas, corazones, destellos, gota de sudor, lágrimas, «!», «?», puntos suspensivos y
  la marca de enfado (`web/js/effects.js`; no dependen de que el modelo traiga esas expresiones).
- **Gestos con nombre** (9): `saludar`, `asentir`, `negar`, `pensar`, `encogerse`, `reverencia`, `celebrar`,
  `aplaudir`, `risita`.

Para revisar las poses de un vistazo, en la consola de la ventana:
`document.body.append(window.companion.avatar.sheet([{ emotion: 'enamorada' }, { state: 'speaking', talk: 'abre' }, { gesture: 'aplaudir' }]))`.

## Estructura

- `companion/` servidor (FastAPI): `session.py` (turnos de conversación), `llm.py` (Gemini / Ollama),
  `stt.py` + `vad.py` (oído), `tts.py` (voz), `prompt.py` + `tags.py` (personaje y etiquetas), `store.py` (memoria).
- `web/` interfaz: `avatar.js` (modelo VRM y animación), `effects.js` (rubor, corazones y demás efectos), `audio.js` (micrófono y reproducción),
  `vision.js` (cámara y pantalla), `main.js`.
- `desktop/` app de escritorio: `main.js` (ventanas normal y flotante, permisos, selector de lo que se comparte),
  `preload.js`, `picker.html` + `picker-preload.js` (ventana «¿Qué quieres que vea Mika?»), `electron/` (descargado).
- `companion/models.py` modelos 3D (por defecto y propios).
- `personas/` personalidad · `models/` el `.vrm` · `data/` historial y registros.
# companion-ai
