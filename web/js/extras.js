// Módulos extra interactivos (N-02, N-04, N-06, N-07, N-08, N-09, N-10, F-03, F-06):
//   · Compañera de Enfoque (Pomodoro con racha diaria)
//   · Presets de personaje + Accesorios 3D acoplables
//   · Diario de recuerdos con búsqueda instantánea FTS, fijado 📌, edición en línea y lista de recordatorios
//   · Mochila del Compañero (exportar/importar sin secretos) + Modo En Casa (emparejamiento LAN opt-in)
//   · Mini-juegos interactivos (Piedra-papel-tijera 1-2-3, Trivia, 20 preguntas, Veo-veo)
//   · Puente MCP local opt-in + Actualización verificada en 1 clic
// Todo el contenido dinámico usa exclusivamente textContent / createElement (cero innerHTML con datos del servidor).
import { ACCESSORY_LIST } from './props.js';

const $ = (id) => document.getElementById(id);
const ACC_KEY = 'companion.accessories';

async function jfetch(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Operación no disponible.');
  return data;
}

function fmtMMSS(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  const m = Math.floor(s / 60), r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

export function initExtras({ getAvatar, getConfig, send, toast, reloadAll }) {
  // ================================================================ 1. Accesorios 3D y Presets (N-06)
  let activeAcc = [];
  try { activeAcc = JSON.parse(localStorage.getItem(ACC_KEY) || '[]'); } catch { activeAcc = []; }
  if (!Array.isArray(activeAcc)) activeAcc = [];

  function syncAccessories() {
    try { localStorage.setItem(ACC_KEY, JSON.stringify(activeAcc)); } catch {}
    const av = getAvatar();
    if (av && av.setAccessories) av.setAccessories(activeAcc);
    const box = $('accessory-chips');
    if (!box) return;
    box.replaceChildren(...ACCESSORY_LIST.map((item) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = item.name;
      b.className = activeAcc.includes(item.id) ? 'on' : '';
      b.onclick = () => {
        activeAcc = activeAcc.includes(item.id) ? activeAcc.filter((x) => x !== item.id) : [...activeAcc, item.id];
        syncAccessories();
      };
      return b;
    }));
  }

  async function refreshPresets() {
    const box = $('preset-list');
    if (!box) return;
    let data;
    try { data = await jfetch('/api/presets'); } catch { return; }
    const presets = data.presets || [];
    if (!presets.length) {
      const empty = document.createElement('small');
      empty.className = 'note';
      empty.textContent = 'Guarda combinaciones de modelo 3D, voz, personalidad y accesorios para cambiar en un clic.';
      box.replaceChildren(empty);
      return;
    }
    box.replaceChildren(...presets.map((p) => {
      const row = document.createElement('div');
      row.className = 'model-row';
      const pick = document.createElement('button');
      pick.type = 'button';
      pick.className = 'pick';
      const b = document.createElement('b');
      b.textContent = p.name;
      const sm = document.createElement('small');
      const parts = [p.voice, p.model_id, p.personality_id].filter(Boolean);
      sm.textContent = parts.join(' · ') || 'Combinación guardada';
      pick.append(b, sm);
      pick.onclick = async () => {
        try {
          await jfetch(`/api/presets/${encodeURIComponent(p.id)}/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          });
          if (Array.isArray(p.accessories)) {
            activeAcc = [...p.accessories];
            syncAccessories();
          }
          await reloadAll();
          toast(`Preset «${p.name}» aplicado.`);
        } catch (e) { toast(e.message, true); }
      };
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'del';
      del.title = `Quitar ${p.name}`;
      del.textContent = '✕';
      del.onclick = async () => {
        try {
          await jfetch(`/api/presets/${encodeURIComponent(p.id)}`, { method: 'DELETE' });
          refreshPresets();
        } catch (e) { toast(e.message, true); }
      };
      row.append(pick, del);
      return row;
    }));
  }

  const presetSaveBtn = $('preset-save');
  if (presetSaveBtn) {
    presetSaveBtn.onclick = async () => {
      const input = $('preset-name');
      const cfg = getConfig();
      const name = (input && input.value.trim()) || (cfg ? `${cfg.name} favorito` : 'Mi preset');
      try {
        await jfetch('/api/presets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, accessories: activeAcc }),
        });
        if (input) input.value = '';
        await refreshPresets();
        toast(`Preset «${name}» guardado.`);
      } catch (e) { toast(e.message, true); }
    };
  }

  // ================================================================ 2. Pomodoro / Enfoque (N-02)
  let focusState = { phase: 'idle', remaining_sec: 0, streak: 0, completed_today: 0 };
  let focusSyncedAt = performance.now();

  function renderFocus() {
    const chip = $('focus-chip');
    const statusEl = $('focus-status');
    const elapsed = focusState.phase !== 'idle' ? (performance.now() - focusSyncedAt) / 1000 : 0;
    const baseRem = focusState.remaining_s ?? focusState.remaining_sec ?? 0;
    const rem = Math.max(0, baseRem - elapsed);
    const active = focusState.phase === 'work' || focusState.phase === 'break';

    if (chip) {
      chip.hidden = !active;
      if (active) {
        const tag = focusState.phase === 'work' ? 'Enfoque' : 'Descanso';
        chip.textContent = `${tag} ${fmtMMSS(rem)}${focusState.streak ? ` · 🔥${focusState.streak}` : ''}`;
      }
    }
    if (statusEl) {
      if (active) {
        const label = focusState.phase === 'work' ? 'Concentración en marcha' : 'Pausa de descanso';
        statusEl.textContent = `${label}: quedan ${fmtMMSS(rem)} · Hoy: ${focusState.completed_today || 0} bloques · Racha: ${focusState.streak || 0} días.`;
      } else {
        statusEl.textContent = `Sin sesión activa · Hoy: ${focusState.completed_today || 0} bloques · Racha: ${focusState.streak || 0} días.`;
      }
    }
    const stopBtn = $('focus-stop');
    if (stopBtn) stopBtn.hidden = !active;
  }

  async function refreshFocus() {
    try {
      focusState = await jfetch('/api/focus');
      focusSyncedAt = performance.now();
      renderFocus();
    } catch { /* edición sin endpoint de enfoque */ }
  }

  async function startFocus(workMin, breakMin) {
    try {
      focusState = await jfetch('/api/focus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'start', work_min: workMin, break_min: breakMin }),
      });
      focusSyncedAt = performance.now();
      renderFocus();
      toast(`Enfoque iniciado (${workMin}/${breakMin} min).`);
    } catch (e) { toast(e.message, true); }
  }

  async function stopFocus() {
    try {
      focusState = await jfetch('/api/focus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'stop' }),
      });
      focusSyncedAt = performance.now();
      renderFocus();
      toast('Sesión de enfoque detenida.');
    } catch (e) { toast(e.message, true); }
  }

  if ($('focus-25')) $('focus-25').onclick = () => startFocus(25, 5);
  if ($('focus-50')) $('focus-50').onclick = () => startFocus(50, 10);
  if ($('focus-stop')) $('focus-stop').onclick = stopFocus;
  setInterval(() => { if (focusState.phase !== 'idle') renderFocus(); }, 1000);

  function onFocusEvent(ev) {
    focusState = { ...focusState, ...ev };
    focusSyncedAt = performance.now();
    renderFocus();
  }

  // ================================================================ 3. Diario de Recuerdos FTS + Recordatorios (N-07, F-03)
  let memTimer = 0;

  async function refreshMemory(query = null) {
    const box = $('memory-list');
    if (!box) return;
    const q = query !== null ? query : ($('memory-search') ? $('memory-search').value.trim() : '');
    let data = null;
    try {
      data = await jfetch(`/api/memory/diary?q=${encodeURIComponent(q)}`);
    } catch {
      try {
        const legacy = await jfetch('/api/memory');
        data = {
          items: (legacy.facts || []).map((f, idx) => ({ id: idx, content: f, pinned: false, legacy: true })),
          diary: legacy.summaries || [],
          can_undo: !!legacy.can_undo,
        };
      } catch { return; }
    }

    const rows = [];
    if (data.can_undo && !q) {
      const undo = document.createElement('button');
      undo.type = 'button';
      undo.className = 'ghost';
      undo.textContent = 'Deshacer el último orden automático de recuerdos';
      undo.onclick = async () => { await fetch('/api/memory/undo', { method: 'POST' }); refreshMemory(); };
      rows.push(undo);
    }

    for (const item of data.items || []) {
      const itemText = item.fact ?? item.content ?? '';
      const row = document.createElement('div');
      row.className = 'mem-item' + (item.pinned ? ' pinned' : '');
      const text = document.createElement('span');
      text.textContent = itemText;

      if (!item.legacy) {
        const pin = document.createElement('button');
        pin.type = 'button';
        pin.className = 'mem-btn' + (item.pinned ? ' on' : '');
        pin.textContent = '📌';
        pin.title = item.pinned ? 'Quitar fijado' : 'Fijar recuerdo (nunca se resume ni se descarta)';
        pin.onclick = async () => {
          try {
            await jfetch(`/api/memory/item/${item.id}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ pinned: !item.pinned }),
            });
            refreshMemory();
          } catch (e) { toast(e.message, true); }
        };

        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'mem-btn';
        edit.textContent = '✎';
        edit.title = 'Editar este recuerdo';
        edit.onclick = () => {
          const inp = document.createElement('input');
          inp.type = 'text';
          inp.className = 'mem-edit-input';
          inp.value = itemText;
          inp.maxLength = 280;
          const save = async () => {
            const val = inp.value.trim();
            if (!val || val === itemText) { refreshMemory(); return; }
            try {
              await jfetch(`/api/memory/item/${item.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fact: val }),
              });
              refreshMemory();
            } catch (e) { toast(e.message, true); refreshMemory(); }
          };
          inp.onkeydown = (ev) => {
            if (ev.key === 'Enter') { ev.preventDefault(); save(); }
            else if (ev.key === 'Escape') { ev.stopPropagation(); refreshMemory(); }
          };
          inp.onblur = save;
          row.replaceChildren(inp);
          inp.focus();
        };
        row.append(pin, text, edit);
      } else {
        row.append(text);
      }

      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = '✕';
      del.title = 'Olvidar esto';
      del.onclick = async () => {
        await fetch('/api/memory/forget', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fact: item.fact || item.content }),
        });
        refreshMemory();
      };
      row.append(del);
      rows.push(row);
    }

    for (const s of (data.summaries || data.diary || []).slice().reverse()) {
      const row = document.createElement('div');
      const date = document.createElement('b');
      date.textContent = s.date || '';
      const text = document.createElement('span');
      text.textContent = s.text || '';
      row.append(date, text);
      rows.push(row);
    }

    if (!rows.length) {
      const empty = document.createElement('div');
      empty.textContent = q ? 'Ningún recuerdo coincide con tu búsqueda.' : 'Todavía no hay recuerdos guardados.';
      rows.push(empty);
    }
    box.replaceChildren(...rows);
  }

  const memSearch = $('memory-search');
  if (memSearch) {
    memSearch.oninput = () => {
      clearTimeout(memTimer);
      memTimer = setTimeout(() => refreshMemory(memSearch.value.trim()), 200);
    };
  }

  async function refreshReminders() {
    const box = $('reminders-list');
    if (!box) return;
    let data;
    try { data = await jfetch('/api/reminders'); } catch { return; }
    const items = data.reminders || [];
    if (!items.length) {
      const empty = document.createElement('div');
      empty.textContent = 'No hay recordatorios ni temporizadores pendientes.';
      box.replaceChildren(empty);
      return;
    }
    box.replaceChildren(...items.map((r) => {
      const row = document.createElement('div');
      const when = document.createElement('b');
      const dt = new Date((r.due_ts || 0) * 1000);
      when.textContent = Number.isNaN(dt.getTime()) ? '' : dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const txt = document.createElement('span');
      txt.textContent = `${r.kind === 'timer' ? '⏱ ' : '🔔 '}${r.text}`;
      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = '✕';
      del.title = 'Cancelar aviso';
      del.onclick = async () => {
        try {
          await jfetch(`/api/reminders/${r.id}`, { method: 'DELETE' });
          refreshReminders();
        } catch (e) { toast(e.message, true); }
      };
      row.append(when, txt, del);
      return row;
    }));
  }

  // ================================================================ 4. Mochila + Modo En Casa (N-04)
  if ($('backpack-export')) {
    $('backpack-export').onclick = async () => {
      try {
        const pack = await jfetch('/api/backpack');
        const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const stamp = new Date().toISOString().slice(0, 10);
        a.href = url;
        a.download = `mochila-companion-${stamp}.json`;
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        toast('Mochila exportada (sin claves ni secretos).');
      } catch (e) { toast(e.message, true); }
    };
  }
  if ($('backpack-import-btn') && $('backpack-file')) {
    $('backpack-import-btn').onclick = () => $('backpack-file').click();
    $('backpack-file').onchange = async (e) => {
      const f = e.target.files[0];
      e.target.value = '';
      if (!f) return;
      try {
        const raw = JSON.parse(await f.text());
        const res = await jfetch('/api/backpack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...raw, merge: true }),
        });
        await reloadAll();
        toast(`Mochila importada (${res.imported_memories || 0} recuerdos nuevos).`);
      } catch (err) {
        toast(err.message || 'Archivo de mochila no válido.', true);
      }
    };
  }

  let pairUrlNow = '';
  const pickPairUrl = (st) => (st && ((st.pair_urls && st.pair_urls[0]) || (st.urls && st.urls[0]) || st.url)) || '';
  async function refreshPairing() {
    const sw = $('pairing-on');
    const box = $('pairing-box');
    if (!sw || !box) return;
    let st;
    try { st = await jfetch('/api/pairing'); } catch { sw.closest('.set-card')?.setAttribute('hidden', ''); return; }
    sw.checked = !!st.enabled;
    box.hidden = !st.enabled;
    pairUrlNow = pickPairUrl(st);
    if ($('pairing-url')) $('pairing-url').textContent = pairUrlNow || 'Activa Wi-Fi o LAN para ver el enlace local.';
  }

  if ($('pairing-on')) {
    $('pairing-on').onchange = async () => {
      try {
        const st = await jfetch('/api/pairing', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: $('pairing-on').checked }),
        });
        pairUrlNow = pickPairUrl(st);
        if ($('pairing-box')) $('pairing-box').hidden = !st.enabled;
        if ($('pairing-url')) $('pairing-url').textContent = pairUrlNow || 'Activa Wi-Fi o LAN para ver el enlace local.';
        toast(st.enabled ? 'Modo En Casa activado en tu red local.' : 'Modo En Casa desactivado.');
      } catch (e) {
        $('pairing-on').checked = !$('pairing-on').checked;
        toast(e.message, true);
      }
    };
  }
  if ($('pairing-copy')) {
    $('pairing-copy').onclick = async () => {
      if (!pairUrlNow) return;
      try {
        await navigator.clipboard.writeText(pairUrlNow);
        toast('Enlace de emparejamiento copiado.');
      } catch { toast(pairUrlNow); }
    };
  }
  if ($('pairing-rotate')) {
    $('pairing-rotate').onclick = async () => {
      try {
        const st = await jfetch('/api/pairing', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: true, rotate: true }),
        });
        pairUrlNow = pickPairUrl(st);
        if ($('pairing-url')) $('pairing-url').textContent = pairUrlNow;
        toast('Código de emparejamiento renovado.');
      } catch (e) { toast(e.message, true); }
    };
  }

  // ================================================================ 5. Mini-Juegos + RPS 1-2-3 (N-08)
  const rpsBar = $('rps-bar');
  for (const b of document.querySelectorAll('[data-game]')) {
    b.onclick = () => {
      const g = b.dataset.game;
      send({ type: 'game', game: g });
      if (rpsBar) rpsBar.hidden = g !== 'rps';
      $('settings').hidden = true;
    };
  }
  if (rpsBar) {
    for (const b of rpsBar.querySelectorAll('[data-rps]')) {
      b.onclick = () => send({ type: 'text', text: b.dataset.rps });
    }
    const closeRps = $('rps-close');
    if (closeRps) closeRps.onclick = () => { rpsBar.hidden = true; };
  }

  function onRpsEvent(ev) {
    if (rpsBar) rpsBar.hidden = false;
    const av = getAvatar();
    const choice = ev.pick || ev.choice;
    if (av && choice) {
      const map = { piedra: '_rps_piedra', papel: '_rps_papel', tijera: '_rps_tijera' };
      const g = map[choice];
      if (g) av.playGesture(g);
    }
  }

  // ================================================================ 6. Puente MCP Local (N-10) & Resumen matutino (N-09)
  async function refreshMcp() {
    const sw = $('mcp-on');
    const list = $('mcp-list');
    if (!sw || !list) return;
    let st;
    try { st = await jfetch('/api/mcp'); } catch { sw.closest('.set-card')?.setAttribute('hidden', ''); return; }
    sw.checked = !!st.enabled;
    const servers = st.servers || [];
    const tools = st.tools || [];
    const rows = servers.map((srv) => {
      const row = document.createElement('div');
      const b = document.createElement('b');
      b.textContent = srv.name || 'MCP';
      const s = document.createElement('span');
      const count = tools.filter((t) => (t.server_id && t.server_id === srv.id) || t.server_name === srv.name || t.server === srv.name).length;
      const detail = srv.command ? [srv.command, ...(srv.args || [])].join(' ') : (srv.url || '');
      s.textContent = `${detail ? detail + ' · ' : ''}${count} herramientas`;
      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = '✕';
      del.onclick = async () => {
        try {
          await jfetch('/api/mcp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ remove_id: srv.id }),
          });
          refreshMcp();
        } catch (e) { toast(e.message, true); }
      };
      row.append(b, s, del);
      return row;
    });
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.textContent = 'Ningún servidor MCP local añadido (solo 127.0.0.1 / localhost).';
      rows.push(empty);
    }
    list.replaceChildren(...rows);
  }

  if ($('mcp-on')) {
    $('mcp-on').onchange = async () => {
      try {
        await jfetch('/api/mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: $('mcp-on').checked }),
        });
        refreshMcp();
      } catch (e) { toast(e.message, true); }
    };
  }
  if ($('mcp-add')) {
    $('mcp-add').onclick = async () => {
      const nameEl = $('mcp-name'), urlEl = $('mcp-url');
      const name = (nameEl && nameEl.value.trim()) || 'local';
      const raw = (urlEl && urlEl.value.trim()) || '';
      if (!raw) { toast('Escribe la dirección local del servidor MCP (http://127.0.0.1:…).', true); return; }
      try {
        await jfetch('/api/mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: true, add: { name, url: raw } }),
        });
        if (nameEl) nameEl.value = '';
        if (urlEl) urlEl.value = '';
        refreshMcp();
        toast(`Servidor MCP «${name}» conectado.`);
      } catch (e) { toast(e.message, true); }
    };
  }

  const briefChk = $('morning-briefing');
  if (briefChk) {
    briefChk.onchange = async () => {
      try {
        await jfetch('/api/setup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ morning_briefing: briefChk.checked }),
        });
      } catch (e) { toast(e.message, true); }
    };
  }

  syncAccessories();
  refreshFocus();

  return {
    syncAccessories,
    refreshPresets,
    refreshFocus,
    refreshMemory,
    refreshReminders,
    refreshPairing,
    refreshMcp,
    onFocusEvent,
    onRpsEvent,
    applyConfig(cfg) {
      if (briefChk && cfg && cfg.morning_briefing !== undefined) briefChk.checked = !!cfg.morning_briefing;
    },
  };
}

export function createUpdateApplyButton(updateInfo, toast) {
  if (!updateInfo || !updateInfo.asset_url) return null;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'mini primary-mini';
  btn.style.marginLeft = '8px';
  btn.textContent = 'Actualizar ahora';
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = 'Verificando descarga…';
    try {
      const r = await fetch('/api/update/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || 'No se pudo descargar la actualización.');
      toast('Instalador verificado (SHA-256) y abierto.');
      btn.textContent = 'Descargado ✓';
    } catch (e) {
      toast(e.message || 'Error al actualizar.', true);
      btn.disabled = false;
      btn.textContent = 'Actualizar ahora';
    }
  };
  return btn;
}
