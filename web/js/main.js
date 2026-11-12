// Une todo: conexión con el servidor, audio, avatar, cámara/pantalla e interfaz.
import { AudioIO } from './audio.js';
import { Avatar } from './avatar.js';
import { Vision } from './vision.js';
import { initOnboarding } from './onboarding.js';

const $ = (id) => document.getElementById(id);
const clamp = (x) => Math.max(0, Math.min(1, x));
const STATUS = { idle: 'Te escucho', listening: 'Escuchando…', thinking: 'Pensando…', speaking: 'Hablando' };

// La app de escritorio (Electron) añade window.desktop y permite el modo flotante: una ventana transparente,
// sin marco y siempre encima de las demás. En un navegador normal esas opciones no aparecen.
const params = new URLSearchParams(location.search);
const desktop = window.desktop || null;
const floating = !!desktop && params.has('flotante');
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
    if (kind === 'screen' && stream) {
      const name = config ? config.name : 'Mika';
      const caption = figure.querySelector('figcaption');
      caption.textContent = detail?.surface === 'window' ? `${name} ve la ventana ${detail.name || 'elegida'}` : `${name} ve tu pantalla`;
      caption.title = detail?.name || '';
    }
    if (!stream) send({ type: 'frame_stop', source: kind });
    if (kind === 'camera') healMic(vision.lastCam);
  },
});

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
      : (vision.detail('screen')?.surface === 'window' ? 'una captura de esa ventana (solo de ella)' : 'una captura de esa pantalla');
    const live = watchOn() ? ' y, con la mirada en vivo, también cada pocos segundos por su cuenta' : '';
    toast(config.llm.provider === 'gemini'
      ? `${config.name} recibe ${what} con cada cosa que le digas${live}. Con el cerebro en la nube, esas imágenes se envían a ${config.cloud.name}.`
      : `${config.name} recibe ${what} con cada cosa que le digas${live}. Con el cerebro local no salen de esta PC.`);
  }
}
$('camera').onclick = () => toggleVision('camera');
$('screen').onclick = () => toggleVision('screen');
for (const b of document.querySelectorAll('[data-stop]')) b.onclick = () => vision.stop(b.dataset.stop);

// ---------------------------------------------------------------- bucle de dibujo
function tick() {
  const voice = audio.analyse();
  if (avatar) { avatar.setVoice(voice); avatar.update(); }
  $('orb').firstElementChild.style.setProperty('--level', clamp(voice.vol * 5).toFixed(3));
  const micLevel = clamp(audio.micLevel * 9).toFixed(3);
  $('mic').firstElementChild.style.setProperty('--level', micLevel);
  $('mic-meter').style.setProperty('--level', micLevel);
  $('mic-meter-2').style.setProperty('--level', micLevel);
  if (floating) updateHit();
  requestAnimationFrame(tick);
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
  }
}

function setState(value) {
  state = value;
  document.body.dataset.state = value;
  if (avatar) avatar.setState(value);
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
  $('brain').textContent = `${cloud ? 'Nube' : 'Local'} · ${cfg.llm.model}`;

  // Primera vez: la bienvenida (perfil, cerebro, voz, modelo). Lo último, micrófono y cámara, es la tarjeta de inicio.
  if (!cfg.onboarded && !welcomed && !floating && !autoStart) { welcomed = true; onboarding.start(); }
  for (const el of document.querySelectorAll('.ob-name')) el.textContent = cfg.name;
  const GENDER = { mujer: 'mujer', hombre: 'hombre', no_binario: 'no binario', '': 'género sin indicar' };
  $('me-line').textContent = cfg.profile.name ? `${cfg.profile.name} · ${cfg.profile.birth_year} · ${GENDER[cfg.profile.gender] || ''}` : 'Sin completar';
  $('cloud-name').textContent = cfg.cloud.name;
  $('cloud-line').textContent = cfg.cloud.has_key ? `${cfg.cloud.name}${cfg.cloud.model ? ' · ' + cfg.cloud.model : ''} · clave ${cfg.cloud.key_hint}` : 'Sin clave de API';
  $('voice-line').textContent = `${cfg.voice || 'Sin voz'} · ${(cfg.voice_engine_name || '').toLowerCase()}`;
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
    ? `Solo el texto de la conversación (y las imágenes de cámara o pantalla, si las compartes) viaja a ${cfg.cloud.name}. Tu voz y la de ${cfg.name} se procesan en esta PC.`
    : `Todo se procesa en esta PC${cfg.adult.active ? ', sin filtro para temas +18 si tú los propones' : ''}. El modelo comparte la memoria de vídeo con la voz: si no cabe (un juego, ComfyUI), ${cfg.name} usa uno más pequeño. Pulsa «Local» otra vez para que vuelva a elegir.`;
  $('watch-note').textContent = `Mientras compartes la cámara o la pantalla, ${cfg.name} mira cada pocos segundos y comenta por su cuenta lo que le llama la atención.`
    + (cloud ? ` Con la nube esas imágenes van a ${cfg.cloud.name} (modelo ${cfg.watch.model}).` : ' Con el cerebro local no salen de esta PC.');

  const health = [
    ['Cerebro', `${cloud ? cfg.cloud.name : 'Ollama'} · ${cfg.llm.model}`, cfg.llm.ready],
    ['Oído', cfg.stt.ready ? `Whisper ${cfg.stt.model} · ${cfg.stt.device === 'cuda' ? 'GPU' : 'CPU'}` : (cfg.stt.error ? 'Error' : 'Cargando…'), !cfg.stt.error],
    ['Voz', cfg.tts ? 'Nodo GPU · activa' : 'No disponible', cfg.tts],
    ['Modelo 3D', cfg.model ? (cfg.model_id === 'default' ? `${cfg.name} (por defecto)` : 'Modelo propio') : 'Falta el .vrm', cfg.model],
  ];
  if (cfg.llm.detail) health[0][1] += ` · ${cfg.llm.detail}`;
  if (cfg.gpu) {
    const gb = (mb) => (mb / 1024).toFixed(1).replace('.', ',');
    const full = cfg.gpu.used > cfg.gpu.total * 0.95;        // llena: el modelo local iría lento
    health.push(['Memoria de vídeo', `${gb(cfg.gpu.used)} de ${gb(cfg.gpu.total)} GB en uso${full ? ' · llena' : ''}`, !full || cloud]);
  }
  $('health').innerHTML = health.map(([k, v, ok]) => `<dt>${k}</dt><dd class="${ok ? '' : 'bad'}">${v}</dd>`).join('');

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

function showOrb(show) {
  $('orb').hidden = !show;
  $('model-hint').hidden = !show || !avatar || floating;
}

async function loadModel() {
  loadingModel = true;
  try {
    if (config && config.model_kind === 'orb') avatar.loadOrb();              // el personaje neutro no es un archivo
    else await avatar.load(`/api/model?v=${Date.now()}`);
    avatar.setState(state);
    showOrb(false);
  } catch (err) {
    console.error(err);
    showOrb(true);
    toast('No pude cargar el modelo 3D: ' + err.message, true);
  }
  loadingModel = false;
}

// Tras cambiar de modelo: vuelve a leer el estado y carga el que quedó activo (o el orbe si no hay ninguno).
async function reloadModel() {
  await refreshConfig();
  if (!avatar) return;
  if (config && config.model) await loadModel();
  else { avatar.unload(); showOrb(true); }
}

function renderModels(list) {
  const rows = [{ id: 'default', name: list.default.name, detail: list.default.available ? 'Por defecto' : 'Por defecto · falta el archivo' },
    ...(list.builtin || []).filter((m) => m.available).map((m) => ({ id: m.id, name: m.name, detail: m.note })),
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
if (navigator.mediaDevices) navigator.mediaDevices.addEventListener('devicechange', () => { fillMics(); fillCams(); });

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

  // Cámara: la elegida en la tarjeta de inicio o, al cambiar entre ventana y flotante, la que ya estaba encendida.
  const choice = $('cam-select').value;
  let resume = false;
  try { resume = autoStart && Date.now() - Number(localStorage.getItem(RESUME_KEY) || 0) < 20000; localStorage.removeItem(RESUME_KEY); } catch { /* modo privado */ }
  const wanted = resume || (!autoStart && choice && choice !== OFF && choice !== ASK);
  const preview = stopCamTest(wanted);                // la vista de prueba pasa a ser la cámara de Mika, sin cerrarla
  if (wanted) {
    camAllowed = true;
    try { await vision.start('camera', resume ? savedCam() : choice, preview); } catch (err) {
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
}
$('keyboard').onclick = () => showKeyboard($('text-form').hidden);

$('text-form').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('text-input').value.trim();
  if (!text) return;
  $('text-input').value = '';
  audio.flush();
  for (const kind of ['camera', 'screen']) vision.push(kind);     // que vea lo de este instante
  send({ type: 'text', text });
};

const openSettings = (open) => {
  $('settings').hidden = !open;
  if (!open) return;
  refreshConfig();
  refreshModels();
  refreshMemory();
  fillMics();
  fillCams();
  $('mic-allow-2').hidden = audio.hasMic;
};
$('open-settings').onclick = () => openSettings(true);
$('brain').onclick = () => openSettings(true);
$('close-settings').onclick = () => openSettings(false);
$('settings').onclick = (e) => { if (e.target === $('settings')) openSettings(false); };
addEventListener('keydown', (e) => { if (e.key === 'Escape') openSettings(false); });

for (const b of $('provider').children) b.onclick = () => postConfig({ provider: b.dataset.value });
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
// Al cambiar de ventana se abre una página nueva: si la cámara estaba encendida, la siguiente la vuelve a encender.
const RESUME_KEY = 'companion.resume.cam';
function switchWindow(toFloat) {
  try { if (vision.active('camera')) localStorage.setItem(RESUME_KEY, String(Date.now())); else localStorage.removeItem(RESUME_KEY); } catch { /* modo privado */ }
  desktop.float(toFloat);
}
$('float-btn').onclick = () => switchWindow(true);
$('dock').onclick = () => switchWindow(false);
$('quit').onclick = () => window.close();

// La ventana flotante es un rectángulo transparente. Para que no estorbe, los clics solo «tocan» a Mika y a
// sus botones; en el resto atraviesan hacia lo que haya debajo. Se decide cuadro a cuadro según el píxel
// que queda bajo el ratón.
let mouse = null;
let dragging = false;
let ignoring = null;
let hoverTimer = 0;

function updateHit() {
  if (avatar) avatar.probe = mouse;
  let hit = dragging;
  if (!hit && mouse) {
    const el = document.elementFromPoint(mouse.x, mouse.y);
    const onUi = !!(el && el.closest('.controls, #toast')) && document.body.classList.contains('hover');
    hit = onUi || (avatar ? avatar.probeHit : !$('orb').hidden);
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

if (floating) {
  const canvas = $('canvas');
  addEventListener('mousemove', (e) => { mouse = { x: e.clientX, y: e.clientY }; });
  document.addEventListener('mouseleave', () => { if (!dragging) mouse = null; });
  // Arrastrar a Mika mueve la ventana; la rueda la hace más grande o más pequeña.
  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || !avatar || !avatar.probeHit) return;
    dragging = true;
    canvas.setPointerCapture(e.pointerId);
    desktop.drag('start');
  });
  canvas.addEventListener('pointermove', () => { if (dragging) desktop.drag('move'); });
  const endDrag = () => { if (dragging) { dragging = false; desktop.drag('end'); } };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  addEventListener('wheel', (e) => { e.preventDefault(); desktop.resize(e.deltaY < 0 ? 1 : -1); }, { passive: false });
}

// Para depurar desde la consola del navegador y para las pruebas automáticas.
window.companion = { avatar, audio, vision, send, status: () => ({ started, floating, ignoring, state }) };
connect();
