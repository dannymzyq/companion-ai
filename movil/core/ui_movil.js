// Capa de interfaz del teléfono sobre web/ (que es la de la PC): elegir el modo «todo dentro del teléfono» con sus
// descargas, textos adaptados al teléfono, márgenes de la barra de estado y lo que aquí no existe, oculto.
// La carga boot.js; onboarding.js le pasa el paso «local» (window.companionPhone).

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
    .phone-bar { height: 8px; border-radius: 4px; background: rgba(255,255,255,0.12); overflow: hidden; margin: 6px 0 10px; }
    .phone-bar i { display: block; height: 100%; background: var(--accent, #a78bfa); transition: width 0.4s; }
    .ob-label { display: block; margin: 14px 0 6px; font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--dim); }
    .ob-check { display: flex; gap: 8px; align-items: center; font-size: 0.9rem; margin: 6px 0 12px; }
    .ob-actions { display: flex; gap: 12px; align-items: center; }`;
  document.head.append(style);

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
    local.querySelector('b').textContent = 'Teléfono';
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
