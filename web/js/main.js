// Une todo: conexión con el servidor, audio, avatar, cámara/pantalla e interfaz.
import { AudioIO, OUTPUT_KEY, VOLUME_KEY, savedOutput, savedVolume } from './audio.js';
import { Avatar } from './avatar.js';
import { Vision } from './vision.js';
import { initOnboarding } from './onboarding.js';
import { initLoading } from './loading.js';
import { initPersonality } from './personality.js';
import { adaptToMac } from './platform.js';

adaptToMac();                               // en el Mac, «esta PC», «tarjeta gráfica»… se dicen como en un Mac

const $ = (id) => document.getElementById(id);
const clamp = (x) => Math.max(0, Math.min(1, x));
const STATUS = { idle: 'Te escucho', listening: 'Escuchando…', thinking: 'Pensando…', speaking: 'Hablando' };

// La app de escritorio (Electron) añade window.desktop y permite el modo flotante: una ventana transparente,
// sin marco y siempre encima de las demás. En un navegador normal esas opciones no aparecen.
// Al cambiar de modo la página NO se recarga (desktop/main.js la lleva a la otra ventana): `floating` cambia en
// caliente con setMode y la conversación, la voz y la cámara siguen.
const params = new URLSearchParams(location.search);
const desktop = window.desktop || null;
let floating = !!desktop && params.has('flotante');
const autoStart = !!desktop && params.has('auto');      // al cambiar de ventana la conversación sigue sola
const greet = params.get('saludo') !== '0';
document.body.classList.toggle('floating', floating);
document.body.classList.toggle('desktop', !!desktop);

let ws = null;
let config = null;
let started = false;
let muted = false;
let state = 'idle';
let sentences = [];
let calmTimer = 0;
let pollTimer = 0;
let talkTimer = 0;
let autoTried = false;

// ---------------------------------------------------------------- avatar y audio
let avatar = null;
try {
  avatar = new Avatar($('canvas'));
  if (floating) avatar.setFloating(true);
  avatar.setFullBody(!fadeOn());
  avatar.hobbyOn = hobbyOn();                                       // pasatiempos (Ajustes › Tú y tu personaje)
  avatar.onContextRestored = () => { if (config && config.model) loadModel(); };
  // Dormida (cabeceando o en la siesta): la mascota no pasea ni salta; al despertar, vuelve a lo de antes.
  avatar.onSleep = (on, mode) => {
    if (on) showKeyboard(false);                                     // se va a dormir: el chat se cierra
    if (!desktop || !desktop.pet) return;
    desktop.pet.state(on ? 'sleep' : state);
    document.body.classList.toggle('sleeping', !!on);                  // sin degradado de pies: está tumbada
    if (desktop.pet.rest) desktop.pet.rest(on && mode === 'lean');   // recostada: primero va a una esquina
  };
  avatar.restWait = !!(desktop && desktop.pet && desktop.pet.rest);   // flotando, espera a llegar a la esquina
  avatar.onView = (kind) => voiceReact({ type: 'look', kind });     // cómo la miras con la cámara libre
} catch (err) {
  console.warn('Sin WebGL: se usa el orbe', err);
}

const audio = new AudioIO({
  // Antes de «Empezar a hablar» el micrófono solo mueve la barra de prueba; nada sale hacia el servidor.
  onMic: (pcm) => { if (started && ws && ws.readyState === WebSocket.OPEN) ws.send(pcm); },
  onSentence: (meta) => {
    clearTimeout(calmTimer);
    clearTimeout(talkTimer);
    document.body.classList.add('talking');
    if (meta.emotion && avatar) avatar.setEmotion(meta.emotion);
    for (const g of meta.gestures || []) avatar && avatar.playGesture(g);
    if (meta.id === 1) sentences = [];
    sentences.push(meta.text);
    $('mika-line').textContent = sentences.slice(-2).join(' ');
  },
  onPlaybackEnd: () => {
    send({ type: 'playback_end' });
    calmTimer = setTimeout(() => avatar && avatar.setEmotion('neutral'), 7000);
    talkTimer = setTimeout(() => document.body.classList.remove('talking'), 3500);
  },
});

// ---------------------------------------------------------------- cámara y pantalla
const vision = new Vision({
  onFrame: (source, jpeg, detail) => { if (started) send({ type: 'frame', source, jpeg, ...(detail || {}) }); },
  onChange: (kind, stream, detail) => {
    const figure = $(`preview-${kind}`);
    const video = figure.querySelector('video');
    video.srcObject = stream;
    if (stream) video.play().catch(() => {});
    figure.hidden = !stream;
    $(kind).classList.toggle('active', !!stream);
    $(kind).title = kind === 'camera'
      ? (stream ? 'Apagar la cámara' : 'Activar la cámara: Mika te ve')
      : (stream ? 'Dejar de compartir' : 'Compartir una pantalla o una ventana: Mika ve solo lo que elijas');
    if (kind === 'screen') screenSound(stream, detail);
    if (!stream) send({ type: 'frame_stop', source: kind });
    if (kind === 'camera') healMic(vision.lastCam);
  },
});

// Sonido de la pantalla compartida: va al servidor en trozos de 1 s, que lo transcribe para que Mika sepa qué
// se oye (no se graba). Se puede silenciar sin dejar de compartir con el botón del altavoz de la vista previa.
let screenHears = false;
async function screenSound(stream, detail) {
  const has = !!stream && stream.getAudioTracks().length > 0;
  screenHears = has;
  if (has) {
    try {
      await audio.startScreen(stream, (pcm) => { if (started && screenHears) send({ type: 'screen_audio', pcm: b64(pcm.buffer) }); });
    } catch (err) {
      console.warn('Sin sonido de la pantalla:', err);
      screenHears = false;
    }
  } else {
    audio.stopScreen();
  }
  $('screen-sound').hidden = !has;
  if (stream) screenCaption(detail);
  if (stream && detail?.audioError) {
    toast(`No pude escuchar el sonido de la PC (${detail.audioError}). ${config ? config.name : 'Mika'} ve la imagen igual.`, true);
  }
}
function screenCaption(detail = vision.detail('screen')) {
  const name = config ? config.name : 'Mika';
  const caption = $('preview-screen').querySelector('figcaption');
  const what = detail?.surface === 'window' ? `la ventana ${detail.name || 'elegida'}` : 'tu pantalla';
  caption.textContent = screenHears ? `${name} ve ${what} y oye el sonido` : `${name} ve ${what}`;
  caption.title = detail?.name || '';
  const b = $('screen-sound');
  b.classList.toggle('off', !screenHears);
  b.title = screenHears ? 'Dejar de escuchar el sonido (sigue viendo)' : 'Escuchar también el sonido';
  b.setAttribute('aria-label', b.title);
}
$('screen-sound').onclick = () => {
  screenHears = !screenHears;
  audio.setScreenOn(screenHears);
  if (!screenHears) send({ type: 'screen_audio_stop' });
  screenCaption();
};
function b64(buffer) {
  const bytes = new Uint8Array(buffer);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// Encender o apagar una cámara que también es el micrófono (una webcam) puede dejar el micrófono mudo:
// se comprueba que sigue llegando sonido y, si no, se reabre. Con otro micrófono, basta un intento.
function healMic(cam) {
  if (audio.hasMic) audio.heal(audio.sameDeviceAs(cam) ? 4 : 1);
}
const VISION_ERRORS = {
  camera: {
    NotAllowedError: 'El navegador tiene bloqueada la cámara para esta ventana. Permítela en la configuración del sitio y vuelve a pulsar.',
    NotFoundError: 'No encontré ninguna cámara conectada.',
    NotReadableError: 'No pude abrir la cámara: otro programa la está usando.',
  },
  screen: { NotAllowedError: 'No se compartió nada.', AbortError: 'No se compartió nada.' },
};
const noticed = {};

async function toggleVision(kind) {
  const turningOn = !vision.active(kind);
  try {
    await vision.toggle(kind, kind === 'camera' ? savedCam() : undefined);
    if (kind === 'camera') { camAllowed = camAllowed || turningOn; saveCamOn(turningOn); fillCams(); }
  } catch (err) {
    console.warn(`Sin ${kind}:`, err);
    toast(VISION_ERRORS[kind][err.name] || `No pude activar ${kind === 'camera' ? 'la cámara' : 'la pantalla'} (${err.name}).`, true);
    return;
  }
  if (turningOn && !noticed[kind] && config) {
    noticed[kind] = true;
    const what = kind === 'camera' ? 'una imagen de tu cámara'
      : (vision.detail('screen')?.surface === 'window' ? 'una captura de esa ventana (solo de ella)' : 'una captura de esa pantalla')
        + (screenHears ? ' y el texto de lo que se dice en el sonido (se transcribe en esta PC; el audio no sale de ella)' : '');
    const live = watchOn() ? ' y, con la mirada en vivo, también cada pocos segundos por su cuenta' : '';
    toast(config.llm.provider === 'gemini'
      ? `${config.name} recibe ${what} con cada cosa que le digas${live}. Con el cerebro en la nube, ${kind === 'screen' && screenHears ? 'las imágenes y ese texto' : 'esas imágenes'} se envían a ${config.cloud.name}.`
      : `${config.name} recibe ${what} con cada cosa que le digas${live}. Con el cerebro local no salen de esta PC.`);
  }
}
$('camera').onclick = () => toggleVision('camera');
$('screen').onclick = () => toggleVision('screen');
for (const b of document.querySelectorAll('[data-stop]')) b.onclick = () => vision.stop(b.dataset.stop);

// ---------------------------------------------------------------- bucle de dibujo
// Un error en un cuadro no puede parar el bucle (antes, una sola excepción dejaba el personaje congelado hasta
// reiniciar la app): se pide el siguiente cuadro ANTES de dibujar y cada error distinto se avisa una vez.
const tickErrors = new Set();
function tickPart(name, fn) {
  try { fn(); } catch (err) {
    const key = name + ':' + err.message;
    if (!tickErrors.has(key) && tickErrors.size < 50) { tickErrors.add(key); console.error(`Cuadro (${name}):`, err); }
  }
}
function tick() {
  requestAnimationFrame(tick);
  let voice = { vol: 0 };
  tickPart('voz', () => { voice = audio.analyse(); });
  if (avatar) tickPart('personaje', () => { avatar.setVoice(voice); avatar.update(); });
  tickPart('niveles', () => {
    $('orb').firstElementChild.style.setProperty('--level', clamp(voice.vol * 5).toFixed(3));
    const micLevel = clamp(audio.micLevel * 9).toFixed(3);
    $('mic').firstElementChild.style.setProperty('--level', micLevel);
    $('mic-meter').style.setProperty('--level', micLevel);
    $('mic-meter-2').style.setProperty('--level', micLevel);
  });
  if (floating) tickPart('flotante', () => {
    updateHit(); sendAnchors();
    // Mientras la mascota se mueve, la ventana avanza con cada cuadro dibujado (fluido, al ritmo de la pantalla).
    if (petFrames && desktop && desktop.pet && desktop.pet.frame) desktop.pet.frame();
  });
}
requestAnimationFrame(tick);

// ---------------------------------------------------------------- servidor
function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) { audio.enqueue(e.data); return; }
    handle(JSON.parse(e.data));
  };
  ws.onclose = () => {
    audio.flush();
    $('status').textContent = 'Sin conexión con el companion…';
    setTimeout(connect, 1500);
  };
}

function handle(ev) {
  switch (ev.type) {
    case 'hello':
      applyConfig(ev);
      setState('idle');
      send({ type: 'watch', on: watchOn() });          // cada conexión es una sesión nueva en el servidor
      if (autoStart && !autoTried) { autoTried = true; begin(true); }
      checkUpdate();
      break;
    case 'state': setState(ev.value); break;
    case 'user_text':
      $('user-line').textContent = ev.text;
      $('mika-line').textContent = '';
      sentences = [];
      break;
    case 'sentence': audio.beginSentence(ev); break;
    case 'sentence_end': audio.endSentence(); break;
    case 'reply_end': audio.markReplyDone(); break;
    case 'interrupt': audio.flush(); document.body.classList.remove('talking'); break;
    case 'error': toast(ev.message, true); break;
    case 'notice': toast(ev.message); refreshConfig(); break;
    case 'watch': $('watch').checked = !!ev.on; break;   // el servidor apagó la mirada en vivo (sin cuota)
    case 'action_request': showAsk(ev); break;
    case 'action_done':
      closeAsk(ev);
      if (ev.ok && QUICK_ACTIONS.includes(ev.action)) petWork({ phase: 'quick' });
      break;
    case 'control_start':
      $('control-title').textContent = `${config ? config.name : 'Mika'} está usando «${ev.title}»`;
      $('control-text').textContent = ev.task;
      $('control').hidden = false;
      if (floating) document.body.classList.add('hover');
      petWorking = floating && petPrefs().work;
      petWork({ phase: 'start', window: ev.window || null });
      break;
    case 'control_step':
      $('control-text').textContent = `Paso ${ev.n} de ${ev.max}: ${ev.text}`;
      petWork({ phase: 'step', kind: ev.kind || 'read', point: ev.point || null });
      break;
    case 'control_end':
      $('control').hidden = true;
      toast(ev.ok ? `Terminó: ${ev.text}` : `Se detuvo: ${ev.text}`, !ev.ok);
      petWorking = false;
      petWork({ phase: 'end', ok: !!ev.ok });
      break;
  }
}

// ---------------------------------------------------------------- permisos de las acciones en la PC
// El personaje solo PIDE: la acción se hace si la apruebas aquí (o diciendo «sí»). Los textos vienen del
// servidor (nombres de apps, rutas): siempre como texto, nunca como HTML.
function showAsk(ev) {
  const card = document.createElement('div');
  card.className = 'ask';
  card.dataset.id = ev.id;
  const head = document.createElement('small');
  head.textContent = `${config ? config.name : 'Mika'} quiere: ${ev.title}`;
  const what = document.createElement('p');
  what.textContent = ev.detail;
  card.append(head, what);
  if (ev.note) { const n = document.createElement('p'); n.className = 'ask-note'; n.textContent = ev.note; card.append(n); }
  const buttons = document.createElement('div');
  buttons.className = 'ask-buttons';
  const options = ev.confirm ? [['allow', 'Sí, hazlo', 'yes'], ['deny', 'No', '']]
    : ev.no_always ? [['allow', 'Permitir', 'yes'], ['deny', 'No', '']]           // el control de ventanas, sin «siempre»
      : [['allow', 'Permitir', 'yes'], ['always', 'Permitir siempre', ''], ['deny', 'No', '']];
  for (const [answer, label, cls] of options) {
    const b = document.createElement('button');
    b.textContent = label;
    if (cls) b.className = cls;
    b.title = answer === 'always' ? 'No volverá a preguntar por este tipo de acción (se quita en Ajustes)' : '';
    b.onclick = () => { send({ type: 'action_answer', id: ev.id, answer }); buttons.remove(); };
    buttons.append(b);
  }
  card.append(buttons);
  $('asks').append(card);
  if (floating) document.body.classList.add('hover');
}

function closeAsk(ev) {
  let card = $('asks').querySelector(`[data-id="${CSS.escape(ev.id)}"]`);
  if (!card) {                                         // se hizo sin preguntar («permitir siempre»): solo se avisa
    toast(ev.text, !ev.ok);
    return;
  }
  card.classList.add('done');
  card.querySelector('.ask-buttons')?.remove();
  const result = document.createElement('p');
  result.className = 'ask-note';
  result.textContent = ev.ok ? `Hecho. ${ev.text}` : ev.text;
  card.append(result);
  setTimeout(() => card.remove(), 4500);
  if ($('settings').hidden === false) refreshActions();
}

async function refreshActions() {
  let a;
  try { a = await (await fetch('/api/actions')).json(); } catch { return; }
  $('actions-on').checked = a.enabled;
  $('actions-on').disabled = !a.available;
  $('actions-ask').checked = a.ask;
  $('actions-ask').disabled = a.full;
  $('actions-full').checked = a.full;
  $('sum-acciones').textContent = !a.available ? 'No disponibles con este modelo'
    : !a.enabled ? 'Apagadas' : a.full ? 'Activadas · acceso total' : a.ask ? 'Activadas · piden permiso' : 'Activadas';
  $('actions-note').textContent = a.available
    ? 'Puede pedir abrir aplicaciones, webs y carpetas, buscar archivos por nombre, poner temporizadores, controlar la música y el volumen, y usar una aplicación abierta con tu ratón y teclado. Solo lo que le pidas; cuánto pregunta antes se elige abajo.'
    : 'El modelo local que usas ahora es demasiado pequeño para pedir acciones con fiabilidad: elige Gemma 4 E2B o E4B, o el cerebro en la nube.';
  const rows = a.always.map((name) => {
    const row = document.createElement('div');
    const s = document.createElement('span');
    s.textContent = `Siempre permitido: ${a.catalog[name] || name}`;
    const x = document.createElement('button');
    x.textContent = 'Quitar';
    x.title = 'Volver a pedir permiso cada vez';
    x.onclick = async () => {
      await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ forget_always: name }) });
      refreshActions();
    };
    row.append(s, x);
    return row;
  });
  $('actions-always').replaceChildren(...rows);
  $('actions-log').replaceChildren(...(a.history.length ? a.history.slice(0, 12).map((h) => {
    const row = document.createElement('div');
    const when = document.createElement('b');
    when.textContent = h.when.slice(5, 16);
    const s = document.createElement('span');
    s.textContent = `${h.detail} · ${h.decision}${h.result ? ' · ' + h.result : ''}`;
    row.append(when, s);
    return row;
  }) : [Object.assign(document.createElement('div'), { textContent: 'Todavía no ha pedido ninguna acción.' })]));
}
$('control-stop').onclick = () => send({ type: 'control_stop' });
$('actions-ask').onchange = async () => {
  await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ask: $('actions-ask').checked }) });
  refreshActions();
};
$('actions-full').onchange = async () => {
  const on = $('actions-full').checked;
  if (on && !confirm('¿Dar acceso total? Hará las acciones de su lista sin preguntarte nunca, también las que elija mientras compartes la pantalla. Lo puedes apagar aquí cuando quieras.')) {
    $('actions-full').checked = false;
    return;
  }
  await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ full: on }) });
  refreshActions();
};
$('actions-on').onchange = async () => {
  await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: $('actions-on').checked }) });
  refreshActions();
};

function setState(value) {
  state = value;
  document.body.dataset.state = value;
  if (avatar) avatar.setState(value);
  if (desktop && desktop.pet) desktop.pet.state(avatar && avatar.sleeping && value === 'idle' ? 'sleep' : value);   // la mascota no pasea mientras hablas, habla o duerme
  let label = STATUS[value] || value;
  if (!started) label = 'Lista';
  else if (value === 'idle' && (muted || !audio.hasMic)) label = 'Micrófono en silencio';
  $('status').textContent = label;
}

// ---------------------------------------------------------------- configuración
function applyConfig(cfg) {
  config = cfg;
  const cloud = cfg.llm.provider === 'gemini';
  document.title = cfg.name;
  $('name').textContent = cfg.name;
  $('start-title').textContent = cfg.name;
  $('text-input').placeholder = `Escríbele a ${cfg.name}…`;
  if (avatar && cfg.personality && cfg.personality.temper) avatar.setTemper(cfg.personality.temper);
  $('brain').textContent = `${cloud ? 'Nube' : 'Local'} · ${cfg.llm.model}`;

  // Pantalla de carga: al abrir (si ya pasó la bienvenida) y cada vez que un ajuste cambia el oído, la voz o el cerebro.
  const key = [cfg.stt.engine, cfg.voice_engine, cfg.llm.provider, cfg.local_model, cfg.llm.model].join('|');
  if (loadKey === null) {
    if (cfg.onboarded && !floating && !autoStart) loading.start(cfg.name);
  } else if (key !== loadKey) {
    loading.watch();
  }
  loadKey = key;
  document.querySelector('#start .fine').textContent = (cfg.stt.engine === 'nube'
    ? 'Tu voz se transcribe en la nube (Groq o Gemini).' : 'Tu voz se transcribe en esta PC.')
    + (cfg.llm.provider === 'gemini' ? ' Con el cerebro en la nube, el texto de la conversación y las imágenes que compartas van al proveedor que elegiste.' : '');
  // Primera vez: la bienvenida (perfil, cerebro, voz, modelo). Lo último, micrófono y cámara, es la tarjeta de inicio.
  if (!cfg.onboarded && !welcomed && !floating && !autoStart) { welcomed = true; onboarding.start(); }
  for (const el of document.querySelectorAll('.ob-name')) el.textContent = cfg.name;
  const GENDER = { mujer: 'mujer', hombre: 'hombre', no_binario: 'no binario', '': 'género sin indicar' };
  $('me-line').textContent = cfg.profile.name ? `${cfg.profile.name} · ${cfg.profile.birth_year} · ${GENDER[cfg.profile.gender] || ''}` : 'Sin completar';
  $('cloud-name').textContent = cfg.cloud.name;
  $('cloud-line').textContent = cfg.cloud.has_key ? `${cfg.cloud.name}${cfg.cloud.model ? ' · ' + cfg.cloud.model : ''} · clave ${cfg.cloud.key_hint}` : 'Sin clave de API';
  const engineName = (id) => ({ ligera: 'voz ligera', nube: 'voz en la nube' }[id] || 'voz completa');
  const earCloud = cfg.stt.engine === 'nube';
  $('cloud-only').checked = !!cfg.cloud_only;
  for (const b of $('ear').children) b.classList.toggle('on', b.dataset.value === cfg.stt.engine);
  $('ear-cloud-name').textContent = cfg.stt.cloud.groq ? 'Groq, y Gemini de respaldo' : (cfg.stt.cloud.gemini ? 'Gemini (sin clave de Groq)' : 'Falta una clave');
  $('groq-state').textContent = (cfg.stt.cloud.groq ? 'Clave de Groq guardada.' : 'Sin clave de Groq: el oído en la nube usa Gemini.')
    + (cfg.stt.restart_frees ? ' Reinicia el companion para devolver del todo la memoria que usaba Whisper.' : '');
  const switched = cfg.voice_engine !== cfg.voice_engine_pref;
  $('voice-line').textContent = `${cfg.voice || 'Sin voz'} · ${engineName(cfg.voice_engine_pref)}${switched ? ` (ahora, ${engineName(cfg.voice_engine)})` : ''}`;
  $('voice-auto').checked = cfg.voice_auto;
  $('voice-auto').disabled = cfg.voice_engine_pref !== 'completa';
  $('voice-auto').closest('.row').classList.toggle('disabled', cfg.voice_engine_pref !== 'completa');
  $('voice-auto-note').textContent = (cfg.voice_engine_pref !== 'completa'
    ? 'Solo sirve con la voz completa elegida (en «Voz › Cambiar»). '
    : '')
    + 'Encendido: suena la voz completa y, si a la tarjeta gráfica le falta memoria de vídeo (un modelo local grande, un juego abierto), pasa sola a la ligera, que corre en el procesador. Al volver a haber sitio (por ejemplo, con el cerebro en la nube) vuelve la completa.'
    + (switched && cfg.voice_reason ? ` Ahora usa la ligera porque ${cfg.voice_reason}.` : '');
  $('sum-tu').textContent = cfg.profile.name ? `${cfg.profile.name} · ${cfg.name}` : cfg.name;
  $('sum-cerebro').textContent = `${cloud ? 'Nube' : 'Local'} · ${cfg.llm.model}`;
  $('sum-voz').textContent = `${cfg.voice || 'Sin voz'} · ${engineName(cfg.voice_engine)} · ${Math.round(savedVolume() * 100)} %`;
  $('sum-compartir').textContent = `Mirada en vivo ${$('watch').checked ? 'encendida' : 'apagada'}`;
  $('local-line').textContent = cfg.local_model + (!cloud && cfg.llm.model !== cfg.local_model ? ` (ahora en uso: ${cfg.llm.model})` : '');

  let banner = '';
  if (!cfg.llm.ready) {
    banner = 'Falta la clave del cerebro en la nube. Ponla en Ajustes › Cerebro › «Proveedor y clave», o usa el cerebro local.';
  } else if (cfg.stt.error) {
    banner = 'El oído (Whisper) no pudo cargar. Puedes escribirle con el teclado.';
  } else if (!cfg.stt.ready) {
    banner = 'Preparando el oído (Whisper)… unos segundos.';
  } else if (!cfg.tts) {
    banner = cfg.voice_engine === 'ligera'
      ? `La voz ligera no está instalada: descárgala en Ajustes › Voz. ${cfg.name} responderá solo con texto.`
      : `La voz completa no está disponible (su servidor no responde; mira data\\voz.log). ${cfg.name} responderá solo con texto; en Ajustes › Voz puedes pasar a la voz ligera.`;
  }
  $('banner').innerHTML = banner;
  $('banner').hidden = !banner;

  for (const b of $('provider').children) b.classList.toggle('on', b.dataset.value === cfg.llm.provider);
  $('brain-note').textContent = cloud
    ? `${earCloud || cfg.voice_engine === 'nube' ? 'El' : 'Solo el'} texto de la conversación (y las imágenes de cámara o pantalla, si las compartes) viaja a ${cfg.cloud.name}.`
      + (earCloud || cfg.voice_engine === 'nube'
        ? `${earCloud ? ' Tu voz se transcribe en la nube.' : ' Tu voz se transcribe en esta PC.'}${cfg.voice_engine === 'nube' ? ` La voz de ${cfg.name} se genera en la nube.` : ` La voz de ${cfg.name} se genera en esta PC.`}`
        : ` Tu voz y la de ${cfg.name} se procesan en esta PC.`)
    : `Todo se procesa en esta PC${cfg.adult.active ? ', sin filtro para temas +18 si tú los propones' : ''}. El modelo comparte la memoria de vídeo con la voz: si no cabe (por ejemplo, con un juego abierto),${cfg.name} pasa primero a la voz ligera y, si aún falta, a un modelo más pequeño. Pulsa «Local» otra vez para que vuelva a elegir.`;
  $('watch-note').textContent = `Mientras compartes la cámara o la pantalla, ${cfg.name} mira cada pocos segundos y comenta por su cuenta lo que le llama la atención.`
    + (cloud ? ` Con la nube esas imágenes van a ${cfg.cloud.name} (modelo ${cfg.watch.model}).` : ' Con el cerebro local no salen de esta PC.');

  const health = [
    ['Cerebro', `${cloud ? cfg.cloud.name : 'Ollama'} · ${cfg.llm.model}`, cfg.llm.ready],
    ['Oído', earCloud ? `Nube · ${cfg.stt.cloud.last ? `${cfg.stt.cloud.last.provider} (${String(cfg.stt.cloud.last.seconds).replace('.', ',')} s)` : (cfg.stt.cloud.groq ? 'Groq' : 'Gemini')}`
      : cfg.stt.ready ? `Whisper ${cfg.stt.model} · ${{ cuda: 'GPU', mps: 'GPU del Mac' }[cfg.stt.device] || 'CPU'}` : (cfg.stt.error ? 'Error' : 'Cargando…'), !cfg.stt.error],
    ['Voz', cfg.tts ? `${engineName(cfg.voice_engine)} · ${{ ligera: 'procesador', nube: 'internet' }[cfg.voice_engine] || 'GPU'}` : 'No disponible', cfg.tts],
    ['Modelo 3D', cfg.model ? (/^avatar\d$/.test(cfg.model_id) ? `Avatar ${cfg.model_id.slice(-1)} (incluido)` : 'Modelo propio') : 'Falta el .vrm', cfg.model],
  ];
  if (cfg.llm.detail) health[0][1] += ` · ${cfg.llm.detail}`;
  if (cfg.gpu) {
    const gb = (mb) => (mb / 1024).toFixed(1).replace('.', ',');
    const full = cfg.gpu.used > cfg.gpu.total * 0.95;        // llena: el modelo local iría lento
    health.push(['Memoria de vídeo', `${gb(cfg.gpu.used)} de ${gb(cfg.gpu.total)} GB en uso${full ? ' · llena' : ''}`, !full || cloud]);
  }
  const bad = health.filter(([, , ok]) => !ok).map(([k]) => k.toLowerCase());
  $('sum-estado').textContent = bad.length ? `Revisar: ${bad.join(', ')}` : 'Todo funciona';
  $('health').innerHTML = health.map(([k, v, ok]) => `<dt>${k}</dt><dd class="${ok ? '' : 'bad'}">${v}</dd>`).join('');
  if (update && update.newer && /^https:\/\/github\.com\//.test(update.url)) {
    const dt = document.createElement('dt'), dd = document.createElement('dd'), a = document.createElement('a');
    dt.textContent = 'Versión';
    a.href = update.url; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = `Hay una nueva: ${update.latest} (tienes ${update.current}). Descargar`;
    dd.append(a);
    $('health').append(dt, dd);
  }

  applyQuality();
  if (cfg.model && avatar && !avatar.loaded && !loadingModel) loadModel();
  if (!cfg.model || !avatar) showOrb(true);

  clearTimeout(pollTimer);
  if (!cfg.stt.ready && !cfg.stt.error) pollTimer = setTimeout(refreshConfig, 2000);
}

async function refreshConfig() {
  try { applyConfig(await (await fetch('/api/config')).json()); } catch { /* el servidor se está reiniciando */ }
}

async function postConfig(body) {
  const r = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (r.ok) applyConfig(await r.json());
}

// ---------------------------------------------------------------- modelos 3D: el de fábrica y los propios
let loadingModel = false;
let modelFailed = false;
// Para la pantalla de carga: ¿el personaje 3D ya está a la vista?
function avatarState() {
  if (!config) return 'cargando';
  if (!config.model || !avatar) return 'listo';                 // sin modelo, o sin 3D: la esfera
  if (modelFailed) return 'error';
  return avatar.loaded && !loadingModel ? 'listo' : 'cargando';
}
const loading = initLoading({ avatarState });
let loadKey = null;                         // lo que, si cambia, puede poner a cargar algo (oído, voz, cerebro)

function showOrb(show) {
  $('orb').hidden = !show;
  $('model-hint').hidden = !show || !avatar || floating;
}

// Las cargas van de una en una: con dos clics seguidos (o subir y elegir a la vez) se pisaban. Si llega otra
// mientras una carga, solo se hace la última. Y si un modelo no termina de cargar en 90 s, se deja de esperar.
let loadSeq = 0;
async function loadModel() {
  const mine = ++loadSeq;
  while (loadingModel) await new Promise((r) => setTimeout(r, 100));
  if (mine !== loadSeq) return;                          // ya hay otra más nueva: esa carga lo que quedó activo
  loadingModel = true;
  modelFailed = false;
  try {
    if (config && config.model_kind === 'orb') avatar.loadOrb();              // el personaje neutro no es un archivo
    else {
      let timer;
      const late = new Promise((_, no) => { timer = setTimeout(() => no(new Error('tarda demasiado (más de 90 s)')), 90000); });
      try { await Promise.race([avatar.load(`/api/model?v=${Date.now()}`), late]); } finally { clearTimeout(timer); }
    }
    avatar.setState(state);
    showOrb(false);
  } catch (err) {
    console.error('Cargar el modelo:', err);
    modelFailed = !avatar.loaded;
    if (modelFailed) showOrb(true);
    toast('No pude cargar el modelo 3D: ' + err.message, true);
  } finally {
    loadingModel = false;
  }
}

// Tras cambiar de modelo: vuelve a leer el estado y carga el que quedó activo (o el orbe si no hay ninguno).
async function reloadModel() {
  await refreshConfig();
  if (!avatar) return;
  if (config && config.model) await loadModel();
  else { avatar.unload(); showOrb(true); }
}

function renderModels(list) {
  const rows = [...(list.builtin || []).filter((m) => m.available).map((m) => ({ id: m.id, name: m.name, detail: m.note })),
    ...list.custom.map((m) => ({ id: m.id, name: m.name, detail: `Propio · VRM ${m.spec} · ${m.size_mb} MB`, custom: true }))];
  const box = $('model-list');
  box.replaceChildren();
  for (const m of rows) {
    const row = document.createElement('div');
    row.className = 'model-row' + (m.id === list.active ? ' on' : '');
    const pick = document.createElement('button');
    pick.className = 'pick';
    const name = document.createElement('b');
    name.textContent = m.name;                         // el nombre viene del archivo: nunca como HTML
    const detail = document.createElement('small');
    detail.textContent = m.detail;
    pick.append(name, detail);
    pick.onclick = () => selectModel(m.id);
    row.append(pick);
    if (m.custom) {
      const del = document.createElement('button');
      del.className = 'del';
      del.title = 'Quitar este modelo';
      del.setAttribute('aria-label', `Quitar ${m.name}`);
      del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>';
      del.onclick = () => deleteModel(m.id, m.name);
      row.append(del);
    }
    box.append(row);
  }
}

async function refreshModels() {
  try { renderModels(await (await fetch('/api/models')).json()); } catch { /* servidor reiniciándose */ }
}

async function selectModel(id) {
  const r = await fetch('/api/models/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
  if (!r.ok) { toast('No pude cambiar de modelo.', true); return; }
  renderModels(await r.json());
  await reloadModel();
}

async function deleteModel(id, name) {
  if (!confirm(`¿Quitar el modelo «${name}»? Se borra su archivo de este companion.`)) return;
  const r = await fetch(`/api/models/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!r.ok) { toast('No pude quitar ese modelo.', true); return; }
  renderModels(await r.json());
  await reloadModel();
}

async function uploadModel(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.vrm')) { toast('Ese archivo no es un modelo .vrm', true); return; }
  toast('Subiendo el modelo…');
  const r = await fetch(`/api/models?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { toast(data.detail || 'No se pudo guardar el modelo', true); return; }
  renderModels(data);
  await reloadModel();
  const warn = (data.license_warnings || [])[0];
  toast(`Modelo propio cargado${data.meta && data.meta.name ? ': ' + data.meta.name : ''}.${warn ? ' Aviso de licencia: ' + warn : ''}`);
}

// ---------------------------------------------------------------- bienvenida y sus pasos sueltos en Ajustes
let welcomed = false;
const onboarding = initOnboarding({
  uploadModel, selectModel,
  onDone: async (changed, single) => {
    if (!changed) return;
    await refreshConfig();
    if (single) return;
    // Recién terminada la bienvenida: la tarjeta de inicio pide el micrófono y la cámara.
    $('start-sub').textContent = 'Último paso: elige tu micrófono y tu cámara.';
  },
});
for (const b of document.querySelectorAll('[data-edit]')) b.onclick = () => onboarding.edit(b.dataset.edit);

// Lo que recuerda a largo plazo: datos (se pueden quitar uno a uno) y resúmenes de conversaciones pasadas.
async function refreshMemory() {
  let data;
  try { data = await (await fetch('/api/memory')).json(); } catch { return; }
  const rows = [];
  for (const fact of data.facts) {
    const row = document.createElement('div');
    const text = document.createElement('span');
    text.textContent = fact;
    const del = document.createElement('button');
    del.textContent = '✕';
    del.title = 'Olvidar esto';
    del.onclick = async () => {
      await fetch('/api/memory/forget', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fact }) });
      refreshMemory();
    };
    row.append(text, del);
    rows.push(row);
  }
  for (const s of data.summaries.slice().reverse()) {
    const row = document.createElement('div');
    const date = document.createElement('b');
    date.textContent = s.date;
    const text = document.createElement('span');
    text.textContent = s.text;
    row.append(date, text);
    rows.push(row);
  }
  if (!rows.length) {
    const row = document.createElement('div');
    row.textContent = 'Todavía no hay recuerdos guardados.';
    rows.push(row);
  }
  $('memory-list').replaceChildren(...rows);
}

$('model-upload').onclick = () => $('model-file').click();
$('model-file').onchange = (e) => { uploadModel(e.target.files[0]); e.target.value = ''; };

let dragDepth = 0;
addEventListener('dragenter', (e) => {
  if (![...e.dataTransfer.types].includes('Files')) return;
  e.preventDefault();
  dragDepth++;
  $('drop').hidden = false;
});
addEventListener('dragover', (e) => e.preventDefault());
addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('drop').hidden = true; } });
addEventListener('drop', (e) => {
  e.preventDefault();
  dragDepth = 0;
  $('drop').hidden = true;
  uploadModel(e.dataTransfer.files[0]);
});

// ---------------------------------------------------------------- micrófono: permiso y elección
const MIC_KEY = 'companion.mic';
const savedMic = () => { try { return localStorage.getItem(MIC_KEY) || ''; } catch { return ''; } };
const saveMic = (id) => { try { localStorage.setItem(MIC_KEY, id); } catch { /* modo privado */ } };
const MIC_ERRORS = {
  NotAllowedError: 'El navegador tiene bloqueado el micrófono para esta ventana. Abre el menú ⋮ (o el candado junto a la dirección) › Configuración del sitio › Micrófono › Permitir, y vuelve a pulsar.',
  NotFoundError: 'No encontré ningún micrófono conectado a la PC.',
  NotReadableError: 'No pude abrir ese micrófono: otro programa lo está usando o Windows lo bloquea (Configuración › Privacidad y seguridad › Micrófono).',
};

async function fillMics() {
  const mics = await audio.listMics();
  const wanted = audio.micId || savedMic();
  for (const sel of [$('mic-select'), $('mic-select-2')]) {
    sel.innerHTML = '';
    for (const m of mics) sel.add(new Option(m.label, m.id));
    if (!mics.length) sel.add(new Option('No hay micrófonos', ''));
    sel.value = mics.some((m) => m.id === wanted) ? wanted : sel.options[0].value;
    sel.disabled = !mics.length;
  }
  return mics;
}

// Abre el micrófono indicado (pide permiso si hace falta) y deja la interfaz al día.
async function useMic(deviceId) {
  $('mic-error').hidden = true;
  try {
    const mic = await audio.openMic(deviceId);
    saveMic(mic.id);
    await fillMics();
    $('mic-allow').hidden = true;
    $('mic-allow-2').hidden = true;
    $('mic-picker').hidden = false;
    $('mic-help').textContent = 'Di algo: la barra debe moverse con tu voz.';
    $('start-btn').hidden = false;
    $('start-text').hidden = true;
    $('mic').classList.toggle('muted', muted);
    if (started) setState(state);
    return true;
  } catch (err) {
    console.warn('Sin micrófono:', err);
    const message = MIC_ERRORS[err.name] || `No pude abrir el micrófono (${err.name}).`;
    $('mic-error').textContent = message;
    $('mic-error').hidden = false;
    $('mic-allow-2').hidden = false;
    if (started) toast(message, true);
    return false;
  }
}

async function withBusy(button, job) {
  button.disabled = true;
  try { return await job(); } finally { button.disabled = false; }
}

$('mic-allow').onclick = () => withBusy($('mic-allow'), async () => { if (await useMic(savedMic())) await allowCam(); });
$('mic-allow-2').onclick = () => withBusy($('mic-allow-2'), () => useMic(savedMic()));
$('mic-select').onchange = (e) => useMic(e.target.value);
$('mic-select-2').onchange = (e) => useMic(e.target.value);
if (navigator.mediaDevices) navigator.mediaDevices.addEventListener('devicechange', () => { fillMics(); fillCams(); fillOutputs(); });

// ---------------------------------------------------------------- cámara: permiso y elección
// Se guarda qué cámara usar y si Mika empieza viéndote. Al iniciar se elige en la tarjeta; después, en Ajustes.
const CAM_KEY = 'companion.cam', CAM_ON_KEY = 'companion.cam.on', OFF = 'off', ASK = 'ask';
function savedCam() { try { return localStorage.getItem(CAM_KEY) || ''; } catch { return ''; } }
function saveCam(id) { try { localStorage.setItem(CAM_KEY, id); } catch { /* modo privado */ } }
function camOn() { try { return localStorage.getItem(CAM_ON_KEY) === '1'; } catch { return false; } }
function saveCamOn(on) { try { localStorage.setItem(CAM_ON_KEY, on ? '1' : '0'); } catch { /* modo privado */ } }
let camTest = null;                     // vista de prueba en la tarjeta de inicio
let camAllowed = false;

// keep = true devuelve la cámara de prueba aún abierta, para seguir usándola sin cerrarla.
function stopCamTest(keep = false) {
  const stream = camTest;
  camTest = null;
  $('cam-test').srcObject = null;
  $('cam-test').hidden = true;
  if (!stream) return null;
  if (keep) return stream;
  const track = stream.getVideoTracks()[0];
  const cam = track ? { group: track.getSettings().groupId || '', label: track.label } : null;
  stream.getTracks().forEach((t) => t.stop());
  healMic(cam);
  return null;
}

async function fillCams() {
  const cams = camAllowed ? await vision.listCams() : [];
  const wanted = savedCam();
  const known = cams.some((c) => c.id === wanted);
  const first = $('cam-select'), later = $('cam-select-2');
  first.innerHTML = '';
  first.add(new Option('Apagada (puedes encenderla después)', OFF));
  for (const c of cams) first.add(new Option(c.label, c.id));
  if (!camAllowed) first.add(new Option('Elegir una cámara… (pide permiso)', ASK));
  first.value = !started && camOn() && known ? wanted : (vision.active('camera') && known ? wanted : OFF);
  later.innerHTML = '';
  for (const c of cams) later.add(new Option(c.label, c.id));
  if (!cams.length) later.add(new Option(camAllowed ? 'No hay cámaras' : 'Sin permiso todavía: pulsa el botón de cámara', ''));
  later.value = known ? wanted : later.options[0].value;
  later.disabled = !cams.length;
  return cams;
}

// Pide el permiso de la cámara (abriéndola un instante si hace falta) y muestra la lista.
async function allowCam() {
  let problem = '';
  try {
    const status = await navigator.permissions.query({ name: 'camera' }).catch(() => null);
    if (!status || status.state !== 'granted') (await vision.openCamera(savedCam())).getTracks().forEach((t) => t.stop());
    camAllowed = true;
  } catch (err) {
    problem = VISION_ERRORS.camera[err.name] || `No pude abrir la cámara (${err.name}).`;
  }
  const cams = await fillCams();
  $('cam-picker').hidden = false;
  $('cam-help').textContent = problem || (cams.length
    ? `Elige una cámara para que ${config ? config.name : 'Mika'} te vea, o déjala apagada. Se puede cambiar después en Ajustes.`
    : 'No encontré ninguna cámara conectada.');
  return cams;
}

// Elección en la tarjeta de inicio: se guarda y se muestra una vista de prueba de esa cámara.
$('cam-select').onchange = async (e) => {
  let id = e.target.value;
  stopCamTest();
  if (id === ASK) {
    const cams = await allowCam();
    id = cams.length ? (savedCam() && cams.some((c) => c.id === savedCam()) ? savedCam() : cams[0].id) : OFF;
    $('cam-select').value = id;
  }
  saveCamOn(id !== OFF);
  if (id === OFF) return;
  saveCam(id);
  try {
    camTest = await vision.openCamera(id);
    $('cam-test').srcObject = camTest;
    $('cam-test').hidden = false;
    $('cam-test').play().catch(() => {});
  } catch (err) {
    $('cam-help').textContent = VISION_ERRORS.camera[err.name] || `No pude abrir esa cámara (${err.name}).`;
  }
};

// En Ajustes: cambia la cámara que se usa; si está encendida, pasa a la nueva en el momento.
$('cam-select-2').onchange = async (e) => {
  if (!e.target.value) return;
  saveCam(e.target.value);
  if (!vision.active('camera')) return;
  vision.stop('camera');
  try { await vision.start('camera', e.target.value); } catch (err) { toast(VISION_ERRORS.camera[err.name] || 'No pude abrir esa cámara.', true); }
};

// ---------------------------------------------------------------- mirada en vivo
const WATCH_KEY = 'companion.watch';
function watchOn() { try { return localStorage.getItem(WATCH_KEY) !== '0'; } catch { return true; } }
$('watch').checked = watchOn();
$('watch').onchange = () => {
  $('sum-compartir').textContent = `Mirada en vivo ${$('watch').checked ? 'encendida' : 'apagada'}`;
  try { localStorage.setItem(WATCH_KEY, $('watch').checked ? '1' : '0'); } catch { /* modo privado */ }
  send({ type: 'watch', on: $('watch').checked });
};

// Si el permiso ya se concedió en una sesión anterior, se muestra directamente el selector.
(async () => {
  try {
    const status = await navigator.permissions.query({ name: 'microphone' });
    if (status.state !== 'granted') return;
    const mics = await fillMics();
    if (!mics.length) return;
    $('mic-allow').hidden = true;
    $('mic-picker').hidden = false;
    $('mic-help').textContent = 'Se usará este micrófono. Puedes cambiarlo aquí o después en Ajustes.';
    $('start-btn').hidden = false;
    const cam = await navigator.permissions.query({ name: 'camera' }).catch(() => null);
    camAllowed = !!cam && cam.state === 'granted';
    const cams = await fillCams();
    $('cam-picker').hidden = false;
    $('cam-help').textContent = camAllowed && !cams.length ? 'No encontré ninguna cámara conectada.'
      : 'Elige si quieres empezar con la cámara encendida y cuál usar. Se puede cambiar después en Ajustes.';
  } catch { /* navegador sin API de permisos: se queda el botón «Permitir micrófono y cámara» */ }
})();

// ---------------------------------------------------------------- inicio de la conversación
if (autoStart) $('start').hidden = true;

async function begin(withMic) {
  if (withMic && !audio.hasMic) {
    if (!(await useMic($('mic-select').value || savedMic()))) {
      $('start').hidden = false;                       // en arranque automático: vuelve la tarjeta con el error
      $('start').classList.remove('leaving');
      return;
    }
  } else {
    await audio.init();
  }
  started = true;
  $('start').classList.add('leaving');
  setTimeout(() => ($('start').hidden = true), 400);
  if (!audio.hasMic) {
    showKeyboard(true);
    $('mic').classList.add('muted');
  }
  setState(state);
  if (config && config.llm.ready && greet) send({ type: 'start' });

  // Cámara: la elegida en la tarjeta de inicio (al cambiar entre ventana y flotante la página sigue, y la cámara
  // también: no hace falta volver a encenderla).
  const choice = $('cam-select').value;
  const wanted = !autoStart && choice && choice !== OFF && choice !== ASK;
  const preview = stopCamTest(wanted);                // la vista de prueba pasa a ser la cámara de Mika, sin cerrarla
  if (wanted) {
    camAllowed = true;
    try { await vision.start('camera', choice, preview); } catch (err) {
      toast(VISION_ERRORS.camera[err.name] || `No pude encender la cámara (${err.name}).`, true);
    }
    fillCams();
  }
}
$('start-btn').onclick = () => withBusy($('start-btn'), () => begin(true));
$('start-text').onclick = () => begin(false);

// ---------------------------------------------------------------- controles
$('mic').onclick = async () => {
  if (!audio.hasMic) {
    muted = false;
    if (!(await useMic(savedMic()))) return;
  } else {
    muted = !muted;
  }
  audio.setMuted(muted);
  $('mic').classList.toggle('muted', muted);
  $('mic').title = muted ? 'Activar micrófono' : 'Silenciar micrófono';
  setState(state);
};

$('stop').onclick = () => { audio.flush(); send({ type: 'interrupt' }); };

function showKeyboard(show) {
  $('text-form').hidden = !show;
  $('keyboard').classList.toggle('active', show);
  if (show) $('text-input').focus();
  if (avatar && show) avatar.wake();                                  // abrir el chat la despierta
}
$('keyboard').onclick = () => showKeyboard($('text-form').hidden);
$('text-input').addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); showKeyboard(false); } });

$('text-form').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('text-input').value.trim();
  if (!text) return;
  $('text-input').value = '';
  if (floating) {                                                // flotando: un destello verde de «enviado»
    $('text-form').classList.add('sent');
    setTimeout(() => $('text-form').classList.remove('sent'), 900);
  }
  audio.flush();
  for (const kind of ['camera', 'screen']) vision.push(kind);     // que vea lo de este instante
  send({ type: 'text', text });
};

const personalityUI = initPersonality({ toast, onChange: () => refreshConfig() });

const openSettings = (open) => {
  $('settings').hidden = !open;
  if (!open) return;
  refreshConfig();
  refreshActions();
  refreshModels();
  refreshMemory();
  personalityUI.refresh();
  Promise.all([fillMics(), fillCams()]).then(() => {
    const pick = (id) => { const o = $(id).selectedOptions[0]; return o && o.value ? o.textContent : ''; };
    const mic = pick('mic-select-2'), cam = pick('cam-select-2');
    $('sum-dispositivos').textContent = [mic || 'Sin micrófono', cam || 'sin cámara'].join(' · ');
  }).catch(() => {});
  fillOutputs();
  $('mic-allow-2').hidden = audio.hasMic;
};
$('open-settings').onclick = () => openSettings(true);
$('brain').onclick = () => openSettings(true);
$('close-settings').onclick = () => openSettings(false);
$('settings').onclick = (e) => { if (e.target === $('settings')) openSettings(false); };
addEventListener('keydown', (e) => { if (e.key === 'Escape') openSettings(false); });

for (const b of $('provider').children) b.onclick = () => postConfig({ provider: b.dataset.value });

// La «i» de cada opción abre y cierra su explicación (dentro de un interruptor, sin cambiarlo).
for (const b of document.querySelectorAll('.info[data-tip]')) {
  b.type = 'button';
  b.setAttribute('aria-expanded', 'false');
  b.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const tip = $(b.dataset.tip);
    tip.hidden = !tip.hidden;
    b.setAttribute('aria-expanded', String(!tip.hidden));
  };
}

async function postSetup(body, fail = 'No se pudo guardar.') {
  const r = await fetch('/api/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (r.ok) { applyConfig(await r.json()); return true; }
  let msg = fail;
  try { msg = (await r.json()).detail || fail; } catch { /* sin detalle */ }
  toast(msg, true);
  refreshConfig();
  return false;
}
const restartHint = () => { if (config.stt.restart_frees) toast('Listo. Para devolver toda la memoria que usaba el oído local, reinicia el companion.'); };
$('cloud-only').onchange = async () => { if (await postSetup({ cloud_only: $('cloud-only').checked })) restartHint(); };
for (const b of $('ear').children) b.onclick = async () => { if (await postSetup({ ear: { engine: b.dataset.value } })) restartHint(); };
$('groq-save').onclick = async () => {
  const key = $('groq-key').value.trim();
  if (!key) { toast('Pega primero la clave de Groq.', true); return; }
  $('groq-save').disabled = true;
  if (await postSetup({ ear: { groq_key: key } })) { $('groq-key').value = ''; toast('Clave de Groq guardada.'); }
  $('groq-save').disabled = false;
};

$('voice-auto').onchange = async () => {
  const r = await fetch('/api/setup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ voice_auto: $('voice-auto').checked }) });
  if (r.ok) applyConfig(await r.json()); else toast('No se pudo guardar.', true);
};

// ---------------------------------------------------------------- salida de audio y volumen
async function fillOutputs() {
  const sel = $('output-select');
  const outs = await audio.listOutputs();
  const wanted = savedOutput();
  sel.innerHTML = '';
  sel.add(new Option('Predeterminada de Windows', ''));
  for (const o of outs) sel.add(new Option(o.label, o.id));
  sel.value = outs.some((o) => o.id === wanted) ? wanted : '';
  sel.disabled = !!audio.ctx && !audio.ctx.setSinkId;     // este navegador no deja elegir la salida
}
$('output-select').onchange = async (e) => {
  const id = e.target.value;
  try {
    await audio.setOutput(id);
    try { localStorage.setItem(OUTPUT_KEY, id); } catch { /* modo privado */ }
    toast(id ? `Ahora suena por ${e.target.selectedOptions[0].textContent}.` : 'Ahora suena por la salida predeterminada de Windows.');
  } catch (err) {
    toast(`No pude usar esa salida (${err.name || err}).`, true);
    fillOutputs();
  }
};
function showVolume(v) {
  $('volume').value = String(Math.round(v * 100));
  $('volume-value').textContent = `${Math.round(v * 100)} %`;
}
showVolume(savedVolume());
$('volume').oninput = () => {
  const v = Number($('volume').value) / 100;
  audio.setVolume(v);
  $('volume-value').textContent = `${Math.round(v * 100)} %`;
  try { localStorage.setItem(VOLUME_KEY, String(v)); } catch { /* modo privado */ }
};
$('volume').onchange = () => refreshConfig();
$('forget').onclick = async () => {
  if (!confirm('¿Borrar todo el historial y los recuerdos? No se puede deshacer.')) return;
  const r = await fetch('/api/memory', { method: 'DELETE' });
  toast(r.ok ? 'Listo: empezamos de cero.' : 'No se pudo borrar.', !r.ok);
  $('user-line').textContent = '';
  $('mika-line').textContent = '';
};

// Empezar de nuevo: repetir la bienvenida (conserva lo guardado) o restablecer todos los datos del usuario.
async function resetSetup(data) {
  const r = await fetch('/api/setup/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data }) });
  if (!r.ok) { toast('No se pudo reiniciar.', true); return; }
  if (data) { try { localStorage.clear(); } catch { /* modo privado */ } }
  location.replace(location.pathname);  // al recargar, sin bienvenida hecha, se abre sola desde el primer paso
}
$('redo-onboarding').onclick = () => resetSetup(false);
$('reset-all').onclick = () => {
  if (confirm('¿Restablecer tus datos? Se borran tu perfil, la clave de API, la voz y el personaje elegidos, la conversación y los recuerdos. No se puede deshacer.')) resetSetup(true);
};

// ---------------------------------------------------------------- versión nueva
// Una vez por apertura: si hay una versión publicada más nueva, se avisa y Ajustes › Estado enseña el enlace.
let update = null;
let updateAsked = false;
async function checkUpdate() {
  if (updateAsked || floating) return;
  updateAsked = true;
  try {
    const r = await fetch('/api/update');
    update = r.ok ? await r.json() : null;
  } catch { update = null; }
  if (!update || !update.newer) return;
  toast(`Hay una versión nueva de Companion (${update.latest}). Descárgala desde Ajustes › Estado.`);
  if (config) applyConfig(config);
}

let toastTimer = 0;
function toast(message, isError = false) {
  const el = $('toast');
  el.textContent = message;
  el.classList.toggle('error', isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 7000 : 5500);
}

// ---------------------------------------------------------------- modo flotante (app de escritorio)
$('float-btn').hidden = !desktop || floating;
async function switchWindow(toFloat) {
  if (toFloat && !started) await begin(true);       // sin la tarjeta de inicio (no se ve flotando): micrófono ya
  desktop.float(toFloat);
}
$('float-btn').onclick = () => switchWindow(true);
$('dock').onclick = () => switchWindow(false);
$('quit').onclick = () => (desktop && desktop.quit ? desktop.quit() : window.close());

// La app avisa del cambio de modo; la página solo cambia de aspecto.
function setMode(mode) {
  const on = mode === 'float';
  if (on === floating) return;
  floating = on;
  document.body.classList.toggle('floating', on);
  document.body.classList.remove('hover');
  $('float-btn').hidden = !desktop || on;
  mouse = null; dragging = false; rotating = false; ignoring = null;
  if (on) {
    openSettings(false);                             // los ajustes no se ven flotando
    showKeyboard(false);
  } else {
    showOrb(!config || !config.model || !avatar);
  }
  if (avatar) { avatar.setFloating(on); avatar.setActivity('none'); }
  lastAnchors = '';                                  // la app vuelve a recibir dónde están los pies
  fitBar();
}
// Flotando, la barra de botones encoge para caber entera en la ventana (pequeña con la rueda, o en parte fuera de la
// pantalla): antes se cortaban los botones de los lados (17 nov 2026). `zoom` también encoge la zona que se pulsa.
function fitBar() {
  const bar = document.querySelector('footer > .controls');
  if (!bar) return;
  if (!floating) { bar.style.zoom = ''; return; }
  bar.style.zoom = '1';
  const avail = bar.parentElement.clientWidth - 16, need = bar.offsetWidth;
  bar.style.zoom = need > avail && need > 0 ? String(Math.max(0.55, avail / need)) : '1';
}
new ResizeObserver(fitBar).observe(document.querySelector('footer'));
if (desktop && desktop.onMode) desktop.onMode(setMode);

// ---------------------------------------------------------------- mascota de escritorio (Ajustes › Escritorio)
// Solo en la app y solo flotando: desktop/pet.js mueve la ventana (gravedad, paseos, sentarse, ir a la ventana que
// maneja) y aquí se ponen las animaciones. Los ajustes se recuerdan en esta app (localStorage).
// Calidad del personaje (18 nov 2026): texturas y resolución según la memoria de vídeo de la tarjeta (config.gpu,
// en MB; en el Mac, la parte de la memoria unificada que puede usar la GPU). Sin dato (gráfica integrada, AMD): media.
function QUALITY() { return { alta: { maxTex: 4096, ratio: 2 }, media: { maxTex: 2048, ratio: 1.5 }, baja: { maxTex: 1024, ratio: 1 } }; }   // función: applyConfig puede llegar antes
function qualityPref() { try { return localStorage.getItem('companion.quality') || 'auto'; } catch { return 'auto'; } }
function qualityNow() {
  const pref = qualityPref();
  if (pref in QUALITY()) return pref;
  const total = config && config.gpu ? config.gpu.total : 0;
  return !total ? 'media' : total >= 7800 ? 'alta' : total >= 5500 ? 'media' : 'baja';
}
function applyQuality() {
  if (!avatar || !avatar.setQuality) return;
  const changed = avatar.setQuality(QUALITY()[qualityNow()]);
  if (changed && avatar.vrm && config && config.model && !loadingModel) loadModel();   // texturas nuevas: se recarga
}
$('quality-select').value = qualityPref();
$('quality-select').onchange = () => {
  try { localStorage.setItem('companion.quality', $('quality-select').value); } catch { /* modo privado */ }
  applyQuality();
};

// Funciones (no const): el avatar las usa antes de llegar aquí.
// Pasatiempos (17 nov 2026): si no usas la app un rato, se entretiene sola (avatar.js HOBBIES). Encendido por defecto.
function hobbyOn() { try { return localStorage.getItem('companion.hobby') !== '0'; } catch { return true; } }
$('hobby').checked = hobbyOn();
$('hobby').onchange = () => {
  try { localStorage.setItem('companion.hobby', $('hobby').checked ? '1' : '0'); } catch { /* modo privado */ }
  if (avatar) avatar.hobbyOn = $('hobby').checked;
};
// Usar la app (ratón por la ventana, teclado, clic, rueda) la saca del pasatiempo; hablar y escribir también (el
// estado deja de ser «idle»). El ratón en otras ventanas no cuenta: estar en otra cosa es justo cuando se entretiene.
for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel']) {
  addEventListener(ev, () => { if (avatar && avatar.wake) avatar.wake(); }, { passive: true });
}

function petPrefs() {
  const base = { follow: true, react: true, gravity: true, walk: 'aveces', sit: false, work: true, fade: true, alpha: 0 };
  try {
    const saved = JSON.parse(localStorage.getItem('companion.pet') || '{}');
    if (localStorage.getItem('companion.float.fade') === '0' && saved.fade === undefined) saved.fade = false;   // ajuste de antes
    return { ...base, ...saved };
  } catch { return base; }
}
function fadeOn() { return petPrefs().fade; }
const PET_SWITCHES = { follow: 'pet-follow', react: 'pet-react', gravity: 'pet-gravity', sit: 'pet-sit', work: 'pet-work', fade: 'float-fade' };
const WALK_NAMES = { nunca: 'sin paseos', aveces: 'paseos a veces', amenudo: 'paseos a menudo' };
let petWorking = false;                       // una acción «controlar» en curso: el modelo no recibe clics

function applyPet() {
  const p = petPrefs();
  for (const [k, id] of Object.entries(PET_SWITCHES)) $(id).checked = !!p[k];
  $('pet-walk').value = p.walk;
  const alpha = Math.max(0, Math.min(90, Number(p.alpha) || 0));          // transparencia en %
  $('pet-alpha').value = String(alpha);
  $('pet-alpha-value').textContent = `${alpha} %`;
  document.body.style.setProperty('--pet-opacity', String(1 - alpha / 100));
  document.body.classList.toggle('no-fade', !p.fade);
  if (avatar) { avatar.setFullBody(!p.fade); avatar.setFollow(p.follow); }
  const on = [p.follow && 'mirada', p.gravity && 'gravedad', WALK_NAMES[p.walk], p.sit && 'se sienta', p.work && 'acompaña las acciones',
    alpha && `transparente ${alpha} %`].filter(Boolean);
  $('sum-escritorio').textContent = on.join(' · ');
  if (desktop && desktop.pet) desktop.pet.prefs(p);
}
function savePet(change) {
  try { localStorage.setItem('companion.pet', JSON.stringify({ ...petPrefs(), ...change })); } catch { /* modo privado */ }
  applyPet();
}
$('pet-group').hidden = !desktop;
for (const [k, id] of Object.entries(PET_SWITCHES)) $(id).onchange = () => savePet({ [k]: $(id).checked });
$('pet-walk').onchange = () => savePet({ walk: $('pet-walk').value });
$('pet-alpha').oninput = () => savePet({ alpha: Number($('pet-alpha').value) });
applyPet();

if (desktop && desktop.pet) {
  desktop.pet.on((ev) => {
    if (!avatar) return;
    if (ev.type === 'cursor') avatar.setCursor(ev.x, ev.y);
    else if (ev.type === 'activity') avatar.setActivity(ev.name, ev.opts || {});
    else if (ev.type === 'workmode') { avatar.setWorkMode(ev.mode); if (ev.stance) avatar.setStance(ev.stance); }
    else if (ev.type === 'gesture') avatar.playGesture(ev.name);
    else if (ev.type === 'frames') petFrames = !!ev.on;
    else if (ev.type === 'rest') avatar.restAt(ev.side);
    else if (ev.type === 'moving') document.body.classList.toggle('pet-moving', !!ev.on);
    else if (ev.type === 'insets') {
      for (const k of ['top', 'bottom', 'left', 'right']) document.body.style.setProperty(`--pet-cut-${k}`, `${Math.round(ev[k] || 0)}px`);
      fitBar();
    }
  });
}
// Los puntos del personaje (pies, asiento, cabeza) en px de la ventana, para que la app la coloque bien.
let lastAnchors = '';
let petFrames = false;                // desktop/pet.js pide los cuadros mientras mueve la ventana
let anchorsAt = 0;
function sendAnchors() {
  if (!floating || !avatar || !desktop || !desktop.pet || performance.now() - anchorsAt < 250) return;
  anchorsAt = performance.now();
  const a = avatar.anchors();
  if (!a) return;
  const r = (pt) => ({ x: Math.round(pt.x), y: Math.round(pt.y) });
  const out = { feet: r(a.feet), seat: r(a.seat), head: r(a.head), hand: r(a.hand), w: a.w, h: a.h };
  if (a.step) out.step = Math.round(a.step);
  if (a.hz) out.hz = Math.round(a.hz * 100) / 100;
  if (a.speed) out.speed = Math.round(a.speed);
  const key = JSON.stringify(out);
  if (key !== lastAnchors) { lastAnchors = key; desktop.pet.anchors(out); }
}
// Las acciones en ventanas, a la mascota (solo flotando; ella mira si «Acompañar las acciones» está encendido).
const QUICK_ACTIONS = ['abrir_app', 'abrir_web', 'abrir_carpeta', 'multimedia', 'volumen'];
function petWork(msg) {
  if (floating && desktop && desktop.pet) desktop.pet.work(msg);
}

// La ventana flotante es un rectángulo transparente. Para que no estorbe, los clics solo «tocan» a Mika y a
// sus botones; en el resto atraviesan hacia lo que haya debajo. Se decide cuadro a cuadro según el píxel
// que queda bajo el ratón.
let mouse = null;
let dragging = false;
let rotating = false;
let ignoring = null;
let hoverTimer = 0;
let overModel = false;
let leftModelAt = 0;
let press = null;                              // clic sin arrastrar = tocarla

function updateHit() {
  if (avatar) avatar.probe = mouse;
  let hit = dragging || rotating;
  if (!hit && mouse) {
    const el = document.elementFromPoint(mouse.x, mouse.y);
    const still = !document.body.classList.contains('pet-moving');   // moviéndose, la barra está escondida
    const onUi = (still && !!(el && el.closest('.controls, #toast')) && document.body.classList.contains('hover'))
      || !!(el && el.closest('#text-form'))              // la cápsula para escribirle, siempre que esté abierta
      || !!(el && el.closest('#asks, #control'));     // una tarjeta de permiso o «Parar» siempre se pueden pulsar
    const model = !petWorking && (avatar ? avatar.probeHit : !$('orb').hidden);
    hit = onUi || model;
    // Pasar el ratón por encima tras un rato sin hacerlo: te mira, sonríe y a veces saluda.
    if (model && !overModel && avatar && petPrefs().react && performance.now() - leftModelAt > 9000 && state === 'idle') avatar.react('hover');
    if (!model && overModel) leftModelAt = performance.now();
    overModel = model;
  }
  if (hit) {
    clearTimeout(hoverTimer);
    hoverTimer = 0;
    document.body.classList.add('hover');
  } else if (!hoverTimer && document.body.classList.contains('hover')) {
    hoverTimer = setTimeout(() => { document.body.classList.remove('hover'); hoverTimer = 0; }, 1400);
  }
  if (hit === ignoring || ignoring === null) {
    ignoring = !hit;
    desktop.ignoreMouse(ignoring);
  }
}

// Flotando: arrastrar con el botón izquierdo mueve la ventana; con el derecho gira al modelo y con el central lo
// desplaza; la rueda cambia el tamaño de la ventana y Ctrl + rueda acerca o aleja la cámara hacia el cursor.
// Doble clic: vuelve al encuadre de siempre. Los oyentes están siempre puestos y solo actúan flotando.
{
  const canvas = $('canvas');
  addEventListener('mousemove', (e) => { if (floating) mouse = { x: e.clientX, y: e.clientY }; });
  document.addEventListener('mouseleave', () => { if (floating && !dragging && !rotating) mouse = null; });
  canvas.addEventListener('pointerdown', (e) => {
    if (!floating || !avatar || !avatar.probeHit || petWorking) return;
    if (e.button === 0) {
      press = { x: e.screenX, y: e.screenY, at: performance.now(), cx: e.clientX, cy: e.clientY };
      dragging = true;
      canvas.setPointerCapture(e.pointerId);
      desktop.drag('start');
    } else if (e.button === 1 || e.button === 2) {
      rotating = true;                               // el modelo se mueve y deja de estar bajo el cursor
    }
  });
  canvas.addEventListener('pointermove', () => { if (floating && dragging) desktop.drag('move'); });
  const endDrag = (e) => {
    // Un clic corto sin mover: la has tocado (la cabeza o el cuerpo).
    if (press && e && e.type === 'pointerup' && performance.now() - press.at < 320
        && Math.hypot(e.screenX - press.x, e.screenY - press.y) < 5 && avatar && petPrefs().react) {
      const zone = avatar.zoneAt(press.cx, press.cy) || 'body';
      touched(avatar.react(zone, avatar.zoneSide || 1));
    }
    press = null;
    if (dragging) { dragging = false; desktop.drag('end'); }
    rotating = false;
  };
  addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  addEventListener('wheel', (e) => {
    if (!floating) return;
    e.preventDefault();
    if (e.ctrlKey && avatar) avatar.zoom(e.deltaY < 0 ? 0.9 : 1 / 0.9);
    else desktop.resize(e.deltaY < 0 ? 1 : -1);
  }, { passive: false });
  canvas.addEventListener('dblclick', () => { if (avatar) avatar.resetView(); });
}

// Toques y miradas (16 nov 2026). En la ventana normal también: la cámara libre usa el arrastre, así que solo un clic
// corto y sin mover cuenta como tocarla. A veces lo comenta en voz alta (con su personalidad; el servidor decide
// cuándo, sin gastar cuota de más): al 3.er y al 6.º toque seguido en la misma parte, y al mirarla de cerca.
function voiceOn() { try { return localStorage.getItem('companion.react_voice') !== '0'; } catch { return true; } }
function voiceReact(msg) {
  if (!voiceOn() || !started || state !== 'idle') return;
  send(msg);
}
function touched(res) {
  if (res && res.level >= 2 && (res.n === 3 || res.n === 6)) voiceReact({ type: 'touch', zone: res.zone, level: res.level });
}
{
  const canvas = $('canvas');
  let click = null;
  canvas.addEventListener('pointerdown', (e) => {
    if (floating || e.button !== 0 || !avatar) return;
    click = { x: e.clientX, y: e.clientY, at: performance.now() };
  });
  canvas.addEventListener('pointerup', async (e) => {
    const c = click;
    click = null;
    if (floating || !c || !avatar || !petPrefs().react || performance.now() - c.at > 320 || Math.hypot(e.clientX - c.x, e.clientY - c.y) > 5) return;
    const r = canvas.getBoundingClientRect();
    const zone = await avatar.pickAt(e.clientX - r.left, e.clientY - r.top);
    if (zone) touched(avatar.react(zone, avatar.zoneSide || 1));
  });
}
const reactVoice = $('react-voice');
if (reactVoice) {
  reactVoice.checked = voiceOn();
  reactVoice.onchange = () => { try { localStorage.setItem('companion.react_voice', reactVoice.checked ? '1' : '0'); } catch { /* modo privado */ } };
}

// Para depurar desde la consola del navegador y para las pruebas automáticas.
window.companion = { avatar, audio, vision, send, handle, petPrefs, savePet,
  status: () => ({ started, floating, ignoring, state, petWorking }) };
connect();
