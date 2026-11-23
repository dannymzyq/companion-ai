# El personaje: modelo 3D, movimiento y emociones

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
(`scripts\herramientas\vestir_vrm.py`, que vestía el modelo de Mika, queda como herramienta suelta.)

## Movimiento y emociones

Todo el movimiento va sobre el esqueleto humanoide normalizado, así que vale para cualquier VRM (los incluidos y
los que cargues):

- **Animaciones grabadas** (17 nov 2026): la base del cuerpo son animaciones de captura de movimiento de la
  Universal Animation Library de Quaternius (CC0; ver `web/anim/CREDITOS.md`), convertidas a VRM con
  `scripts/herramientas/convertir_animaciones.py` en `web/anim/clips.json`: reposo, hablar, andar, agacharse, arrodillarse,
  aterrizar y cruzarse de brazos (enfado). Se mezclan con lo escrito en código, que va encima: respiración,
  mirada, gestos al hablar, emociones, toques. El reposo grabado se toma con los pies más juntos y el andar pisa
  hacia el centro, para que se vea menos de personaje de acción. Si falta el archivo, todo sigue como antes.
- **Estilos según la emoción** (17 nov 2026): andar y estar de pie salen de The 100STYLE Dataset - Ian Mason
  (CC BY 4.0, `scripts/herramientas/anim_bvh.py`): neutro, alegre, triste, enfado, tímido, orgullo, pensar, ligero y nervioso
  (`EMO_STYLE` en `avatar.js`; sin emoción, manda la personalidad). Se funden al cambiar, van a la par en la fase
  de la marcha, y su ritmo y velocidad los usa la mascota para avanzar. El movimiento se marca algo más que la
  captura (`amp` de cada capa), más con alegría y menos con tristeza.
- **Manos** (17 nov 2026): posturas con cada dedo por separado (`HANDS` en `avatar.js`: relax, grace, open, fist,
  point, ok, pinch, thumb, peace; en los brazos, `hs`), cascada natural, un temblor mínimo de cada dedo en reposo y
  cada dedo con su velocidad (`FINGER_RATE`). El pulgar se opone (cruza hacia el índice) al cerrarse (`THUMB`).
  Gestos `[gesto:pulgar]` y `[gesto:paz]`; al hablar, `precisa` (pinza u OK).
- **Cara por partes** (`web/js/face.js`): en los modelos de VRoid se registran las formas sueltas de cejas, ojos y
  boca (`Fcl_BRW_*`, `Fcl_EYE_*`, `Fcl_MTH_*`) como expresiones `p_…` y cada emoción se arma con ellas
  (`EMO_PARTS`). Microgestos al azar (`Micro`, idea de TalkingHead): cejas al recalcar, entrecerrar, sonrisita,
  colmillo. Sin esas formas, las expresiones completas de siempre.
- **Boca** (`web/js/lipsync.js`, adaptado de wawa-lipsync, MIT): 7 bandas de formantes y el centroide (audio.js)
  → vocal, oclusiva (cierra) o fricativa (dientes juntos); se mezcla 60/40 con el reparto por bandas de antes.
  Créditos en `web/js/CREDITOS.md`.
- **Ropa con físicas** (`_legColliders`): al cargar, cápsulas en muslos y espinillas (huesos de verdad) y un plano de
  suelo para toda cadena de físicas bajo el pecho (por encima, solo el suelo). Las piezas rígidas de algunas faldas
  (sin física propia) no se pueden empujar.
- **Sueño** (17 nov 2026): tras `SLEEP_AFTER` (180 s) sin usar la app, `sleepNow` → `lean` casi siempre (recostada:
  `lay_up` al revés parado en `LEAN.base`, pierna izquierda estirada, mirando una tablet o un móvil de `props.js`
  colocado en cada cuadro entre las manos o en la palma por `_placeDevice`; tras `LEAN.watch` le entra sueño y tras
  `LEAN.drowsy` deja la pantalla en el pecho y se duerme). Flotando, `pet.rest(true)` la lleva andando a la esquina
  de abajo más cercana y responde `rest` con el lado de la pared (`restAt`). En la ventana, a veces `nod` (seiza,
  cabeceando) o `nap` (tumbada con `lay_up` al revés, `sleepYaw`). Ojos por `sleepEyes`, «zzz» de effects.js, sin IK de pies. `wake()` la despierta (la siesta se levanta
  con el clip hacia delante). Mientras duerme, la mascota recibe el estado `sleep` y no pasea.
- **A petición**: los pasatiempos tienen nombre público (`bailar`, `saltar`, `girar`, `estirarse`, `hechizo`,
  `tararear`, `beber`) y `dormir` (se duerme al terminar de hablar). El prompt le dice que los haga cuando se los
  pidan; `companion/play.py` reconoce la petición en tus palabras y la sesión añade el gesto a la primera frase si el
  modelo no lo puso (`tests/test_juego.py`).
- **Pasatiempos** (17 nov 2026): tras `BORED_AFTER` (50 s) sin usar la app (`avatar.wake()` desde main.js con el
  ratón en la ventana, teclado, clic o rueda; hablar o escribir cambian el estado y también cuentan), hace uno de
  `HOBBIES` cada 15–40 s: `_bailar`, `_saltar`, `_girar` (`spinYaw`), `_estirarse` (bostezo), `_hechizo`, `_tararear`,
  `_beber`, `_curiosear` (en `GESTURES`; usan los clips dance, jump_*, spell, consume si están). La cara de cada uno
  va por `faceX`. Una actividad de la mascota o volver a usar la app lo corta (`endHobby`). `companion.hobby` en
  localStorage; la esfera hace los suyos en orb.js.
- **Rubor pegado a la cara**: `effects.attachBlush` cuelga un plano por mejilla del hueso de la cabeza, orientado
  hacia fuera, con prueba de profundidad (el pelo lo tapa) y apagado según mire a la cámara. El punto de la mejilla
  se busca sobre la piel con un rayo contra las mallas con expresiones (`_onSkin`).
- **Pies en el suelo**: IK de dos huesos (`_legIK`) después de los muelles. De pie cada pie queda clavado y da un
  pasito si la animación lo aleja; andando solo se corrige la altura. `avatar.ikOn = false` lo apaga.
- **Físicas**: el pelo, la falda y los adornos son los muelles del propio VRM. Flotando, notan además el movimiento
  de la ventana (al arrastrarla, andar o caer se quedan atrás y vuelven).

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
