// App de escritorio del companion (Electron). Muestra la interfaz que sirve el servidor local en dos modos:
//   · ventana normal
//   · flotante: ventana transparente, sin marco y siempre encima de las demás, con solo el avatar
// La página es UNA sola (un WebContentsView) y al cambiar de modo pasa de una ventana a la otra sin recargarse:
// la voz que está sonando, el micrófono, la cámara y la conversación siguen tal cual (antes se abría una página
// nueva y la respuesta en curso se cortaba, 16 nov 2026). Nunca hay dos páginas escuchando el micrófono.
//
//   desktop\electron\electron.exe desktop            (lo hace iniciar.ps1)
//   En el Mac lo carga desktop/mac.js (Companion.app) después de instalar y arrancar el servidor.
//
// Variables de entorno: COMPANION_URL (por defecto http://127.0.0.1:8200), COMPANION_STOP_ON_EXIT=1 apaga
// el servidor al cerrar (y el servidor vigila esta app: si muere sin cerrar bien, se apaga solo),
// COMPANION_SERVER_PID = el proceso del servidor que acaba de arrancar iniciar.ps1 (si se cierra, la pantalla de
// carga lo dice en vez de esperar), COMPANION_TEST=1 es para las pruebas automáticas (ventanas fuera de pantalla, sin
// sonido y con micrófono y cámara simulados).
const { app, BaseWindow, BrowserWindow, WebContentsView, ipcMain, session, desktopCapturer, screen, shell, Tray, Menu, globalShortcut, nativeImage } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const petModule = require('./pet');
const fs = require('fs');

const URL_BASE = (process.env.COMPANION_URL || 'http://127.0.0.1:8200').replace(/\/$/, '');
const ORIGIN = new URL(URL_BASE).origin;
// Icono de las ventanas y de la barra de tareas (scripts/instalacion/crear_icono.py). En Windows, el mismo AppUserModelID que
// lleva el acceso directo (instalar.ps1): así la ventana se agrupa con él y anclarla ancla el companion, no Electron.
const ICON = path.join(__dirname, process.platform === 'win32' ? 'icono.ico' : 'icono.png');
const ICON_PNG = path.join(__dirname, 'icono.png');
const APP_ID = 'Companion.Desktop';
if (process.platform === 'win32') app.setAppUserModelId(APP_ID);
const TEST = process.env.COMPANION_TEST === '1';
const FLOAT_MIN = 220, FLOAT_MAX = 900, FLOAT_RATIO = 1.55;

app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');   // la voz suena sin un clic previo
// Evita que Chromium frene requestAnimationFrame (bajones de fps o pausas) cuando otra ventana tiene el foco.
for (const s of ['disable-renderer-backgrounding', 'disable-backgrounding-occluded-windows', 'disable-background-timer-throttling']) {
  app.commandLine.appendSwitch(s);
}
if (TEST) {
  // Micrófono y cámara simulados, salvo en la prueba de dispositivos reales (scripts/pruebas/prueba_dispositivos.py).
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

let win = null;               // la ventana (BaseWindow) que tiene ahora la página
let view = null;              // la página del companion (WebContentsView): la misma en los dos modos
let mode = 'window';
let mainBounds = null;        // dónde y de qué tamaño estaba la ventana normal
let pet = null;               // la mascota de escritorio (desktop/pet.js): solo en modo flotante
let floatBounds = null;       // se recuerda dónde y de qué tamaño dejaste a Mika
let drag = null;
let picker = null;            // ventana «¿Qué quieres que vea Mika?»
let pickerSources = [];
let pickerDone = null;
let pickerOptions = { audio: false, audioOn: false };
let audioNext = 0;           // la próxima petición de pantalla es solo para el sonido (hasta este instante)
let retryVideoNext = 0;      // si video+loopback falla (p. ej. Discord capturando), reintento solo vídeo sin reabrir el selector
let lastShare = null;         // {id, kind: 'screen' | 'window', name, audio} de lo último que se compartió
let tray = null;
let rebuildTrayMenu = null;
let quitting = false;
const desktopPrefsFile = () => path.join(app.getPath('userData'), 'escritorio.json');
const DEFAULT_SHORTCUTS = {
  mute: 'CommandOrControl+Shift+M',
  float: 'CommandOrControl+Shift+F',
  stop: 'CommandOrControl+Shift+S',
};
function loginItemOpts(openAtLogin) {
  const opts = {};
  if (openAtLogin !== undefined) opts.openAtLogin = !!openAtLogin;
  if (process.platform === 'win32' && !app.isPackaged) {
    opts.path = 'powershell.exe';
    opts.args = ['-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', path.resolve(__dirname, '..', 'iniciar.ps1')];
  }
  return opts;
}
function sanitizeShortcut(val, fallback) {
  const s = typeof val === 'string' ? val.trim().slice(0, 48) : '';
  return /^[A-Za-z0-9+]+$/.test(s) ? s : fallback;
}
function loadDesktopPrefs() {
  const def = { shortcuts: true, trayOnClose: false, openAtLogin: false, customShortcuts: { ...DEFAULT_SHORTCUTS } };
  try {
    const raw = JSON.parse(fs.readFileSync(desktopPrefsFile(), 'utf8'));
    const cs = raw.customShortcuts && typeof raw.customShortcuts === 'object' ? raw.customShortcuts : {};
    return {
      shortcuts: raw.shortcuts !== false,
      trayOnClose: raw.trayOnClose === true,
      openAtLogin: app.getLoginItemSettings ? app.getLoginItemSettings(loginItemOpts()).openAtLogin : !!raw.openAtLogin,
      customShortcuts: {
        mute: sanitizeShortcut(cs.mute, DEFAULT_SHORTCUTS.mute),
        float: sanitizeShortcut(cs.float, DEFAULT_SHORTCUTS.float),
        stop: sanitizeShortcut(cs.stop, DEFAULT_SHORTCUTS.stop),
      },
    };
  } catch {
    try { def.openAtLogin = app.getLoginItemSettings ? app.getLoginItemSettings(loginItemOpts()).openAtLogin : false; } catch { /* noop */ }
    return def;
  }
}
function saveDesktopPrefs(patch) {
  const cur = loadDesktopPrefs();
  if (patch && typeof patch === 'object') {
    if ('shortcuts' in patch) cur.shortcuts = !!patch.shortcuts;
    if ('trayOnClose' in patch) cur.trayOnClose = !!patch.trayOnClose;
    if ('openAtLogin' in patch) cur.openAtLogin = !!patch.openAtLogin;
    if (patch.customShortcuts && typeof patch.customShortcuts === 'object') {
      cur.customShortcuts = {
        mute: sanitizeShortcut(patch.customShortcuts.mute, cur.customShortcuts.mute),
        float: sanitizeShortcut(patch.customShortcuts.float, cur.customShortcuts.float),
        stop: sanitizeShortcut(patch.customShortcuts.stop, cur.customShortcuts.stop),
      };
    }
  }
  try { fs.writeFileSync(desktopPrefsFile(), JSON.stringify(cur)); } catch { /* noop */ }
  if (patch && 'openAtLogin' in patch && app.setLoginItemSettings && !TEST) {
    try { app.setLoginItemSettings(loginItemOpts(cur.openAtLogin)); } catch { /* noop */ }
  }
  let failedShortcuts = [];
  if (patch && ('shortcuts' in patch || 'customShortcuts' in patch)) {
    const res = applyGlobalShortcuts(cur.shortcuts, cur.customShortcuts);
    if (res && Array.isArray(res.failed)) failedShortcuts = res.failed;
  }
  return { ...cur, failedShortcuts };
}
function sendShortcut(action) {
  if (view && !view.webContents.isDestroyed()) {
    view.webContents.send('companion:shortcut', action);
  }
}
function applyGlobalShortcuts(on, custom = null) {
  if (TEST) return { failed: [] };
  try { globalShortcut.unregisterAll(); } catch { /* noop */ }
  if (!on) return { failed: [] };
  const sc = custom || loadDesktopPrefs().customShortcuts || DEFAULT_SHORTCUTS;
  const failed = [];
  const reg = (accel, fn) => {
    if (!accel) return;
    try {
      if (!globalShortcut.register(accel, fn)) failed.push(accel);
    } catch {
      failed.push(accel);
    }
  };
  reg(sc.mute || DEFAULT_SHORTCUTS.mute, () => sendShortcut('mute'));
  reg(sc.float || DEFAULT_SHORTCUTS.float, () => { if (win && !win.isDestroyed()) open(mode === 'float' ? 'window' : 'float'); });
  reg(sc.stop || DEFAULT_SHORTCUTS.stop, () => sendShortcut('stop'));
  if (failed.length) winLog('AVISO', 'Atajos globales no registrados:', failed.join(', '));
  return { failed };
}
function bringToCurrentDisplay() {
  if (!win || win.isDestroyed()) { open('window'); return; }
  const cur = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea;
  const b = win.getBounds();
  const x = Math.round(cur.x + (cur.width - b.width) / 2);
  const y = mode === 'float' ? cur.y + cur.height - b.height - 12 : Math.round(cur.y + (cur.height - b.height) / 2);
  win.setBounds({ x, y, width: b.width, height: b.height });
  win.show();
  win.focus();
}
function createTray() {
  if (TEST || tray) return;
  try {
    const img = nativeImage.createFromPath(ICON_PNG);
    tray = new Tray(img.isEmpty() ? ICON : img.resize({ width: 16, height: 16 }));
    tray.setToolTip('Companion');
    const toggleShow = () => {
      if (!win || win.isDestroyed()) { open('window'); return; }
      if (win.isVisible()) win.hide(); else { ensureVisibleBounds(win); win.show(); win.focus(); }
    };
    tray.on('click', toggleShow);
    rebuildTrayMenu = () => Menu.buildFromTemplate([
      { label: 'Mostrar / ocultar', click: toggleShow },
      { label: 'Traer a esta pantalla', click: bringToCurrentDisplay },
      { label: mode === 'float' ? 'Volver a ventana normal' : 'Modo flotante', click: () => open(mode === 'float' ? 'window' : 'float') },
      { type: 'separator' },
      { label: 'Silenciar / activar micrófono', click: () => sendShortcut('mute') },
      { label: 'Callar / interrumpir', click: () => sendShortcut('stop') },
      { type: 'separator' },
      { label: 'Salir de Companion', click: () => { quitting = true; app.quit(); } },
    ]);
    tray.setContextMenu(rebuildTrayMenu());
    tray.on('right-click', () => { if (tray && rebuildTrayMenu) tray.setContextMenu(rebuildTrayMenu()); });
  } catch (err) {
    console.warn('No pude crear el icono en la bandeja:', err.message);
  }
}
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
  // En pruebas, fuera de la pantalla. macOS devuelve a la pantalla las ventanas que se crean fuera de ella:
  // enableLargerThanScreen lo evita en las sin marco (la flotante) y reshow() las vuelve a mover tras mostrarlas.
  return TEST ? { ...bounds, x: -4000, y: -4000, enableLargerThanScreen: true } : bounds;
}

function reshow(w) {
  if (!TEST || process.platform !== 'darwin') { w.show(); return; }
  w.showInactive();                                 // en pruebas en el Mac, sin quitarle el foco al usuario
  w.setPosition(-4000, -4000);
  if (w.getBounds().x + w.getBounds().width > -1000) {   // la ventana con marco: macOS deja un borde en la pantalla
    w.setOpacity(0);                                 // invisible y sin recibir clics (las capturas son de la página)
    w.setIgnoreMouseEvents(true);
  }
}

// ---------------------------------------------------------------- arranque: la ventana se abre ya
// iniciar.ps1 arranca el servidor y abre esta app sin esperar: mientras el servidor no responde se ve
// cargando.html (con el motivo si no llega a arrancar); luego, la interfaz, que enseña lo que falta por cargar.
let serverReady = false;
const ROOT_DIR = process.env.COMPANION_HOME || path.join(__dirname, '..');

// Registro de la ventana (17 nov 2026): errores de la página, cuelgues y caídas de la tarjeta gráfica, que antes no
// quedaban en ningún sitio (p. ej. un cambio de modelo que dejaba la ventana parada). Solo errores de código, nunca
// lo que se dice; guarda la sesión anterior en ventana.1.log.
const WIN_LOG = path.join(ROOT_DIR, 'data', ...(TEST ? ['prueba'] : []), 'ventana.log');
let winLogLines = 0;
try {
  fs.mkdirSync(path.dirname(WIN_LOG), { recursive: true });
  if (fs.existsSync(WIN_LOG)) fs.renameSync(WIN_LOG, WIN_LOG.replace(/\.log$/, '.1.log'));
} catch { /* sin registro, la app sigue */ }
function winLog(...parts) {
  if (winLogLines++ > 2000) return;                  // un error en bucle no llena el disco
  const line = `${new Date().toISOString()} ${parts.join(' ')}`.slice(0, 2000);
  try { fs.appendFileSync(WIN_LOG, line + '\n'); } catch { /* nada */ }
}
app.on('child-process-gone', (_e, d) => winLog('PROCESO', d.type, d.reason, 'código', d.exitCode));
app.on('render-process-gone', (_e, _wc, d) => winLog('PÁGINA CAÍDA', d.reason, 'código', d.exitCode));

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

async function boot(w, target) {              // w: el webContents de la página
  const t0 = Date.now();
  const say = (title, text, failure = '') => {
    if (!w.isDestroyed()) w.executeJavaScript(`setEstado(${JSON.stringify(title)}, ${JSON.stringify(text)}, ${JSON.stringify(failure)})`).catch(() => {});
  };
  const onBootTitle = (_e, title) => {
    if (title === 'companion:registro') shell.openPath(path.join(ROOT_DIR, 'data', 'companion.log'));
    if (title === 'companion:cerrar') app.quit();
  };
  w.on('page-title-updated', onBootTitle);
  while (!w.isDestroyed()) {
    if (await serverUp()) {
      serverReady = true;
      registerOwner();
      w.removeListener('page-title-updated', onBootTitle);
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

function makeView() {
  const v = new WebContentsView({ webPreferences: webPreferences() });
  v.setBackgroundColor('#00000000');              // transparente: en flotante solo se ve el avatar
  const wc = v.webContents;
  if (TEST) wc.setAudioMuted(true);
  // Enlaces externos: en el navegador del sistema, nunca dentro de la ventana del companion.
  wc.setWindowOpenHandler(({ url }) => {
    try {
      if (/^https?:/.test(url) && new URL(url).origin !== ORIGIN) shell.openExternal(url);
    } catch { /* URL inválida */ }
    return { action: 'deny' };
  });
  wc.on('will-navigate', (e, url) => {
    try { if (new URL(url).origin !== ORIGIN) e.preventDefault(); }
    catch { e.preventDefault(); }
  });
  wc.on('console-message', (e, lvl, msg, line, src) => {
    const level = e.level ?? (['debug', 'info', 'warning', 'error'][lvl] || lvl);
    if (level !== 'error' && level !== 'warning') return;
    if (String(e.message ?? msg).startsWith('Electron Security Warning')) return;   // aviso fijo de Electron sin empaquetar
    winLog(level === 'error' ? 'ERROR' : 'AVISO', e.message ?? msg, '@', String(e.sourceId ?? src ?? '').replace(/^.*\/\/[^/]+/, ''), e.lineNumber ?? line ?? '');
  });
  wc.on('unresponsive', () => winLog('LA PÁGINA NO RESPONDE'));
  wc.on('responsive', () => winLog('la página vuelve a responder'));
  wc.on('page-title-updated', (e, title) => {
    if (title.startsWith('companion:')) return;   // señales de cargando.html (ver boot)
    if (win && !win.isDestroyed()) win.setTitle(title);
  });
  return v;
}

function ensureVisibleBounds(w) {
  if (TEST || !w || w.isDestroyed()) return;
  const b = w.getBounds();
  const displays = screen.getAllDisplays();
  const visible = displays.some((d) => {
    const r = d.workArea;
    return b.x + b.width > r.x + 40 && b.x < r.x + r.width - 40 && b.y + b.height > r.y + 40 && b.y < r.y + r.height - 40;
  });
  if (!visible) {
    const area = screen.getPrimaryDisplay().workArea;
    w.setBounds({
      x: Math.round(area.x + (area.width - b.width) / 2),
      y: Math.round(area.y + (area.height - b.height) / 2),
      width: b.width,
      height: b.height,
    });
  }
}

function fit(w) {
  if (!view || !w || w.isDestroyed()) return;
  const b = w.getContentBounds();
  view.setBounds({ x: 0, y: 0, width: b.width, height: b.height });
}

function createMain() {
  const w = new BaseWindow({
    ...place(mainBounds || { width: 520, height: 880 }), minWidth: 380, minHeight: 560, backgroundColor: '#0c0b14',
    autoHideMenuBar: true, icon: ICON, title: 'Companion', show: false,
  });
  w.setMenuBarVisibility(false);
  w.on('resize', () => fit(w));
  const remember = () => { if (!TEST && !w.isMaximized() && !w.isMinimized()) mainBounds = w.getBounds(); };
  w.on('moved', remember);
  w.on('resized', remember);
  return w;
}

function createFloat() {
  const area = screen.getPrimaryDisplay().workArea;
  const width = 340, height = Math.round(width * FLOAT_RATIO);
  const bounds = floatBounds || { width, height, x: area.x + area.width - width - 28, y: area.y + area.height - height - 12 };
  const w = new BaseWindow({
    ...place(bounds), transparent: true, frame: false, resizable: false, maximizable: false, fullscreenable: false,
    hasShadow: false, backgroundColor: '#00000000', icon: ICON, title: 'Companion', show: false,
  });
  w.setAlwaysOnTop(true, 'screen-saver');           // por encima también de las ventanas a pantalla completa sin borde
  w.setVisibleOnAllWorkspaces(true);
  ensureVisibleBounds(w);
  w.on('moved', () => { if (!TEST) floatBounds = w.getBounds(); });
  w.on('resize', () => fit(w));
  return w;
}

// Cambia de modo llevando la misma página a la ventana nueva; la anterior se cierra después, ya vacía.
function open(next) {
  const old = win;
  if (old && !old.isDestroyed() && mode === 'float' && !TEST) floatBounds = old.getBounds();
  mode = next;
  const w = next === 'float' ? createFloat() : createMain();
  win = w;
  const first = !view;
  if (first) view = makeView();
  else if (old && !old.isDestroyed()) old.contentView.removeChildView(view);
  w.contentView.addChildView(view);
  fit(w);
  w.on('close', (e) => {
    if (!TEST && !quitting && win === w && tray && loadDesktopPrefs().trayOnClose) {
      e.preventDefault();
      w.hide();
    }
  });
  w.on('closed', () => {
    if (win !== w) return;                          // la cerró un cambio de modo: la página sigue en la otra
    win = null;
    if (picker && !picker.isDestroyed()) picker.destroy();      // sin la página no queda nada que elegir
    app.quit();
  });
  if (picker && !picker.isDestroyed()) picker.destroy();        // estaba pegada a la ventana que se va
  reshow(w);
  if (old && !old.isDestroyed()) old.destroy();
  const wc = view.webContents;
  if (first) {
    const target = `${URL_BASE}/`;
    if (serverReady) wc.loadURL(target);
    else {
      wc.loadFile(path.join(__dirname, 'cargando.html'));
      wc.once('did-finish-load', () => boot(wc, target));
    }
  } else {
    wc.send('companion:mode', mode);                // la página cambia su aspecto (flotante o normal)
  }
  if (!TEST) wc.focus();
  if (!pet) pet = petModule.create({ screen, getWin: () => win, getView: () => view, getMode: () => mode, urlBase: URL_BASE, test: TEST });
  if (mode === 'float') pet.start(); else pet.stop();
  if (tray && rebuildTrayMenu) tray.setContextMenu(rebuildTrayMenu());
}

const fromOurPage = (e) => {
  try { return new URL(e.senderFrame.url).origin === ORIGIN; } catch { return false; }
};

// La ventana de la página que manda el mensaje (solo la del companion).
const ownWindow = (e) => (view && e.sender === view.webContents && fromOurPage(e) && win && !win.isDestroyed() ? win : null);

ipcMain.handle('companion:float', (e, on) => {
  if (!ownWindow(e)) return false;
  const next = on ? 'float' : 'window';
  if (next !== mode) open(next);
  return mode;
});

ipcMain.on('companion:quit', (e) => { if (ownWindow(e)) app.quit(); });

ipcMain.on('companion:ignore-mouse', (e, ignore) => {
  const w = ownWindow(e);
  if (w && mode === 'float') w.setIgnoreMouseEvents(!!ignore, { forward: true });
});

ipcMain.on('companion:drag', (e, phase) => {
  const w = ownWindow(e);
  if (!w || mode !== 'float') return;
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
  if (pet) pet.onDrag(phase === 'start' || phase === 'move' ? phase : 'end');
});

// Mascota de escritorio: lo que manda la página (ajustes, puntos del personaje, estado, acciones en ventanas).
ipcMain.on('pet:prefs', (e, p) => { if (ownWindow(e) && pet) pet.setPrefs(p); });
ipcMain.on('pet:anchors', (e, a) => { if (ownWindow(e) && pet) pet.setAnchors(a); });
ipcMain.on('pet:state', (e, s) => { if (ownWindow(e) && pet) pet.setState(s); });
ipcMain.on('pet:work', (e, m) => { if (ownWindow(e) && pet) pet.work(m); });
ipcMain.on('pet:frame', (e) => { if (pet && ownWindow(e)) pet.pageFrame(); });
ipcMain.on('pet:rest', (e, on) => { if (pet && ownWindow(e)) pet.rest(!!on); });
ipcMain.on('pet:test-scene', (e, s) => { if (TEST && ownWindow(e) && pet) pet.setTestScene(s); });
ipcMain.on('pet:test', (e, c) => { if (TEST && ownWindow(e) && pet) pet.testCmd(c || {}); });
ipcMain.handle('pet:info', (e) => (ownWindow(e) && pet ? pet.info() : null));

ipcMain.on('companion:resize', (e, step) => {
  const w = ownWindow(e);
  if (!w || mode !== 'float') return;
  const b = w.getBounds();
  const width = Math.max(FLOAT_MIN, Math.min(FLOAT_MAX, Math.round(b.width * (step > 0 ? 1.08 : 1 / 1.08))));
  const height = Math.round(width * FLOAT_RATIO);
  // Crece desde los pies: el centro inferior de la ventana no se mueve.
  w.setBounds({ x: Math.round(b.x + (b.width - width) / 2), y: b.y + b.height - height, width, height });
  if (pet) pet.resized({ width, height });
  if (!TEST) floatBounds = w.getBounds();
});

// ---------------------------------------------------------------- elegir qué se comparte
// Lista pantallas y ventanas (sin las del propio companion) y deja elegir una en una ventana aparte, que
// sirve igual en modo normal y en modo flotante. Devuelve {id, name, kind, audio} o null si se cancela.
// `audio`: ofrecer el interruptor «Escuchar también el sonido».
async function listCaptureSources() {
  const found = await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 400, height: 250 } });
  const mine = win && !win.isDestroyed() ? win.getMediaSourceId() : '';
  const picId = picker && !picker.isDestroyed() ? picker.getMediaSourceId() : '';
  const displays = screen.getAllDisplays();
  const cursor = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const list = [];
  for (const s of found) {
    if (s.id === mine || (picId && s.id === picId)) continue;
    if (s.id.startsWith('screen:')) {
      const n = displays.findIndex((d) => String(d.id) === s.display_id);
      const d = displays[n];
      let name = displays.length > 1 && n >= 0 ? `Pantalla ${n + 1}` : 'Pantalla completa';
      if (d) name += ` (${Math.round(d.size.width * d.scaleFactor)}×${Math.round(d.size.height * d.scaleFactor)})`;
      if (displays.length > 1 && d && d.id === cursor.id) name += ' · aquí está el cursor';
      list.push({ id: s.id, kind: 'screen', name, thumbnail: s.thumbnail.isEmpty() ? '' : s.thumbnail.toDataURL() });
    } else if (s.name.trim()) {
      list.push({ id: s.id, kind: s.id.startsWith('window:') ? 'window' : 'screen', name: s.name.trim().slice(0, 120), thumbnail: s.thumbnail.isEmpty() ? '' : s.thumbnail.toDataURL() });
    }
  }
  return { list, cursor };
}

async function pickSource(audio) {
  if (picker && !picker.isDestroyed()) picker.destroy();        // una petición anterior sin responder
  const { list, cursor } = await listCaptureSources();

  const area = cursor.workArea;
  const width = Math.min(820, area.width - 40), height = Math.min(640, area.height - 40);
  const w = new BrowserWindow({
    ...place({ width, height, x: Math.round(area.x + (area.width - width) / 2), y: Math.round(area.y + (area.height - height) / 2) }),
    minWidth: 420, minHeight: 360, backgroundColor: '#0c0b14', autoHideMenuBar: true, icon: ICON, title: 'Compartir pantalla',
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
      const s = pickerSources.find((x) => x.id === id);
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
ipcMain.handle('picker:refresh', async (e) => {
  if (!fromPicker(e)) return [];
  const { list } = await listCaptureSources();
  pickerSources = list;
  return pickerSources;
});
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
ipcMain.handle('companion:share-retry-video', (e) => {
  if (!fromOurPage(e) || !lastShare || !lastShare.id) return false;
  retryVideoNext = Date.now() + 10000;
  return true;
});
ipcMain.handle('companion:desktop-prefs-get', (e) => (fromOurPage(e) ? loadDesktopPrefs() : null));
ipcMain.handle('companion:desktop-prefs-set', (e, patch) => (fromOurPage(e) ? saveDesktopPrefs(patch) : null));

// Qué se eligió la última vez (pantalla o ventana y su nombre), para que la página se lo cuente a Mika.
ipcMain.handle('companion:share-info', (e) => (fromOurPage(e) ? lastShare : null));

ipcMain.handle('companion:info', (e) => {
  const w = ownWindow(e);
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
    if (fromUs && Date.now() < retryVideoNext && lastShare && lastShare.id) {
      retryVideoNext = 0;
      try {
        return callback({ video: { id: lastShare.id, name: lastShare.name } });
      } catch (err) {
        console.error('No pude reintentar solo vídeo:', err);
        return callback(null);
      }
    }
    let chosen = null;
    try {
      if (fromUs) chosen = await pickSource(true);
    } catch (err) {
      console.error('No pude listar pantallas y ventanas:', err);
    }
    try {
      if (!chosen) return callback(null);          // cancelado: getDisplayMedia() se rechaza con AbortError
      lastShare = { id: chosen.id, kind: chosen.kind, name: chosen.name, audio: chosen.audio };
      // Pedir video + loopback en UNA sola captura evita conflictos de WGC/WASAPI con Discord y evita perder la
      // activación del clic en una segunda llamada getDisplayMedia. Si falla, vision.js reintenta solo vídeo.
      if (chosen.audio && request.audioRequested) {
        return callback({ video: { id: chosen.id, name: chosen.name }, audio: 'loopback' });
      }
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

  open('window');
  createTray();
  const dp = loadDesktopPrefs();
  applyGlobalShortcuts(dp.shortcuts, dp.customShortcuts);
  const recoverBounds = () => { if (win && !win.isDestroyed()) ensureVisibleBounds(win); };
  screen.on('display-removed', recoverBounds);
  screen.on('display-metrics-changed', recoverBounds);
});

app.on('before-quit', () => { quitting = true; });
app.on('window-all-closed', () => app.quit());

app.on('will-quit', () => {
  try { globalShortcut.unregisterAll(); } catch { /* noop */ }
  if (tray) { try { tray.destroy(); } catch { /* noop */ } tray = null; }
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
