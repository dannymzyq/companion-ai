// Bienvenida: perfil → cerebro (clave de API, o modelo local si no se quiere clave) → voz → modelo 3D.
// El último paso (micrófono y cámara) es la tarjeta de inicio de siempre. Cada paso se guarda en el servidor
// (data/settings.json) al pulsar «Siguiente», así que no se repite en la siguiente sesión; después, cada
// paso se puede abrir suelto desde Ajustes para cambiarlo (`edit`).

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const r = await fetch(path, body === undefined ? undefined
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo guardar. Inténtalo otra vez.');
  return data;
}

export function initOnboarding({ onDone, uploadModel, selectModel }) {
  const box = $('onboard');
  const sections = Object.fromEntries([...box.querySelectorAll('section')].map((s) => [s.dataset.step, s]));
  let setup = null;            // lo que devuelve /api/setup
  let step = 'perfil';
  let brain = 'cerebro';       // por cuál de los dos pasos del cerebro se pasó: 'cerebro' (clave) o 'local'
  let single = false;          // true = se abrió un solo paso desde Ajustes
  let gender = '';
  let checked = null;          // {preset, key, base} de la última clave comprobada con éxito
  let localPick = '';
  let voicePick = '';
  let enginePick = '';         // completa | ligera
  let poll = 0;
  let player = null;

  const order = () => ['perfil', brain, 'modelo', 'voz'];
  const fail = (msg) => { $('ob-error').textContent = msg || ''; $('ob-error').hidden = !msg; };

  function show(name) {
    step = name;
    fail('');
    clearInterval(poll);
    for (const k in sections) sections[k].hidden = k !== name;
    // Al elegir personaje la tarjeta baja y el fondo se aclara: detrás se ve el personaje, en vivo.
    box.classList.toggle('preview', name === 'modelo');
    const steps = order();
    $('ob-dots').hidden = single;
    $('ob-dots').replaceChildren(...[...steps, 'dispositivos'].map((s, i) => {
      const dot = document.createElement('i');
      if (i <= steps.indexOf(name)) dot.className = 'on';
      return dot;
    }));
    $('ob-back').textContent = single ? 'Cancelar' : 'Atrás';
    $('ob-back').hidden = !single && name === 'perfil';
    $('ob-next').textContent = single ? 'Guardar' : 'Siguiente';
    ({ perfil: fillProfile, cerebro: fillCloud, local: fillLocal, voz: fillVoices, modelo: fillModels })[name]();
    box.querySelector('.card').scrollTop = 0;
  }

  // ---------------------------------------------------------------- 1. perfil
  function fillProfile() {
    const p = setup.profile;
    $('ob-user').value = p.name || setup.suggested_name || '';
    $('ob-year').value = p.birth_year || '';
    $('ob-year').max = setup.year;
    gender = p.gender || '';
    paintGender(p.birth_year ? gender : null);
  }
  function paintGender(value) {
    for (const b of $('ob-gender').children) b.classList.toggle('on', value !== null && b.dataset.value === value);
  }
  for (const b of $('ob-gender').children) b.onclick = () => { gender = b.dataset.value; paintGender(gender); };

  async function saveProfile() {
    if (![...$('ob-gender').children].some((b) => b.classList.contains('on'))) throw new Error('Elige una opción de género (también puedes no decirlo).');
    await api('/api/setup', { profile: { name: $('ob-user').value, birth_year: $('ob-year').value, gender } });
  }

  // ---------------------------------------------------------------- 2a. clave de API
  function fillCloud() {
    const sel = $('ob-preset');
    sel.replaceChildren(...setup.presets.map((p) => new Option(p.name, p.id)));
    sel.value = setup.cloud.preset;
    $('ob-key').value = '';
    $('ob-base').value = setup.cloud.preset === 'custom' ? setup.cloud.base : '';
    checked = null;
    paintCloud();
    if (setup.cloud.model && setup.cloud.preset !== 'gemini') setModels([setup.cloud.model], setup.cloud.model);
  }
  function paintCloud() {
    const p = setup.presets.find((x) => x.id === $('ob-preset').value);
    const saved = setup.cloud.has_key && setup.cloud.preset === p.id;
    $('ob-preset-note').textContent = p.note;
    $('ob-base-box').hidden = p.id !== 'custom';
    $('ob-keys-link').hidden = !p.keys;
    $('ob-keys-link').href = p.keys || '#';
    $('ob-key').placeholder = saved ? `Clave guardada (${setup.cloud.key_hint}). Escribe otra para cambiarla` : 'Pega aquí tu clave';
    $('ob-model-box').hidden = p.id === 'gemini';
    $('ob-key-state').textContent = '';
    if (p.id !== setup.cloud.preset) setModels([], '');
  }
  function setModels(list, wanted) {
    const sel = $('ob-model');
    sel.replaceChildren(...(list.length ? list : ['']).map((m) => new Option(m || 'Comprueba la clave para ver los modelos', m)));
    if (wanted && list.includes(wanted)) sel.value = wanted;
  }
  $('ob-preset').onchange = () => { checked = null; paintCloud(); };
  $('ob-key').oninput = () => { checked = null; };
  $('ob-go-local').onclick = () => { brain = 'local'; show('local'); };

  async function saveCloud() {
    const preset = $('ob-preset').value, key = $('ob-key').value.trim(), base = $('ob-base').value.trim();
    const same = checked && checked.preset === preset && checked.key === key && checked.base === base;
    if (!same) {
      $('ob-key-state').textContent = 'Comprobando la clave…';
      const res = await api('/api/cloud/check', { preset, key, base }).finally(() => ($('ob-key-state').textContent = ''));
      checked = { preset, key, base };
      $('ob-key-state').textContent = 'Clave correcta.';
      if (preset !== 'gemini') {
        const before = $('ob-model').value;
        setModels(res.models, before || setup.cloud.model);
        if (!before) throw new Error('La clave funciona. Ahora elige el modelo que quieres usar y pulsa otra vez.');
      }
    }
    const model = preset === 'gemini' ? '' : $('ob-model').value;
    await api('/api/setup', { cloud: { preset, key, base, model }, provider: 'gemini' });
  }

  // ---------------------------------------------------------------- 2b. modelo local
  async function fillLocal() {
    const draw = () => {
      const l = setup.local, res = setup.resources;
      const gb = l.gpu ? Math.round(l.gpu.total / 1024) : 0;
      const n = (x) => String(x).replace('.', ',');
      // La voz, el oído y el modelo comparten la memoria de vídeo: se enseña la cuenta y qué cabe con cada voz.
      $('ob-gpu').textContent = l.gpu
        ? `Tu tarjeta gráfica tiene ${gb} GB de memoria de vídeo, y el modelo la comparte: el escritorio y el oído ocupan unos ${n(res.ear_gb + res.desktop_gb)} GB y la voz completa, unos ${n(res.engines.completa.vram_gb)} GB más. `
          + `Para el modelo quedan unos ${n(res.room.completa)} GB con la voz completa, o ${n(res.room.ligera)} GB con la voz ligera (que no usa la tarjeta). La voz se elige dos pasos más adelante.`
        : 'No encontré una tarjeta NVIDIA: el modelo correrá en el procesador y responderá despacio. Te conviene el más pequeño, con la voz ligera.';
      const fitText = (f) => (!l.gpu ? '' : f.completa ? ' Cabe junto a la voz completa.' : f.ligera ? ' Cabe solo con la voz ligera.' : ' No cabe en tu tarjeta: irá lento.');
      $('ob-ollama').hidden = l.ollama;
      if (!localPick) localPick = [l.selected, l.recommended].find((id) => l.models.some((m) => m.id === id && m.installed)) || '';
      const rows = l.models.map((m) => {
        const row = document.createElement('div');
        row.className = 'model-row' + (m.id === localPick ? ' on' : '') + (m.installed ? '' : ' off');
        const pick = document.createElement('button');
        pick.className = 'pick';
        pick.disabled = !m.installed;
        pick.innerHTML = '<b></b><small></small>';
        pick.firstChild.textContent = m.name;
        if (m.id === l.recommended) { const b = document.createElement('span'); b.className = 'badge'; b.textContent = 'Recomendado para tu PC'; pick.firstChild.append(b); }
        pick.lastChild.textContent = `${m.note} Descarga de ${n(m.size_gb)} GB · usa ${n(m.vram_gb)} GB de vídeo.${fitText(m.fits)}`;
        pick.onclick = () => { localPick = m.id; draw(); };
        row.append(pick);
        const pulling = m.pull && !m.pull.error && m.pull.status !== 'success';
        if (!m.installed) {
          const side = document.createElement(pulling ? 'span' : 'button');
          side.className = 'side';
          side.textContent = pulling ? `${m.pull.percent} %` : 'Descargar';
          if (!pulling) side.onclick = async () => { try { await api('/api/local-models/pull', { id: m.id }); await refresh(); } catch (e) { fail(e.message); } };
          row.append(side);
          if (m.pull && m.pull.error) fail(`No se pudo descargar ${m.name}: ${m.pull.error}`);
        }
        return row;
      });
      for (const o of l.others) {                    // otros modelos que el usuario ya tenía en Ollama
        const name = o.id;
        const row = document.createElement('div');
        row.className = 'model-row' + (name === localPick ? ' on' : '');
        const pick = document.createElement('button');
        pick.className = 'pick';
        pick.innerHTML = '<b></b><small></small>';
        pick.firstChild.textContent = name;
        pick.lastChild.textContent = `Ya instalado en Ollama · pide unos ${n(o.vram_gb)} GB de vídeo.${fitText(o.fits)}`;
        pick.onclick = () => { localPick = name; draw(); };
        row.append(pick);
        rows.push(row);
      }
      $('ob-local-list').replaceChildren(...rows);
    };
    const refresh = async () => { setup = await api('/api/setup'); if (step === 'local') draw(); };
    draw();
    poll = setInterval(() => refresh().catch(() => {}), 1500);       // progreso de descarga y si Ollama ya está abierto
  }

  async function saveLocal() {
    if (!localPick) throw new Error('Descarga y elige un modelo para continuar.');
    await api('/api/setup', { local_model: localPick, provider: 'local' });
  }

  // ---------------------------------------------------------------- 3. voz
  // Arriba, el motor de voz (completa: clonada, usa ~5 GB de vídeo · ligera: Piper, en el procesador), con la
  // recomendación para esta PC; debajo, la lista de voces, cuyas muestras suenan con el motor marcado.
  function drawEngine() {
    const e = setup.voice_engine, res = setup.resources;
    const local = setup.provider === 'local';
    const brain = local ? `el modelo local (${setup.local.selected})` : 'el cerebro en la nube';
    const gb = String(res.total_gb).replace('.', ',');
    $('ob-engine').replaceChildren(...Object.values(res.engines).map((x) => {
      const b = document.createElement('button');
      b.dataset.value = x.id;
      b.className = x.id === enginePick ? 'on' : '';
      b.innerHTML = '<b></b><small></small>';
      b.firstChild.textContent = x.name;
      if (x.id === e.recommended) { const s = document.createElement('span'); s.className = 'badge'; s.textContent = 'Recomendada para tu PC'; b.firstChild.append(s); }
      b.lastChild.textContent = x.note + (x.id === 'completa' && !e.node ? ' No está instalada.' : '') + (x.id === 'ligera' && !e.light_installed ? ` Hay que descargarla (${e.light_size_mb} MB).` : '');
      b.onclick = () => { enginePick = x.id; drawEngine(); };
      return b;
    }));
    $('ob-engine-note').textContent = !res.total_gb
      ? 'No encontré una tarjeta NVIDIA: la voz completa necesita una; aquí va la ligera.'
      : e.recommended === 'completa'
        ? `En tu tarjeta de ${gb} GB la voz completa cabe junto con ${brain}.`
        : (e.node ? `La voz completa usa unos ${String(res.engines.completa.vram_gb).replace('.', ',')} GB de memoria de vídeo y, junto con ${brain}, no cabe bien en tu tarjeta de ${gb} GB: mejor la ligera.`
          : 'La voz completa no está instalada en esta PC (instalar.ps1 -Voz ambas): usa la ligera.');
    const p = e.light_progress, loading = p && p.status === 'descargando';
    const get = $('ob-engine-get');
    get.hidden = !(enginePick === 'ligera' && !e.light_installed);
    get.disabled = !!loading;
    get.textContent = loading ? `Descargando la voz ligera… ${p.percent} %` : `Descargar la voz ligera (${e.light_size_mb} MB)`;
    if (p && p.error && enginePick === 'ligera' && !e.light_installed) fail(p.error);
  }
  $('ob-engine-get').onclick = async () => {
    try { await api('/api/voice-engine/install', {}); setup = await api('/api/setup'); drawEngine(); } catch (e) { fail(e.message); }
  };

  function fillVoices() {
    voicePick = (setup.voices.find((v) => v.selected) || {}).id || '';
    // Quien ya eligió ve su elección; en la bienvenida se parte de la recomendada para esta PC.
    enginePick = setup.onboarded ? setup.voice_engine.selected : setup.voice_engine.recommended;
    $('ob-tts').hidden = true;
    drawEngine();
    poll = setInterval(async () => {                 // progreso de la descarga de la voz ligera
      const p = setup.voice_engine.light_progress;
      if (step !== 'voz' || !(p && p.status === 'descargando')) return;
      try { setup = await api('/api/setup'); drawEngine(); } catch { /* servidor ocupado */ }
    }, 1500);
    const draw = () => {
      const rows = document.createElement('div');
      rows.className = 'model-list';
      {
        for (const v of setup.voices) {
          const row = document.createElement('div');
          row.className = 'model-row' + (v.id === voicePick ? ' on' : '') + (v.available ? '' : ' off');
          const pick = document.createElement('button');
          pick.className = 'pick';
          pick.disabled = !v.available;
          pick.innerHTML = '<b></b><small></small>';
          pick.firstChild.textContent = v.name;
          pick.lastChild.textContent = v.available ? (v.note || 'Disponible') : 'Próximamente';
          pick.onclick = () => { voicePick = v.id; draw(); };
          row.append(pick);
          if (v.available) {                   // la muestra está pregrabada: suena aunque el nodo de voz esté apagado
            const play = document.createElement('button');
            play.className = 'side';
            play.textContent = '▶';
            play.title = `Oír a ${v.name}`;
            play.onclick = () => preview(v.id, play);
            row.append(play);
          }
          rows.append(row);
        }
      }
      $('ob-voices').replaceChildren(rows);
    };
    draw();
  }
  async function preview(id, button) {
    if (player) { player.pause(); player = null; }
    button.textContent = '…';
    try {
      const r = await fetch('/api/voices/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, engine: enginePick }) });
      if (!r.ok) throw new Error(enginePick === 'ligera' && !setup.voice_engine.light_installed ? 'Descarga primero la voz ligera para oírla.' : 'No pude generar la muestra de esa voz.');
      player = new Audio(URL.createObjectURL(await r.blob()));
      await player.play();
    } catch (e) {
      fail(e.message);
    }
    button.textContent = '▶';
  }
  async function saveVoice() {
    if (player) { player.pause(); player = null; }
    if (enginePick === 'ligera' && !setup.voice_engine.light_installed) throw new Error('Descarga la voz ligera con el botón de arriba, o elige la voz completa.');
    await api('/api/setup', voicePick ? { voice: voicePick, voice_engine: enginePick } : { voice_engine: enginePick });
  }

  // ---------------------------------------------------------------- 4. modelo 3D
  async function fillModels() {
    const list = await api('/api/models');
    const entries = [...list.builtin.filter((m) => m.available).map((m) => ({ id: m.id, name: m.name, detail: m.note })),
      ...list.custom.map((m) => ({ id: m.id, name: m.name, detail: `Tu modelo · VRM ${m.spec} · ${m.size_mb} MB` }))];
    $('ob-models').replaceChildren(...entries.map((m) => {
      const row = document.createElement('div');
      row.className = 'model-row' + (m.id === list.active ? ' on' : '');
      const pick = document.createElement('button');
      pick.className = 'pick';
      pick.innerHTML = '<b></b><small></small>';
      pick.firstChild.textContent = m.name;                 // el nombre viene del archivo: nunca como HTML
      pick.lastChild.textContent = m.detail;
      pick.onclick = async () => { await selectModel(m.id); fillModels(); };
      row.append(pick);
      return row;
    }));
  }
  $('ob-upload').onclick = () => $('ob-file').click();
  $('ob-file').onchange = async (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) { await uploadModel(f); fillModels(); } };

  // ---------------------------------------------------------------- navegación
  const SAVE = { perfil: saveProfile, cerebro: saveCloud, local: saveLocal, voz: saveVoice, modelo: async () => {} };

  function close(changed) {
    clearInterval(poll);
    if (player) { player.pause(); player = null; }
    box.hidden = true;
    box.classList.remove('preview');
    $('start').style.visibility = '';
    onDone(changed, single);
  }

  $('ob-next').onclick = async () => {
    const button = $('ob-next');
    button.disabled = true;
    fail('');
    try {
      await SAVE[step]();
      if (single) return close(true);
      const steps = order(), i = steps.indexOf(step);
      if (i === steps.length - 1) {
        await api('/api/setup', { onboarded: true });       // lo que queda (micrófono y cámara) es la tarjeta de inicio
        return close(true);
      }
      setup = await api('/api/setup');
      for (const el of document.querySelectorAll('.ob-name')) el.textContent = setup.character;
      show(steps[i + 1]);
    } catch (e) {
      fail(e.message);
    } finally {
      button.disabled = false;
    }
  };

  $('ob-back').onclick = () => {
    if (single) return close(false);
    if (step === 'local') { brain = 'cerebro'; return show('cerebro'); }
    const steps = order();
    show(steps[Math.max(0, steps.indexOf(step) - 1)]);
  };

  async function open(first, alone) {
    setup = await api('/api/setup');
    single = alone;
    localPick = '';
    if (!alone) brain = setup.provider === 'local' && !setup.cloud.has_key ? 'local' : 'cerebro';
    for (const el of document.querySelectorAll('.ob-name')) el.textContent = setup.character;
    box.hidden = false;
    if (!alone) $('start').style.visibility = 'hidden';      // la tarjeta de inicio no debe tapar la vista del personaje
    show(first);
  }

  return {
    start: () => open('perfil', false),                      // la bienvenida completa
    edit: (name) => open(name, true),                        // un solo paso, desde Ajustes
    get open() { return !box.hidden; },
  };
}
