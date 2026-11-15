// App de escritorio del companion (Electron). Muestra la interfaz que sirve el servidor local en dos modos:
//   · ventana normal
//   · flotante: ventana transparente, sin marco y siempre encima de las demás, con solo el avatar
// Solo hay una ventana viva a la vez, para que nunca haya dos conversaciones escuchando el micrófono.
//
//   desktop\electron\electron.exe desktop            (lo hace iniciar.ps1)
//   En el Mac lo carga desktop/mac.js (Companion.app) después de instalar y arrancar el servidor.
//
// Variables de entorno: COMPANION_URL (por defecto http://127.0.0.1:8200), COMPANION_STOP_ON_EXIT=1 apaga
// el servidor al cerrar (y el servidor vigila esta app: si muere sin cerrar bien, se apaga solo),
// COMPANION_SERVER_PID = el proceso del servidor que acaba de arrancar iniciar.ps1 (si se cierra, la pantalla de
// carga lo dice en vez de esperar), COMPANION_TEST=1 es para las pruebas automáticas (ventanas fuera de pantalla, sin
// sonido y con micrófono y cámara simulados).
const { app, BrowserWindow, ipcMain, session, desktopCapturer, screen, shell } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const URL_BASE = (process.env.COMPANION_URL || 'http://127.0.0.1:8200').replace(/\/$/, '');
const ORIGIN = new URL(URL_BASE).origin;
const TEST = process.env.COMPANION_TEST === '1';
const FLOAT_MIN = 220, FLOAT_MAX = 900, FLOAT_RATIO = 1.55;

app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');   // la voz suena sin un clic previo
if (TEST) {
  // Micrófono y cámara simulados, salvo en la prueba de dispositivos reales (scripts/prueba_dispositivos.py).
  if (process.env.COMPANION_TEST_REAL_MEDIA !== '1') app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('remote-debugging-port', process.env.COMPANION_TEST_PORT || '9334');
  app.setPath('userData', path.join(app.getPath('temp'), 'companion-pc-prueba'));   // perfil aparte del real
} else if (process.env.COMPANION_BOOTED === '1') {
  app.on('second-instance', () => { if (win && !win.isDestroyed()) { win.show(); win.focus(); } });   // el candado es de mac.js
} else if (!app.requestSingleInstanceLock()) {
  app.quit();                 // ya hay una Mika abierta: no se abre otra escuchando el mismo micrófono
} else {
  app.on('second-instance', () => { if (win && !win.isDestroyed()) { win.show(); win.focus(); } });
}

let win = null;
let mode = 'window';
let floatBounds = null;       // se recuerda dónde y de qué tamaño dejaste a Mika
let drag = null;
let picker = null;            // ventana «¿Qué quieres que vea Mika?»
let pickerSources = [];
let pickerDone = null;
let pickerOptions = { audio: false, audioOn: false };
let audioNext = 0;           // la próxima petición de pantalla es solo para el sonido (hasta este instante)
let lastShare = null;         // {kind: 'screen' | 'window', name, audio} de lo último que se compartió
// El sonido de la PC («loopback») solo se ofrece en Windows: para entenderlo hace falta el oído en una tarjeta
// NVIDIA (companion/screen_audio.py), y en el Mac Electron aún no lo da sin permisos aparte.
const CAN_AUDIO = process.platform === 'win32';
const prefsFile = () => path.join(app.getPath('userData'), 'compartir.json');
function shareAudioPref() {                // se recuerda si la última vez se compartió también el sonido
  try { return JSON.parse(fs.readFileSync(prefsFile(), 'utf8')).audio === true; } catch { return false; }
}
function saveShareAudioPref(on) {
  try { fs.writeFileSync(prefsFile(), JSON.stringify({ audio: !!on })); } catch { /* sin permiso: no pasa nada */ }
}

const webPreferences = () => ({
  preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true,
  backgroundThrottling: false,
});

function place(bounds) {
  return TEST ? { ...bounds, x: -4000, y: -4000 } : bounds;     // en pruebas, fuera de la pantalla
}

// ---------------------------------------------------------------- arranque: la ventana se abre ya
// iniciar.ps1 arranca el servidor y abre esta app sin esperar: mientras el servidor no responde se ve
// cargando.html (con el motivo si no llega a arrancar); luego, la interfaz, que enseña lo que falta por cargar.
let serverReady = false;
const ROOT_DIR = process.env.COMPANION_HOME || path.join(__dirname, '..');

function serverUp() {
  return new Promise((resolve) => {
    const req = http.get(`${URL_BASE}/api/config`, { timeout: 1500 }, (r) => { r.resume(); resolve(r.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

function serverAlive() {
  const pid = Number(process.env.COMPANION_SERVER_PID || 0);
  if (!pid) return true;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

let ownerSent = false;
function registerOwner() {          // si esta app muere sin cerrar bien, el servidor se apaga solo (lifecycle.py)
  if (ownerSent || process.env.COMPANION_STOP_ON_EXIT !== '1') return;
  ownerSent = true;
  const body = JSON.stringify({ pid: process.pid });
  const req = http.request(`${URL_BASE}/api/owner`, { method: 'POST', timeout: 3000,
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, (r) => r.resume());
  req.on('error', () => { ownerSent = false; });
  req.end(body);
}

async function boot(w, target) {
  const t0 = Date.now();
  const say = (title, text, failure = '') => {
    if (!w.isDestroyed()) w.webContents.executeJavaScript(`setEstado(${JSON.stringify(title)}, ${JSON.stringify(text)}, ${JSON.stringify(failure)})`).catch(() => {});
  };
  w.webContents.on('page-title-updated', (e, title) => {
    if (title === 'companion:registro') shell.openPath(path.join(ROOT_DIR, 'data', 'companion.log'));
    if (title === 'companion:cerrar') app.quit();
  });
  while (!w.isDestroyed()) {
    if (await serverUp()) {
      serverReady = true;
      registerOwner();
      if (!w.isDestroyed()) w.loadURL(target);
      return;
    }
    const s = (Date.now() - t0) / 1000;
    if (!serverAlive() || s > 180) {
      say('No se pudo abrir Companion', '', (serverAlive() ? 'El servidor local no respondió en 3 minutos.' : 'El servidor local se cerró al arrancar.')
        + ' El motivo suele estar al final del registro (Companion › data › companion.log). Si otro programa usa el puerto, cámbialo en .env (PORT=8202).');
      return;
    }
    say('Abriendo Companion', s < 6 ? 'Arrancando el servidor local…' : `Arrancando el servidor local… ${Math.round(s)} s (la primera vez tarda más)`);
    await new Promise((r) => setTimeout(r, 500));
  }
}

function createMain(resume) {
  mode = 'window';
  const w = new BrowserWindow({
    ...place({ width: 520, height: 880 }), minWidth: 380, minHeight: 560, backgroundColor: '#0c0b14',
    autoHideMenuBar: true, title: 'Mika', webPreferences: webPreferences(),
  });
  w.setMenuBarVisibility(false);
  const target = `${URL_BASE}/${resume ? '?auto=1&saludo=0' : ''}`;
  if (serverReady || resume) {
    w.loadURL(target);
  } else {
    w.loadFile(path.join(__dirname, 'cargando.html'));
    w.webContents.once('did-finish-load', () => boot(w, target));
  }
  return w;
}

function createFloat() {
  mode = 'float';
  const area = screen.getPrimaryDisplay().workArea;
  const width = 340, height = Math.round(width * FLOAT_RATIO);
  const bounds = floatBounds || { width, height, x: area.x + area.width - width - 28, y: area.y + area.height - height - 12 };
  const w = new BrowserWindow({
    ...place(bounds), transparent: true, frame: false, resizable: false, maximizable: false, fullscreenable: false,
    hasShadow: false, backgroundColor: '#00000000', title: 'Mika', webPreferences: webPreferences(),
  });
  w.setAlwaysOnTop(true, 'screen-saver');           // por encima también de las ventanas a pantalla completa sin borde
  w.setVisibleOnAllWorkspaces(true);
  w.on('moved', () => { if (!TEST) floatBounds = w.getBounds(); });
  w.loadURL(`${URL_BASE}/?flotante=1&auto=1&saludo=0`);
  return w;
}

function open(next, resume) {
  const old = win;
  win = next === 'float' ? createFloat() : createMain(resume);
  if (TEST) win.webContents.setAudioMuted(true);
  const current = win;
  current.on('closed', () => {
    if (win !== current) return;
    win = null;
    if (picker && !picker.isDestroyed()) picker.destroy();      // sin Mika no queda nada que elegir (y la app se cierra)
  });
  // Enlaces externos: en el navegador del sistema, nunca dentro de la ventana del companion.
  current.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url) && new URL(url).origin !== ORIGIN) shell.openExternal(url);
    return { action: 'deny' };
  });
  current.webContents.on('will-navigate', (e, url) => { if (new URL(url).origin !== ORIGIN) e.preventDefault(); });
  if (picker && !picker.isDestroyed()) picker.destroy();        // la petición era de la ventana que se va
  if (old && !old.isDestroyed()) old.destroy();
}

const fromOurPage = (e) => {
  try { return new URL(e.senderFrame.url).origin === ORIGIN; } catch { return false; }
};

ipcMain.handle('companion:float', (e, on) => {
  if (!fromOurPage(e)) return false;
  if (mode === 'float' && win && !win.isDestroyed() && !TEST) floatBounds = win.getBounds();
  open(on ? 'float' : 'window', true);
  return true;
});

ipcMain.on('companion:ignore-mouse', (e, ignore) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (w && mode === 'float' && fromOurPage(e)) w.setIgnoreMouseEvents(!!ignore, { forward: true });
});

ipcMain.on('companion:drag', (e, phase) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (!w || mode !== 'float' || !fromOurPage(e)) return;
  const cursor = screen.getCursorScreenPoint();
  if (phase === 'start') {
    const b = w.getBounds();
    drag = { dx: cursor.x - b.x, dy: cursor.y - b.y, width: b.width, height: b.height };
  } else if (phase === 'move' && drag) {
    w.setBounds({ x: cursor.x - drag.dx, y: cursor.y - drag.dy, width: drag.width, height: drag.height });
  } else {
    drag = null;
    if (!TEST) floatBounds = w.getBounds();
  }
});

ipcMain.on('companion:resize', (e, step) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (!w || mode !== 'float' || !fromOurPage(e)) return;
  const b = w.getBounds();
  const width = Math.max(FLOAT_MIN, Math.min(FLOAT_MAX, Math.round(b.width * (step > 0 ? 1.08 : 1 / 1.08))));
  const height = Math.round(width * FLOAT_RATIO);
  // Crece desde los pies: el centro inferior de la ventana no se mueve.
  w.setBounds({ x: Math.round(b.x + (b.width - width) / 2), y: b.y + b.height - height, width, height });
  if (!TEST) floatBounds = w.getBounds();
});

// ---------------------------------------------------------------- elegir qué se comparte
// Lista pantallas y ventanas (sin las del propio companion) y deja elegir una en una ventana aparte, que
// sirve igual en modo normal y en modo flotante. Devuelve {id, name, kind, audio} o null si se cancela.
// `audio`: ofrecer el interruptor «Escuchar también el sonido».
async function pickSource(audio) {
  if (picker && !picker.isDestroyed()) picker.destroy();        // una petición anterior sin responder
  const found = await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 400, height: 250 } });
  const mine = win && !win.isDestroyed() ? win.getMediaSourceId() : '';
  const displays = screen.getAllDisplays();
  const cursor = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const list = [];
  for (const s of found) {
    if (s.id === mine) continue;
    if (s.id.startsWith('screen:')) {
      const n = displays.findIndex((d) => String(d.id) === s.display_id);
      const d = displays[n];
      let name = displays.length > 1 && n >= 0 ? `Pantalla ${n + 1}` : 'Pantalla completa';
      if (d) name += ` (${Math.round(d.size.width * d.scaleFactor)}×${Math.round(d.size.height * d.scaleFactor)})`;
      if (displays.length > 1 && d && d.id === cursor.id) name += ' · aquí está el cursor';
      list.push({ id: s.id, kind: 'screen', name, thumbnail: s.thumbnail.isEmpty() ? '' : s.thumbnail.toDataURL() });
    } else if (s.name.trim()) {
      list.push({ id: s.id, kind: 'window', name: s.name.trim().slice(0, 120), thumbnail: s.thumbnail.isEmpty() ? '' : s.thumbnail.toDataURL() });
    }
  }

  const area = cursor.workArea;
  const width = Math.min(820, area.width - 40), height = Math.min(640, area.height - 40);
  const w = new BrowserWindow({
    ...place({ width, height, x: Math.round(area.x + (area.width - width) / 2), y: Math.round(area.y + (area.height - height) / 2) }),
    minWidth: 420, minHeight: 360, backgroundColor: '#0c0b14', autoHideMenuBar: true, title: 'Compartir con Mika',
    minimizable: false, maximizable: false, fullscreenable: false,
    webPreferences: { preload: path.join(__dirname, 'picker-preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  picker = w;
  pickerSources = list;
  pickerOptions = { audio: CAN_AUDIO && audio, audioOn: shareAudioPref() };
  w.setMenuBarVisibility(false);
  w.setAlwaysOnTop(true, 'screen-saver');           // que no quede tapada por Mika flotante
  w.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  w.webContents.on('will-navigate', (e) => e.preventDefault());
  w.loadFile(path.join(__dirname, 'picker.html'));
  return new Promise((resolve) => {
    pickerDone = (id, withAudio) => {
      pickerDone = null;
      const s = list.find((x) => x.id === id);
      if (s && pickerOptions.audio) saveShareAudioPref(withAudio);
      resolve(s ? { ...s, audio: !!(withAudio && pickerOptions.audio) } : null);
      if (!w.isDestroyed()) w.destroy();
    };
    w.on('closed', () => {
      if (picker === w) { picker = null; pickerSources = []; }
      if (pickerDone) { pickerDone = null; resolve(null); }
    });
  });
}

const fromPicker = (e) => picker && !picker.isDestroyed() && e.sender === picker.webContents;
ipcMain.handle('picker:sources', (e) => (fromPicker(e) ? pickerSources : []));
ipcMain.handle('picker:options', (e) => (fromPicker(e) ? pickerOptions : null));
ipcMain.on('picker:choose', (e, id, withAudio) => { if (fromPicker(e) && pickerDone) pickerDone(String(id || ''), withAudio === true); });

// El sonido de la PC se pide aparte, después de la imagen: la página avisa con esto y la siguiente petición
// de pantalla no abre la ventana de selección (ver setDisplayMediaRequestHandler).
ipcMain.handle('companion:share-audio-next', (e, on) => {
  if (!fromOurPage(e)) return false;
  if (on === false || !lastShare || !lastShare.audio) { audioNext = 0; return false; }   // false: ya no hace falta
  audioNext = Date.now() + 10000;
  return true;
});

// Qué se eligió la última vez (pantalla o ventana y su nombre), para que la página se lo cuente a Mika.
ipcMain.handle('companion:share-info', (e) => (fromOurPage(e) ? lastShare : null));

ipcMain.handle('companion:info', (e) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  return w ? { mode, alwaysOnTop: w.isAlwaysOnTop(), bounds: w.getBounds(), electron: process.versions.electron } : null;
});

app.whenReady().then(async () => {
  // La interfaz se sirve desde el servidor local: nada de usar una copia vieja guardada por la ventana.
  await session.defaultSession.clearCache().catch(() => {});

  // Micrófono, cámara y pantalla: solo para la página del companion (Electron no pregunta por su cuenta;
  // el permiso se pide dentro de la propia interfaz).
  const allowed = new Set(['media', 'mediaKeySystem', 'display-capture', 'clipboard-sanitized-write', 'speaker-selection']);
  const ours = (url) => { try { return new URL(url).origin === ORIGIN; } catch { return false; } };
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) =>
    callback(allowed.has(permission) && ours(details.requestingUrl || wc.getURL())));
  session.defaultSession.setPermissionCheckHandler((wc, permission, origin) => allowed.has(permission) && ours(origin));

  // «Compartir pantalla» abre una ventana para elegir una pantalla o una sola ventana: Mika ve solo eso.
  session.defaultSession.setDisplayMediaRequestHandler(async (request, callback) => {
    const fromUs = ours(request.securityOrigin || (request.frame && request.frame.url) || '');
    if (fromUs && Date.now() < audioNext) {
      // Solo el sonido de la PC («loopback»). Se da junto con una pantalla, que es como lo documenta Electron y
      // como funciona en Windows (junto a una sola ventana puede fallar); la página descarta esa imagen al
      // instante. Si falla, la imagen ya compartida sigue: el sonido nunca estropea el compartir.
      audioNext = 0;
      try {
        const screens = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 0, height: 0 } });
        if (!screens.length || !request.audioRequested) return callback(null);
        return callback({ video: screens[0], audio: 'loopback' });
      } catch (err) {
        console.error('No pude preparar el sonido de la PC:', err);
        try { callback(null); } catch { /* ya respondida */ }
        return;
      }
    }
    let chosen = null;
    try {
      if (fromUs) chosen = await pickSource(true);    // el sonido se pide después, aparte (ver arriba)
    } catch (err) {
      console.error('No pude listar pantallas y ventanas:', err);
    }
    try {
      if (!chosen) return callback(null);          // cancelado: getDisplayMedia() se rechaza con AbortError
      // Con «Escuchar también el sonido», la página pide después el de toda la PC (companion:share-audio-next;
      // Windows no deja separar el de una sola ventana). La voz de Mika también suena ahí: la interfaz no envía
      // ese audio mientras ella habla.
      lastShare = { kind: chosen.kind, name: chosen.name, audio: chosen.audio };
      callback({ video: { id: chosen.id, name: chosen.name } });
    } catch (err) {
      console.error('La ventana que pidió compartir ya no existe:', err.message);
    }
  });

  // Solo en las pruebas: una ventana propia con un texto conocido, para compartir «una ventana» sin tocar
  // ninguna ventana real del usuario.
  if (TEST && process.env.COMPANION_TEST_CARD === '1') {
    const card = new BrowserWindow({ ...place({ width: 900, height: 560 }), title: 'Tarjeta de prueba del companion', skipTaskbar: true,
      autoHideMenuBar: true, webPreferences: { sandbox: true, backgroundThrottling: false } });
    card.on('page-title-updated', (e) => e.preventDefault());
    card.loadFile(path.join(__dirname, 'tarjeta-prueba.html'));
  }

  open('window', false);
});

app.on('window-all-closed', () => app.quit());

app.on('will-quit', () => {
  if (process.env.COMPANION_STOP_ON_EXIT !== '1') return;
  // Al cerrar a Mika se apaga todo lo que arrancó el companion: el servidor (con un apagado ordenado), la voz
  // completa, el modelo local de Ollama y Ollama si lo abrió él (detener.ps1 / detener.sh).
  const root = ROOT_DIR;
  if (process.platform === 'win32') {
    spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(root, 'detener.ps1')],
      { detached: true, stdio: 'ignore', windowsHide: true }).unref();
  } else {
    spawn('/bin/bash', [path.join(root, 'detener.sh')], { cwd: root, detached: true, stdio: 'ignore' }).unref();
  }
});
