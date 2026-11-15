// Arranque de la app para Mac (Companion.app, Apple Silicon). La app trae dentro el programa
// (Contents/Resources/programa: lo que está en git, más manifest.json con la huella de cada archivo) y lo
// instala en ~/Library/Application Support/Companion, donde viven también Python, los modelos y tus datos:
//   1. la primera vez y con cada versión nueva copia solo lo que cambió (y borra lo que la versión anterior
//      instaló y esta ya no trae; nunca toca lo que no está en un manifiesto, como .env o data/)
//   2. ejecuta instalar.sh en una ventana de progreso (marcas ::paso::, ::progreso::, ::omitido::, ::error::, ::fin::)
//   3. arranca el servidor con iniciar.sh --sin-ventana y abre la ventana de siempre (main.js)
// Al cerrar la app se apaga también el servidor (detener.sh), para devolver la memoria.
//
// Variables: COMPANION_HOME (otra carpeta de instalación, para las pruebas), COMPANION_TEST=1 (ventanas fuera
// de pantalla, como en main.js).
const { app, BrowserWindow, ipcMain, shell, systemPreferences } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const TEST = process.env.COMPANION_TEST === '1';
const BUNDLE = process.env.COMPANION_BUNDLE || path.join(process.resourcesPath, 'programa');
const HOME = process.env.COMPANION_HOME || path.join(app.getPath('appData'), 'Companion');
const LOG = path.join(HOME, 'data', 'instalacion.log');
// Lo que Electron hereda al abrirse desde el Finder es un PATH mínimo: Ollama y Homebrew viven fuera de él.
const PATH_EXTRA = ['/usr/local/bin', '/opt/homebrew/bin', '/Applications/Ollama.app/Contents/Resources'];
const env = () => ({ ...process.env, PATH: [process.env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin', ...PATH_EXTRA].join(':') });

app.setName('Companion');
// Lo que main.js pone en la línea de órdenes de Chromium solo vale antes de que la app esté lista, y main.js se
// carga después (tras instalar): se pone aquí. main.js lo repite sin efecto.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');   // la voz suena sin un clic previo
if (TEST) {
  if (process.env.COMPANION_TEST_REAL_MEDIA !== '1') app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('remote-debugging-port', process.env.COMPANION_TEST_PORT || '9334');
  app.setPath('userData', path.join(app.getPath('temp'), 'companion-pc-prueba'));
}
if (!TEST && !app.requestSingleInstanceLock()) {
  app.quit();                 // ya hay una abierta: no se abre otra escuchando el mismo micrófono
} else {
  app.on('second-instance', () => {
    const w = BrowserWindow.getAllWindows()[0];
    if (w) { w.show(); w.focus(); }
  });
  boot();
}

let ui = null;                // la ventana de instalación
let child = null;             // instalar.sh o iniciar.sh en marcha
let quitting = false;

function send(kind, ...args) {
  if (ui && !ui.isDestroyed()) ui.webContents.send('instalar:evento', kind, ...args);
}

function log(line) {
  try { fs.mkdirSync(path.dirname(LOG), { recursive: true }); fs.appendFileSync(LOG, line + '\n'); } catch { /* sin permiso */ }
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex').toUpperCase();
}

// ---------------------------------------------------------------- 1. el programa (solo lo que cambió)
function copyProgram() {
  const next = readJson(path.join(BUNDLE, 'manifest.json'));
  if (!next || !Array.isArray(next.files)) throw new Error('La app no trae manifest.json: no sé qué copiar.');
  if (fs.existsSync(path.join(HOME, '.git'))) throw new Error(`${HOME} es una copia de desarrollo (tiene .git): no la toco.`);
  fs.mkdirSync(HOME, { recursive: true });
  const prev = readJson(path.join(HOME, 'manifest.json'));
  const before = new Map((prev && prev.files || []).map((f) => [f.p, f.h]));
  const now = new Set();
  let copied = 0, n = 0;
  for (const f of next.files) {
    n += 1;
    now.add(f.p);
    const dst = path.join(HOME, f.p);
    if (!dst.startsWith(HOME + path.sep)) continue;                          // nunca fuera de la carpeta
    let same = false;
    try {
      const st = fs.statSync(dst);
      same = st.size === f.s && (before.get(f.p) === f.h || sha256(dst) === f.h);
    } catch { /* no existe */ }
    if (!same) {
      fs.mkdirSync(path.dirname(dst), { recursive: true });
      fs.copyFileSync(path.join(BUNDLE, f.p), dst);
      if (f.p.endsWith('.sh')) fs.chmodSync(dst, 0o755);
      copied += 1;
    }
    if (n % 200 === 0) send('progreso', Math.round((100 * n) / next.files.length), `Copiando el programa: ${n} de ${next.files.length}`);
  }
  let removed = 0;
  for (const p of before.keys()) {                   // lo que instaló la versión anterior y esta ya no trae
    if (now.has(p)) continue;
    const dst = path.join(HOME, p);
    if (!dst.startsWith(HOME + path.sep)) continue;
    try { fs.unlinkSync(dst); removed += 1; } catch { /* ya no estaba */ }
  }
  fs.copyFileSync(path.join(BUNDLE, 'manifest.json'), path.join(HOME, 'manifest.json'));
  log(`Programa ${next.version}: ${copied} archivos copiados, ${removed} retirados.`);
  return next.version;
}

// ---------------------------------------------------------------- 2 y 3. instalar.sh e iniciar.sh
function run(script, args, onLine) {
  return new Promise((resolve) => {
    child = spawn('/bin/bash', [path.join(HOME, script), ...args], { cwd: HOME, env: { ...env(), COMPANION_UI: '1' } });
    let rest = '';
    const feed = (chunk) => {
      rest += chunk.toString('utf8');
      const lines = rest.split(/\r?\n/);
      rest = lines.pop();
      for (const l of lines) onLine(l);
    };
    child.stdout.on('data', feed);
    child.stderr.on('data', feed);
    child.on('close', (code) => { if (rest) onLine(rest); child = null; resolve(code); });
    child.on('error', (err) => { onLine(`::error::${err.message}`); child = null; resolve(1); });
  });
}

async function install(version) {
  let failed = '';
  let finished = false;
  log(`---- instalar.sh (${new Date().toISOString()})`);
  const code = await run('instalar.sh', ['--sin-modelo-local'], (line) => {
    const m = /^::(paso|omitido|progreso|error|fin)::(.*)$/.exec(line);
    if (!m) { log(line); if (line.trim()) send('linea', line.slice(0, 200)); return; }
    const [kind, rest] = [m[1], m[2]];
    if (kind === 'progreso') { const [pct, ...t] = rest.split('::'); send('progreso', Number(pct) || 0, t.join('::')); }
    else if (kind === 'error') { failed = rest; log(`ERROR: ${rest}`); }
    else if (kind === 'fin') finished = true;
    else send(kind, rest);
  });
  if (code !== 0 || !finished) throw new Error(failed || `La instalación se detuvo (código ${code}).`);
  fs.writeFileSync(path.join(HOME, '.instalado'), version);
}

async function startServer() {
  let url = '';
  const code = await run('iniciar.sh', ['--sin-ventana'], (line) => {
    log(line);
    const m = /Companion en (http:\/\/\S+)/.exec(line);
    if (m) url = m[1];
  });
  if (code !== 0 || !url) throw new Error('El companion no arrancó. El registro está en Companion › data › companion.log.');
  return url;
}

function installed(version) {
  try {
    return fs.readFileSync(path.join(HOME, '.instalado'), 'utf8').trim() === version &&
      fs.existsSync(path.join(HOME, '.venv', 'bin', 'python'));
  } catch { return false; }
}

function showUi() {
  if (ui && !ui.isDestroyed()) return ui;
  ui = new BrowserWindow({
    width: 560, height: 520, ...(TEST ? { x: -4000, y: -4000 } : {}), resizable: false, maximizable: false,
    fullscreenable: false, backgroundColor: '#0c0b14', title: 'Companion',
    webPreferences: { preload: path.join(__dirname, 'instalando-preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  ui.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  ui.webContents.on('will-navigate', (e) => e.preventDefault());
  ui.loadFile(path.join(__dirname, 'instalando.html'));
  ui.on('closed', () => { ui = null; if (!quitting && !global.companionMainLoaded) app.quit(); });
  return new Promise((resolve) => ui.webContents.once('did-finish-load', () => resolve(ui)));
}

const fromUi = (e) => ui && !ui.isDestroyed() && e.sender === ui.webContents;
ipcMain.on('instalar:reintentar', (e) => { if (fromUi(e)) start(); });
ipcMain.on('instalar:registro', (e) => { if (fromUi(e)) shell.showItemInFolder(LOG); });

async function start() {
  try {
    const manifest = readJson(path.join(BUNDLE, 'manifest.json'));
    const version = manifest && manifest.version;
    if (!version) throw new Error('La app no trae manifest.json: no sé qué instalar.');
    if (!installed(version)) {
      await showUi();
      send('inicio', version, fs.existsSync(path.join(HOME, '.instalado')));
      send('paso', 'programa');
      copyProgram();
      await install(version);
    } else if (!TEST) {
      await showUi();
    }
    send('paso', 'arranque');
    const url = await startServer();
    if (!TEST && process.platform === 'darwin') {
      // El permiso del micrófono se pide a macOS una vez (Info.plist explica para qué).
      await systemPreferences.askForMediaAccess('microphone').catch(() => false);
    }
    process.env.COMPANION_URL = url;
    process.env.COMPANION_STOP_ON_EXIT = '1';
    process.env.COMPANION_HOME = HOME;
    process.env.COMPANION_BOOTED = '1';
    global.companionMainLoaded = true;
    require('./main.js');                              // abre la ventana del companion
    setTimeout(() => { if (ui && !ui.isDestroyed()) ui.destroy(); }, 800);
  } catch (err) {
    log(`ERROR: ${err.message}`);
    if (!ui) await showUi();
    send('error', err.message);
  }
}

function boot() {
  app.whenReady().then(start);
  app.on('before-quit', () => {
    quitting = true;
    if (child) { try { child.kill('SIGTERM'); } catch { /* ya terminó */ } }
  });
  app.on('window-all-closed', () => { if (!global.companionMainLoaded) app.quit(); });
}
