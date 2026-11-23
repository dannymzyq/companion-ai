// Companion Live Demo — Cliente directo de Gemini Live API (BidiGenerateContent) en el navegador.
// Sin servidor intermedio: la clave API del usuario se conecta directamente a Google.

const WS_ENDPOINT =
  'wss://generativelanguage.googleapis.com/ws/' +
  'google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';

const OUTPUT_SAMPLE_RATE = 24000;
const STORAGE_KEY = 'companion_live_demo_cfg_v1';

const EMOTIONS = [
  'neutral', 'feliz', 'emocionada', 'pensativa', 'triste',
  'sorprendida', 'sonrojada', 'carinosa', 'molesta'
];

const PERSONALITIES = [
  {
    id: 'confianza',
    name: 'De confianza',
    mood: 'feliz',
    prompt: 'Eres Mika, una compañera cercana, ordenada y con humor ligero e ironía cariñosa. Usas muletillas como «a ver» y «listo».'
  },
  {
    id: 'energia',
    name: 'Pura energía',
    mood: 'emocionada',
    prompt: 'Eres Mika con energía desbordante: entusiasmo contagioso, frases cortas y vivas, celebras cada logro.'
  },
  {
    id: 'ironia',
    name: 'Ironía fina',
    mood: 'pensativa',
    prompt: 'Eres Mika con sarcasmo elegante y remates rápidos, seca y ocurrente pero siempre ayudas y nunca eres cruel.'
  },
  {
    id: 'timidez',
    name: 'Corazón tímido',
    mood: 'sonrojada',
    prompt: 'Eres Mika en modo dulce y tímida: voz pausada, los halagos te ponen nerviosa, pero escuchas con mucha atención.'
  },
  {
    id: 'profesional',
    name: 'Modo profesional',
    mood: 'neutral',
    prompt: 'Eres Mika en modo profesional: seria, cordial, clara, priorizas y vas directa al siguiente paso.'
  },
  {
    id: 'calma',
    name: 'Calma total',
    mood: 'neutral',
    prompt: 'Eres Mika serena y reflexiva: hablas sin prisa, ayudas a respirar y a ver las cosas con perspectiva.'
  },
  {
    id: 'orgullo',
    name: 'Orgullo y ternura',
    mood: 'sonrojada',
    prompt: 'Eres Mika con estilo tsundere: orgullo por fuera, ternura por dentro; protestas un poco antes de ayudar.'
  },
  {
    id: 'caos',
    name: 'Caos simpático',
    mood: 'feliz',
    prompt: 'Eres Mika bromista y ocurrente: sueltas datos curiosos y juegos de palabras, y luego ayudas de verdad.'
  }
];

const EMO_PATTERNS = [
  ['triste', /lo siento|qu[eé] pena|qu[eé] triste|qu[eé] mal|\bpobre|lamento|\bánimo/i],
  ['molesta', /\boye\b|qu[eé] pesad|no me gusta|me molesta|ya basta|qu[eé] rabia/i],
  ['sorprendida', /\bwow\b|en serio\?|de verdad\?|no me digas|no puede ser/i],
  ['emocionada', /qu[eé] emoci[oó]n|incre[ií]ble|felicidades|enhorabuena|me encanta|\bgenial\b/i],
  ['sonrojada', /me sonroj|qu[eé] cosas dices|ay,? (calla|para)/i],
  ['carinosa', /cari[nñ]o|aqu[ií] estoy|te quiero|mi vida|\babrazo/i],
  ['feliz', /\bjaj|\bjej|qu[eé] bien|me alegra|\bbonito|claro que s[ií]/i],
  ['pensativa', /\bhmm|d[eé]jame pensar|\ba ver\b|buena pregunta/i]
];

// --- Referencias del DOM ---
const $ = (id) => document.getElementById(id);
const statusText = $('status-text');
const chipPersona = $('chip-persona');
const chipEmo = $('chip-emo');
const capUser = $('cap-user');
const capAi = $('cap-ai');
const toastEl = $('toast');
const orbCore = $('orb-core');
const audioBars = Array.from($('audio-bars').querySelectorAll('span'));

const btnConnect = $('btn-connect');
const btnConnectLabel = $('btn-connect-label');
const btnMic = $('btn-mic');
const btnCam = $('btn-cam');
const btnScreen = $('btn-screen');
const textForm = $('text-form');
const textInput = $('text-input');
const btnSend = $('btn-send');

const visionPip = $('vision-pip');
const visionVideo = $('vision-video');
const visionLabel = $('vision-label');

const settingsModal = $('settings-modal');
const settingsForm = $('settings-form');
const btnSettings = $('btn-settings');
const btnCloseModal = $('btn-close-modal');
const btnToggleKey = $('btn-toggle-key');
const btnClearKey = $('btn-clear-key');
const inputApiKey = $('input-api-key');
const inputRemember = $('input-remember');
const inputUserName = $('input-user-name');
const selectVoice = $('select-voice');
const selectPersona = $('select-persona');
const selectModel = $('select-model');

// --- Estado de la sesión ---
let cfg = {
  apiKey: '',
  remember: false,
  userName: '',
  voice: 'Aoede',
  personaId: 'confianza',
  model: 'gemini-3.1-flash-live-preview'
};

let ws = null;
let connected = false;

// Audio salida (24 kHz PCM)
let outCtx = null;
let analyser = null;
let nextPlayTime = 0;
let activeSources = [];
let speakingTimer = null;

// Audio entrada (16 kHz PCM)
let micCtx = null;
let micStream = null;
let micNode = null;
let micActive = false;

// Visión (cámara o pantalla)
let visionStream = null;
let visionMode = null; // 'cam' | 'screen' | null
let visionTimer = null;
const captureCanvas = document.createElement('canvas');
const captureCtx = captureCanvas.getContext('2d');

// Transcripción acumulada por turno
let curInText = '';
let curOutText = '';

// --- Utilidades ---
function showToast(msg) {
  if (!msg) {
    toastEl.classList.add('hidden');
    toastEl.textContent = '';
    return;
  }
  toastEl.textContent = msg;
  toastEl.classList.remove('hidden');
}

function setState(state, label) {
  document.body.dataset.state = state;
  if (label) statusText.textContent = label;
}

function setEmotion(emo) {
  const safe = EMOTIONS.includes(emo) ? emo : 'neutral';
  document.body.dataset.emo = safe;
  chipEmo.textContent = safe;
}

function guessEmotion(text) {
  for (const [emo, rx] of EMO_PATTERNS) {
    if (rx.test(text || '')) return emo;
  }
  return null;
}

function getPersona() {
  return PERSONALITIES.find((p) => p.id === cfg.personaId) || PERSONALITIES[0];
}

function updatePersonaChip() {
  const p = getPersona();
  chipPersona.textContent = `Mika · ${p.name}`;
  if (!connected) setEmotion(p.mood);
}

function bytesToBase64(bytes) {
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

function base64ToInt16(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

// --- Configuración y Modal ---
function loadConfig() {
  PERSONALITIES.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    selectPersona.appendChild(opt);
  });

  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (saved && typeof saved === 'object') {
      cfg = { ...cfg, ...saved };
    }
  } catch { /* ignorar */ }

  inputApiKey.value = cfg.apiKey || '';
  inputRemember.checked = Boolean(cfg.remember && cfg.apiKey);
  inputUserName.value = cfg.userName || '';
  selectVoice.value = cfg.voice || 'Aoede';
  selectPersona.value = cfg.personaId || 'confianza';
  selectModel.value = cfg.model || 'gemini-3.1-flash-live-preview';
  updatePersonaChip();
}

function openSettings() {
  settingsModal.classList.remove('hidden');
  setTimeout(() => inputApiKey.focus(), 40);
}

function closeSettings() {
  settingsModal.classList.add('hidden');
}

btnSettings.addEventListener('click', openSettings);
btnCloseModal.addEventListener('click', closeSettings);
settingsModal.addEventListener('click', (e) => {
  if (e.target === settingsModal) closeSettings();
});

btnToggleKey.addEventListener('click', () => {
  const isPwd = inputApiKey.type === 'password';
  inputApiKey.type = isPwd ? 'text' : 'password';
  btnToggleKey.textContent = isPwd ? 'Ocultar' : 'Mostrar';
});

btnClearKey.addEventListener('click', () => {
  cfg.apiKey = '';
  cfg.remember = false;
  inputApiKey.value = '';
  inputRemember.checked = false;
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignorar */ }
  showToast('Clave borrada del navegador.');
});

settingsForm.addEventListener('submit', (e) => {
  e.preventDefault();
  cfg.apiKey = inputApiKey.value.trim();
  cfg.remember = inputRemember.checked;
  cfg.userName = inputUserName.value.trim();
  cfg.voice = selectVoice.value;
  cfg.personaId = selectPersona.value;
  cfg.model = selectModel.value;
  updatePersonaChip();

  try {
    const toStore = {
      userName: cfg.userName,
      voice: cfg.voice,
      personaId: cfg.personaId,
      model: cfg.model,
      remember: cfg.remember,
      apiKey: cfg.remember ? cfg.apiKey : ''
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore));
  } catch { /* ignorar */ }

  closeSettings();
  showToast('');
  if (cfg.apiKey && !connected) {
    connectLive();
  }
});

// --- Reproducción de audio PCM 24 kHz ---
function ensureOutAudio() {
  if (!outCtx) {
    outCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: OUTPUT_SAMPLE_RATE });
    analyser = outCtx.createAnalyser();
    analyser.fftSize = 64;
    analyser.connect(outCtx.destination);
    startVisualizerLoop();
  }
  if (outCtx.state === 'suspended') outCtx.resume();
}

function playPcm24k(b64) {
  ensureOutAudio();
  const int16 = base64ToInt16(b64);
  if (!int16.length) return;
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

  const buf = outCtx.createBuffer(1, float32.length, OUTPUT_SAMPLE_RATE);
  buf.getChannelData(0).set(float32);

  const src = outCtx.createBufferSource();
  src.buffer = buf;
  src.connect(analyser);

  const now = outCtx.currentTime;
  const startAt = Math.max(now + 0.02, nextPlayTime);
  src.start(startAt);
  nextPlayTime = startAt + buf.duration;

  activeSources.push(src);
  src.onended = () => {
    activeSources = activeSources.filter((s) => s !== src);
  };

  setState('speaking', 'Hablando');
  clearTimeout(speakingTimer);
  const remainMs = Math.max(250, (nextPlayTime - outCtx.currentTime) * 1000 + 180);
  speakingTimer = setTimeout(() => {
    if (connected) setState('listening', micActive ? 'En vivo · Escuchando' : 'En vivo');
  }, remainMs);
}

function stopPlayback() {
  activeSources.forEach((s) => {
    try { s.stop(); } catch { /* ignorar */ }
  });
  activeSources = [];
  if (outCtx) nextPlayTime = outCtx.currentTime;
  clearTimeout(speakingTimer);
}

// Visualizador reactivo del orbe y las barras
let vizRunning = false;
function startVisualizerLoop() {
  if (vizRunning) return;
  vizRunning = true;
  const freq = new Uint8Array(32);

  function tick() {
    if (analyser && document.body.dataset.state === 'speaking') {
      analyser.getByteFrequencyData(freq);
      let sum = 0;
      audioBars.forEach((bar, i) => {
        const val = freq[i + 1] || 0;
        sum += val;
        const h = 5 + (val / 255) * 23;
        bar.style.height = `${h.toFixed(1)}px`;
      });
      const avg = sum / (audioBars.length * 255);
      orbCore.style.transform = `scale(${(1 + avg * 0.14).toFixed(3)})`;
    } else {
      audioBars.forEach((bar) => { bar.style.height = '5px'; });
      orbCore.style.transform = '';
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// --- Micrófono 16 kHz PCM ---
async function startMic() {
  if (micActive) return;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });
    micCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = micCtx.createMediaStreamSource(micStream);

    if (micCtx.audioWorklet) {
      await micCtx.audioWorklet.addModule('mic-worklet.js');
      micNode = new AudioWorkletNode(micCtx, 'mic-capture');
      micNode.port.onmessage = (ev) => {
        if (!connected || !ws || ws.readyState !== WebSocket.OPEN) return;
        const { pcm, level } = ev.data || {};
        if (!pcm) return;
        if (document.body.dataset.state === 'listening' && level > 0.015) {
          audioBars.forEach((bar, i) => {
            const wave = Math.sin(Date.now() * 0.012 + i) * 0.5 + 0.5;
            bar.style.height = `${(5 + Math.min(1, level * 7) * 20 * wave).toFixed(1)}px`;
          });
        }
        sendJson({
          realtimeInput: {
            audio: {
              mimeType: 'audio/pcm;rate=16000',
              data: bytesToBase64(new Uint8Array(pcm))
            }
          }
        });
      };
      source.connect(micNode);
      micNode.connect(micCtx.destination);
    }

    micActive = true;
    btnMic.classList.add('active');
    if (connected && document.body.dataset.state !== 'speaking') {
      setState('listening', 'En vivo · Escuchando');
    }
  } catch (err) {
    showToast(`No se pudo activar el micrófono: ${err.message || err}`);
  }
}

function stopMic() {
  micActive = false;
  btnMic.classList.remove('active');
  if (micNode) {
    try { micNode.disconnect(); } catch { /* ignorar */ }
    micNode = null;
  }
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }
  if (micCtx) {
    try { micCtx.close(); } catch { /* ignorar */ }
    micCtx = null;
  }
  if (connected && document.body.dataset.state !== 'speaking') {
    setState('listening', 'En vivo · Mic silenciado');
  }
}

// --- Visión (Cámara / Pantalla) ---
async function startVision(mode) {
  if (visionMode === mode) {
    stopVision();
    return;
  }
  stopVision();
  try {
    visionStream = mode === 'cam'
      ? await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 } } })
      : await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 } });

    visionMode = mode;
    visionVideo.srcObject = visionStream;
    visionLabel.textContent = mode === 'cam' ? 'Cámara activa' : 'Pantalla compartida';
    visionPip.classList.remove('hidden');
    btnCam.classList.toggle('active', mode === 'cam');
    btnScreen.classList.toggle('active', mode === 'screen');

    visionStream.getVideoTracks()[0].addEventListener('ended', stopVision);

    visionTimer = setInterval(() => {
      if (!connected || !visionVideo.videoWidth) return;
      const maxW = 768;
      const scale = Math.min(1, maxW / visionVideo.videoWidth);
      captureCanvas.width = Math.round(visionVideo.videoWidth * scale);
      captureCanvas.height = Math.round(visionVideo.videoHeight * scale);
      captureCtx.drawImage(visionVideo, 0, 0, captureCanvas.width, captureCanvas.height);
      const dataUrl = captureCanvas.toDataURL('image/jpeg', 0.72);
      const b64 = dataUrl.split(',')[1];
      if (b64) {
        sendJson({
          realtimeInput: {
            video: { mimeType: 'image/jpeg', data: b64 }
          }
        });
      }
    }, 1500);
  } catch (err) {
    showToast(`No se pudo compartir ${mode === 'cam' ? 'la cámara' : 'la pantalla'}: ${err.message || err}`);
  }
}

function stopVision() {
  clearInterval(visionTimer);
  visionTimer = null;
  if (visionStream) {
    visionStream.getTracks().forEach((t) => t.stop());
    visionStream = null;
  }
  visionVideo.srcObject = null;
  visionPip.classList.add('hidden');
  visionMode = null;
  btnCam.classList.remove('active');
  btnScreen.classList.remove('active');
}

// --- Conexión Gemini Live WebSocket ---
function sendJson(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function buildSystemInstruction() {
  const p = getPersona();
  const who = cfg.userName ? `Hablas con ${cfg.userName}.` : 'Hablas directamente con el usuario.';
  return [
    p.prompt,
    who,
    'Respondes en español con voz natural, cercana y breve, como en una llamada real. Nada de tono de asistente robótica.',
    'Tu cara cambia llamando a la herramienta `expresar` al empezar cada respuesta con tu emoción real. No esperes su resultado y sigue hablando.',
    'Nunca digas en voz alta etiquetas entre corchetes ni nombres de herramientas.',
    'Estás en la versión web ligera de Companion (en el navegador), así que si te piden abrir apps o archivos del PC explica amablemente que eso está disponible en la app de escritorio Companion.'
  ].join('\n');
}

function buildSetupPayload() {
  const modelName = cfg.model.startsWith('models/') ? cfg.model : `models/${cfg.model}`;
  return {
    setup: {
      model: modelName,
      generationConfig: {
        responseModalities: ['AUDIO'],
        speechConfig: {
          voiceConfig: {
            prebuiltVoiceConfig: { voiceName: cfg.voice || 'Aoede' }
          }
        }
      },
      systemInstruction: {
        parts: [{ text: buildSystemInstruction() }]
      },
      inputAudioTranscription: {},
      outputAudioTranscription: {},
      tools: [
        {
          functionDeclarations: [
            {
              name: 'expresar',
              description: 'Muestra en tu cara la emoción que sientes al empezar tu respuesta.',
              behavior: 'NON_BLOCKING',
              parameters: {
                type: 'OBJECT',
                properties: {
                  emocion: { type: 'STRING', enum: EMOTIONS }
                },
                required: ['emocion']
              }
            }
          ]
        }
      ]
    }
  };
}

function setControlsEnabled(enabled) {
  btnMic.disabled = !enabled;
  btnCam.disabled = !enabled;
  btnScreen.disabled = !enabled;
  textInput.disabled = !enabled;
  btnSend.disabled = !enabled;
}

async function connectLive() {
  if (!cfg.apiKey) {
    openSettings();
    return;
  }
  showToast('');
  ensureOutAudio();
  setState('connecting', 'Conectando con Gemini Live…');
  btnConnect.disabled = true;

  const url = `${WS_ENDPOINT}?key=${encodeURIComponent(cfg.apiKey)}`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    sendJson(buildSetupPayload());
  };

  ws.onmessage = async (event) => {
    let raw = event.data;
    if (raw instanceof Blob) raw = await raw.text();
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }

    if (msg.setupComplete) {
      connected = true;
      btnConnect.disabled = false;
      btnConnect.classList.add('connected');
      btnConnectLabel.textContent = 'Colgar';
      setControlsEnabled(true);
      setEmotion(getPersona().mood);
      setState('listening', 'En vivo · Escuchando');
      capUser.textContent = '';
      capAi.textContent = '¡Conectado! Háblame o escríbeme lo que quieras.';
      await startMic();
      return;
    }

    if (msg.toolCall && Array.isArray(msg.toolCall.functionCalls)) {
      const responses = msg.toolCall.functionCalls.map((fc) => {
        if (fc.name === 'expresar' && fc.args && fc.args.emocion) {
          setEmotion(fc.args.emocion);
        }
        return {
          id: fc.id,
          name: fc.name,
          response: { ok: true, scheduling: 'SILENT' }
        };
      });
      sendJson({ toolResponse: { functionResponses: responses } });
    }

    const sc = msg.serverContent;
    if (!sc) return;

    if (sc.interrupted) {
      stopPlayback();
      curOutText = '';
      setState('listening', micActive ? 'En vivo · Escuchando' : 'En vivo');
    }

    if (sc.inputTranscription && sc.inputTranscription.text) {
      curInText += sc.inputTranscription.text;
      capUser.textContent = `Tú: «${curInText.trim()}»`;
    }

    if (sc.outputTranscription && sc.outputTranscription.text) {
      curOutText += sc.outputTranscription.text;
      const clean = curOutText.replace(/\[[^\]]+\]/g, '').trim();
      if (clean) {
        capAi.textContent = `«${clean}»`;
        const guessed = guessEmotion(clean);
        if (guessed) setEmotion(guessed);
      }
    }

    if (sc.modelTurn && Array.isArray(sc.modelTurn.parts)) {
      for (const part of sc.modelTurn.parts) {
        const inline = part && part.inlineData;
        if (inline && inline.data && (!inline.mimeType || inline.mimeType.startsWith('audio/pcm'))) {
          playPcm24k(inline.data);
        }
      }
    }

    if (sc.turnComplete) {
      curInText = '';
      curOutText = '';
    }
  };

  ws.onerror = () => {
    showToast('Error de conexión con Gemini Live. Revisa tu clave API o el modelo en Ajustes.');
  };

  ws.onclose = (ev) => {
    const wasConnected = connected;
    disconnectLive(false);
    if (!wasConnected && ev.code !== 1000) {
      showToast(`No se pudo iniciar la sesión (código ${ev.code}${ev.reason ? `: ${ev.reason}` : ''}). Verifica tu clave de Gemini.`);
    }
  };
}

function disconnectLive(closeSocket = true) {
  connected = false;
  stopMic();
  stopVision();
  stopPlayback();

  if (closeSocket && ws) {
    try { ws.close(1000, 'user_disconnect'); } catch { /* ignorar */ }
  }
  ws = null;
  curInText = '';
  curOutText = '';

  btnConnect.disabled = false;
  btnConnect.classList.remove('connected');
  btnConnectLabel.textContent = 'Conectar en vivo';
  setControlsEnabled(false);
  setState('idle', 'Desconectado');
}

// --- Eventos de controles ---
btnConnect.addEventListener('click', () => {
  if (connected) disconnectLive(true);
  else connectLive();
});

btnMic.addEventListener('click', () => {
  if (micActive) stopMic();
  else startMic();
});

btnCam.addEventListener('click', () => startVision('cam'));
btnScreen.addEventListener('click', () => startVision('screen'));

textForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const txt = textInput.value.trim();
  if (!txt || !connected) return;
  textInput.value = '';
  capUser.textContent = `Tú: «${txt}»`;
  curOutText = '';
  sendJson({
    clientContent: {
      turns: [{ role: 'user', parts: [{ text: txt }] }],
      turnComplete: true
    }
  });
});

// Inicialización
loadConfig();
if (!cfg.apiKey) {
  openSettings();
}
