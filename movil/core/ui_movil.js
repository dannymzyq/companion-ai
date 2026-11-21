// Capa de interfaz del teléfono sobre web/ (que es la de la PC): elegir el modo «todo dentro del teléfono» con sus
// descargas, textos adaptados al teléfono, márgenes de la barra de estado y lo que aquí no existe, oculto.
// La carga boot.js; onboarding.js le pasa el paso «local» (window.companionPhone).

import { call, on } from './platform.js';

const $ = (id) => document.getElementById(id);
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? undefined
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo guardar.');
  return data;
};
const gb = (b) => `${(b / 1e9).toFixed(b >= 1e9 ? 1 : 2).replace('.', ',')} GB`;
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

// ---------------------------------------------------------------- textos de la PC → del teléfono
const TEXTOS = [
  ['Permitir micrófono y cámara', 'Permitir micrófono'], ['Micrófono y cámara', 'Micrófono'],
  ['Sin micrófono · sin cámara', 'Sin micrófono'], [' · sin cámara', ''],
  ['Local · ', 'Teléfono · '],
  ['No quiero usar una clave: usar un modelo en esta PC', 'Prefiero todo dentro del teléfono, sin internet'],
  ['La clave se guarda solo en esta PC.', 'La clave se guarda solo en el llavero de este teléfono.'],
  [': responde mejor y no ocupa tu tarjeta gráfica.', ': responde mejor y gasta menos batería.'],
  ['Recomendada para tu PC', 'Recomendada'],
  ['Ollama en esta PC', 'Todo en el teléfono'],
  ['Whisper en esta PC', 'Whisper en el teléfono'],
  ['Tu voz se transcribe en esta PC.', 'Tu voz se transcribe en el teléfono.'],
  ['Responde mejor y no ocupa tu tarjeta gráfica.', 'Responde mejor y gasta menos batería.'],
  ['en esta PC', 'en este teléfono'], ['de esta PC', 'de este teléfono'], ['esta PC', 'este teléfono'],
  ['en tu PC', 'en tu teléfono'], ['de tu PC', 'de tu teléfono'], ['tu PC', 'tu teléfono'],
  ['la PC', 'el teléfono'], ['su PC', 'su teléfono'],
  ['; la GPU del Mac queda libre', '; no descarga nada en el teléfono'], ['; tu tarjeta gráfica queda libre', '; no descarga nada en el teléfono'],
  ['nada se carga en la GPU del Mac', 'nada se descarga'], ['la GPU del Mac', 'el teléfono'],
  ['Tu tarjeta queda libre', 'Sin descargas'], ['nada se carga en tu tarjeta', 'nada se descarga'],
  ['En vivo no se carga nada en tu tarjeta: ni el oído (Whisper) ni la voz completa.', 'En vivo no se descarga ni se carga ningún modelo en el teléfono.'],
];
const MOTOR_NUBE = 'Habla con las voces neuronales de Microsoft: necesita internet.';
const MOTOR_TEL = 'Habla con la voz ligera, dentro del teléfono: sin internet.';

const CLAVES = new RegExp(TEXTOS.map(([a]) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'));

function adaptar(texto) {
  let t = texto;
  for (const [a, b] of TEXTOS) if (t.includes(a)) t = t.split(a).join(b);
  return t;
}

function adaptarNodo(root) {
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (CLAVES.test(n.nodeValue)) { const t = adaptar(n.nodeValue); if (t !== n.nodeValue) n.nodeValue = t; }
  }
  if (root.querySelectorAll) {
    for (const e of root.querySelectorAll('[placeholder],[title]')) {
      for (const a of ['placeholder', 'title']) {
        const v = e.getAttribute(a);
        if (v && CLAVES.test(v)) e.setAttribute(a, adaptar(v));
      }
    }
  }
}

// Notas largas que en la PC hablan de tarjeta y memoria de vídeo: en el teléfono se escriben de nuevo.
const poner = (e, t) => { if (e && e.textContent !== t) e.textContent = t; };

function notas(cfg) {
  const phone = cfg && cfg.mode === 'telefono';
  document.body.classList.toggle('modo-telefono', !!phone);
  const note = $('ob-engine-note');
  if (note && /NVIDIA|tarjeta|vídeo/.test(note.textContent)) poner(note, phone ? MOTOR_TEL : MOTOR_NUBE);
  const brain = $('brain-note');
  if (brain && cfg) {
    const name = cfg.name || 'Tu companion';
    poner(brain, phone
      ? `Todo pasa dentro de este teléfono: tu voz, lo que piensa ${name} y su voz. Nada sale a internet.`
        + (cfg.adult && cfg.adult.active ? ' Sin filtro para temas +18 si tú los propones.' : '')
      : `El texto de la conversación viaja a ${cfg.cloud.name}, tu voz se transcribe en la nube y la voz de ${name} se genera en la nube.`);
  }
  const local = $('tip-local');
  poner(local, 'Los modelos que usa el modo teléfono: el cerebro (Gemma), el oído (Whisper) y la voz ligera. '
    + 'Se descargan una vez y después funcionan sin internet.');
  const head = local && local.closest('.set') && local.closest('.set').querySelector('.set-head b');
  poner(head, 'Modelos del teléfono');
}

// ---------------------------------------------------------------- el paso «todo dentro del teléfono»
let estado = null;
let pintar = null;

async function refrescar() {
  estado = await api('/api/phone');
  if (pintar) pintar();
  return estado;
}

function opcion(nombre, detalle, on, onClick) {
  const row = el('div', 'model-row' + (on ? ' on' : ''));
  const b = el('button', 'pick');
  b.append(el('b', null, nombre), el('small', null, detalle));
  b.onclick = onClick;
  row.append(b);
  return row;
}

async function fill(section, { fail, poll }) {
  section.replaceChildren(
    el('h2', null, 'Todo dentro del teléfono'),
    el('p', null, 'Sin internet: te oye, piensa y habla aquí mismo, y nada sale del teléfono. La primera vez hay que '
      + 'descargar los modelos (mejor con wifi).'),
  );
  const box = el('div');
  section.append(box);
  pintar = () => {
    if (!estado) return;
    const by = Object.fromEntries(estado.models.map((m) => [m.kind, m]));
    const parts = [];
    for (const kind of ['cerebro', 'oido']) {
      parts.push(el('label', 'ob-label', kind === 'cerebro' ? 'Cerebro' : 'Oído'));
      const list = el('div', 'model-list');
      for (const o of estado.options[kind]) {
        const chosen = by[kind] && by[kind].id === o.id;
        const size = o.total ? gb(o.total) : '';
        const ready = o.listo ? ' · descargado' : '';
        if (o.cabe === false) {
          const row = opcion(o.nombre, `${size} · No cabe en la memoria que iOS le deja a la app en este iPhone`, false, () => {});
          row.querySelector('button').disabled = true;
          row.querySelector('button').style.opacity = '0.45';
          if (o.listo) {                       // bajado pero inservible aquí: que se pueda recuperar el espacio
            const del = el('button', 'mini', `Borrar (${size})`);
            del.onclick = async () => {
              try { await api('/api/phone/delete', { id: o.id }); await refrescar(); } catch (e) { fail(e.message); }
            };
            row.append(del);
          }
          list.append(row);
          continue;
        }
        list.append(opcion(o.nombre, [size + ready, o.nota].filter(Boolean).join(' · '), chosen, async () => {
          try { await api('/api/setup', { phone_models: { [kind]: o.id } }); await refrescar(); } catch (e) { fail(e.message); }
        }));
      }
      parts.push(list);
    }
    const falta = estado.missing_bytes;
    const bajando = estado.models.filter((m) => m.progress && !m.progress.fin && !m.progress.error);
    const fallo = estado.models.find((m) => m.progress && m.progress.error && m.progress.error !== 'cancelada');
    const info = el('p', 'ob-info');
    const cell = el('label', 'ob-check');
    const check = el('input'); check.type = 'checkbox'; check.id = 'phone-cell';
    check.checked = sessionStorage.getItem('companion.cellular') === '1';
    check.onchange = () => sessionStorage.setItem('companion.cellular', check.checked ? '1' : '0');
    cell.append(check, document.createTextNode(' Permitir descargar con datos móviles'));
    const actions = el('div', 'ob-actions');
    if (bajando.length) {
      const done = bajando.reduce((a, m) => a + m.progress.done, 0), total = bajando.reduce((a, m) => a + m.progress.total, 0);
      const pct = total ? Math.floor((done / total) * 100) : 0;
      info.textContent = `Descargando… ${pct} % (${gb(done)} de ${gb(total)}). Puedes salir de esta pantalla: sigue sola mientras la app esté abierta.`;
      const bar = el('div', 'phone-bar'); const fillBar = el('i'); fillBar.style.width = `${pct}%`; bar.append(fillBar);
      const stop = el('button', 'link', 'Cancelar');
      stop.onclick = async () => { for (const m of bajando) await api('/api/phone/cancel', { id: m.id }).catch(() => {}); refrescar(); };
      actions.append(stop);
      parts.push(info, bar, actions);
    } else if (falta > 0) {
      const partial = estado.models.some((m) => !m.listo && m.present > 0);
      info.textContent = `Falta descargar ${gb(falta)}.` + (check.checked ? '' : ' Solo con wifi.')
        + (fallo ? ` La última descarga falló (${fallo.progress.error}).` : '');
      const get = el('button', 'primary', `${partial ? 'Reanudar' : 'Descargar'} (${gb(falta)})`);
      get.onclick = async () => {
        fail('');
        try { await api('/api/phone/download', { cellular: check.checked }); await refrescar(); } catch (e) { fail(e.message); }
      };
      actions.append(get);
      parts.push(info, cell, actions);
    } else {
      info.textContent = estado.simulated_brain
        ? 'Todo descargado. En el simulador el cerebro es de prueba; en el iPhone piensa Gemma.'
        : 'Todo descargado: ya funciona sin internet.';
      parts.push(info);
    }
    box.replaceChildren(...parts);
  };
  box.replaceChildren(el('p', 'ob-info', 'Mirando qué hay en el teléfono…'));
  try { await refrescar(); } catch (e) { fail(`No pude ver los modelos: ${e.message}`); }
  poll(setInterval(() => refrescar().catch(() => {}), 1000));
}

async function save() {
  const s = estado || await refrescar();
  if (s.missing_bytes > 0) {
    throw new Error('Descarga los modelos para usar el modo teléfono, o vuelve a la nube con «Atrás».');
  }
  await api('/api/setup', { mode: 'telefono' });
}

// ---------------------------------------------------------------- ventana flotante (picture in picture)
// Como las apps de vídeo: el personaje sigue en una ventanita encima de las demás apps. Se copia el dibujo 3D a un
// lienzo con fondo (de la cintura a la cabeza) y cada cuadro va al nativo (VentanaFlotante.swift), que lo pone en
// la ventana flotante de iOS (WebKit no deja hacer picture in picture de un lienzo). Con la app en segundo plano la página no recibe cuadros (requestAnimationFrame se para): un
// temporizador sigue moviendo al personaje mientras la ventana está abierta.
const pip = { canvas: null, timer: null, on: false };

function pipFrame() {
  const av = window.companion && window.companion.avatar, a = window.companion && window.companion.audio;
  if (!av || !pip.canvas) return;
  if (document.hidden) {                        // en segundo plano main.js no dibuja: se hace aquí
    try { av.setVoice(a ? a.analyse() : { vol: 0 }); av.update(); } catch { /* el siguiente cuadro */ }
  }
  const src = av.renderer.domElement, g = pip.canvas.getContext('2d');
  const W = pip.canvas.width, H = pip.canvas.height;
  const grad = g.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, '#1d1830'); grad.addColorStop(1, '#0c0b14');
  g.fillStyle = grad; g.fillRect(0, 0, W, H);
  // Recorte con la proporción de la ventanita, centrado arriba (donde está la cabeza con el primer plano).
  const sw = src.width, sh = src.height, want = W / H;
  let cw = sw, ch = sw / want;
  if (ch > sh) { ch = sh; cw = sh * want; }
  g.drawImage(src, (sw - cw) / 2, sh * 0.04, cw, Math.min(ch, sh * 0.96), 0, 0, W, H);
}

async function abrirFlotante() {
  const av = window.companion && window.companion.avatar;
  if (!av || !av.renderer) throw new Error('El personaje todavía está cargando.');
  if (!pip.canvas) {
    pip.canvas = Object.assign(document.createElement('canvas'), { width: 360, height: 480 });
    on('pip', (open) => { if (!open) cerrarFlotante(true); });
  }
  await call('pip.open', { width: pip.canvas.width, height: pip.canvas.height });
  pip.on = true;
  let enviando = false;
  const tick = () => {
    if (enviando) return;                         // si el puente va lento, se salta un cuadro
    pipFrame();
    enviando = true;
    call('pip.frame', { jpeg: pip.canvas.toDataURL('image/jpeg', 0.75).split(',')[1] })
      .catch(() => {}).finally(() => { enviando = false; });
  };
  tick();
  clearInterval(pip.timer);
  pip.timer = setInterval(tick, 66);              // ~15 cuadros por segundo
}

function cerrarFlotante(yaCerrada = false) {
  clearInterval(pip.timer); pip.timer = null; pip.on = false;
  if (!yaCerrada) call('pip.close').catch(() => {});
}
window.companionPip = { abrir: abrirFlotante, cerrar: cerrarFlotante, estado: () => pip.on };

window.companionPhone = { fill, save, refresh: refrescar };

// ---------------------------------------------------------------- arranque
export function init() {
  const meta = document.querySelector('meta[name="viewport"]');
  if (meta && !/viewport-fit/.test(meta.content)) meta.content += ', viewport-fit=cover';
  const style = document.createElement('style');
  style.textContent = `
    header { padding-top: calc(env(safe-area-inset-top) + 8px) !important; }
    footer { padding-bottom: calc(env(safe-area-inset-bottom) + 6px) !important; }
    #banner { margin-top: env(safe-area-inset-top); }
    #settings > * { padding-top: calc(env(safe-area-inset-top) + 12px); }
    #onboard { padding-top: env(safe-area-inset-top); padding-bottom: env(safe-area-inset-bottom); }
    #start, #loading { padding-top: env(safe-area-inset-top); }
    #modes [data-mode="hybrid"], .row:has(#cloud-only), .row:has(#voice-auto), #voice-auto-note, #ear, .modo-telefono .set:has(#ear), .set:has(#output-select),
    #ob-engine-get, #ob-tts { display: none !important; }
    #text-send { display: grid !important; place-items: center; flex: 0 0 auto; width: 44px; height: 44px; margin-left: 6px;
      border-radius: 50%; border: none; background: var(--accent, #a78bfa); color: #14111f; }
    #text-send svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
    #text-form:not([hidden]) { display: flex; align-items: center; }
    #text-form #text-input { flex: 1 1 auto; min-width: 0; }
    #float-btn[hidden] { display: inline-grid !important; }
    /* Con el teclado, el margen de abajo del iPhone ya no cuenta (lo tapa el teclado): se sube su alto entero. */
    footer { transform: translateY(calc(-1 * var(--teclado, 0px)));
      transition: transform var(--teclado-t, 0.25s) ease-out; }
    .con-teclado footer { padding-bottom: 10px !important; }
    .con-teclado footer > .controls { display: none !important; }
    .phone-bar { height: 8px; border-radius: 4px; background: rgba(255,255,255,0.12); overflow: hidden; margin: 6px 0 10px; }
    .phone-bar i { display: block; height: 100%; background: var(--accent, #a78bfa); transition: width 0.4s; }
    .ob-label { display: block; margin: 14px 0 6px; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--dim); }
    .ob-check { display: flex; gap: 8px; align-items: center; font-size: 0.9rem; margin: 6px 0 12px; }
    .ob-actions { display: flex; gap: 12px; align-items: center; }`;
  document.head.append(style);

  // Si iOS interrumpe el audio de la página (una llamada, Siri, otra app), se reanuda solo al volver: si no, la voz
  // queda muda hasta reiniciar la app.
  setInterval(() => {
    const a = window.companion && window.companion.audio;
    if (a && a.ctx && a.ctx.state === 'interrupted') a.ctx.resume().catch(() => {});
  }, 1000);
  document.addEventListener('visibilitychange', () => {
    const a = window.companion && window.companion.audio;
    if (!document.hidden && a && a.ctx && a.ctx.state !== 'running') a.ctx.resume().catch(() => {});
  });

  // Teclado (lo mide el nativo, Bridge.watchKeyboard): solo la barra de abajo sube por encima; el personaje no se
  // mueve. Al cerrarlo, todo vuelve a su sitio.
  window.__teclado = (alto, dur) => {
    const root = document.documentElement.style;
    root.setProperty('--teclado', `${alto}px`);
    root.setProperty('--teclado-t', `${Math.max(0.1, dur || 0.25)}s`);
    document.body.classList.toggle('con-teclado', alto > 0);
  };

  // El botón de flotar (en la PC, la ventana flotante) abre aquí la ventana de picture in picture.
  const flotar = $('float-btn');
  if (flotar) {
    flotar.title = 'Ventana flotante: sigue contigo en las demás apps';
    flotar.setAttribute('aria-label', 'Ventana flotante');
    flotar.addEventListener('click', (e) => {
      e.stopImmediatePropagation(); e.preventDefault();
      (pip.on ? Promise.resolve(cerrarFlotante()) : abrirFlotante()).catch((err) => {
        console.warn('Ventana flotante', err);
        const t = document.getElementById('toast');
        if (t) { t.textContent = `No pude abrir la ventana flotante: ${err.message}`; t.hidden = false; setTimeout(() => { t.hidden = true; }, 4000); }
      });
    }, true);
  }

  // Tocar fuera del chat cierra el teclado (en iOS no se cierra solo).
  document.addEventListener('pointerdown', (e) => {
    const input = $('text-input');
    if (document.body.classList.contains('con-teclado') && input && !e.target.closest('#text-form')) input.blur();
  }, true);

  // Primer plano del personaje (de la cintura a la cabeza): en vertical, el encuadre de la PC lo dejaba lejos.
  const cerca = setInterval(() => {
    const av = window.companion && window.companion.avatar;
    if (!av) return;
    clearInterval(cerca);
    av.closeUp = true;
    if (!av.userMoved && av.frame) av.frame();
  }, 200);

  adaptarNodo(document.body);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'characterData') adaptarNodo(m.target.parentNode || document.body);
      else for (const n of m.addedNodes) adaptarNodo(n.nodeType === 1 ? n : (n.parentNode || document.body));
    }
    notas(window.__companionConfig);
  }).observe(document.body, { childList: true, subtree: true, characterData: true });

  // Selector de modo (0.9.1) en el teléfono: En vivo (recomendado), Solo nube y Todo en el teléfono.
  const card = (m, title, tag, text, tags) => {
    const b = document.querySelector(`#modes [data-mode="${m}"]`);
    if (!b) return;
    b.querySelector('.mode-top').replaceChildren(el('b', null, title), ...(tag ? [el('i', 'tag good', tag)] : []));
    b.querySelector('small').textContent = text;
    b.querySelector('.mode-tags').replaceChildren(...tags.map((t) => el('i', null, t)));
  };
  card('live', 'En vivo', 'Recomendado', 'Como una llamada: te oye, piensa y responde con su voz al instante, con Gemini Live.',
    ['Sin descargas', 'Necesita internet y una clave']);
  card('cloud', 'Nube', null, 'Piensa con Gemini y habla con las voces de Microsoft, por turnos.', ['Sin descargas', 'Necesita internet']);
  card('local', 'Todo en el teléfono', null, 'Nada sale del teléfono y funciona sin internet. Más lento y gasta más batería.',
    ['Máxima privacidad', 'Descarga unos 2,5 GB']);
  const hybrid = document.querySelector('#modes [data-mode="hybrid"]');
  if (hybrid) hybrid.hidden = true;
  const localCard = document.querySelector('#modes [data-mode="local"]');
  if (localCard) {
    localCard.addEventListener('click', async (e) => {
      if (window.__companionConfig && window.__companionConfig.mode === 'telefono') return;
      const s = await refrescar().catch(() => null);
      if (s && s.missing_bytes === 0) return;                 // ya están: cambia como en la PC
      e.stopImmediatePropagation();
      e.preventDefault();
      document.querySelector('[data-edit="local"]').click();  // primero, las descargas
    }, true);
  }

  // «Teléfono» en Ajustes › Cerebro: si faltan los modelos, se abre el paso de descargas en vez de cambiar.
  const local = document.querySelector('#provider [data-value="local"]');
  if (local) {
    const b = local.querySelector('b');
    if (b) b.textContent = 'Teléfono';
    local.addEventListener('click', async (e) => {
      if (window.__companionConfig && window.__companionConfig.mode === 'telefono') return;
      e.stopImmediatePropagation();
      e.preventDefault();
      const s = await refrescar().catch(() => null);
      if (s && s.missing_bytes === 0) { await api('/api/setup', { mode: 'telefono' }); location.reload(); return; }
      document.querySelector('[data-edit="local"]').click();
    }, true);
  }
  const cloud = document.querySelector('#provider [data-value="gemini"]');
  if (cloud) {
    cloud.addEventListener('click', async (e) => {
      if (!window.__companionConfig || window.__companionConfig.mode !== 'telefono') return;
      e.stopImmediatePropagation();
      e.preventDefault();
      try { await api('/api/setup', { mode: 'nube' }); location.reload(); } catch (err) { console.warn(err); }
    }, true);
  }
}
