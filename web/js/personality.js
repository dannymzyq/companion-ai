// Ajustes › Personalidad (16 nov 2026): elegir una personalidad, personalizar una incluida (se copia como propia),
// crear una desde cero y ver su ánimo de ahora. Todo lo que viene del servidor se pinta con textContent.
const $ = (id) => document.getElementById(id);

// Las emociones como sustantivos, sin género (decisión del usuario del 12 nov 2026).
export const EMOTION_NAMES = {
  neutral: 'Neutral', feliz: 'Alegría', emocionada: 'Emoción', timida: 'Timidez', sonrojada: 'Rubor', triste: 'Tristeza',
  molesta: 'Enfado', sorprendida: 'Sorpresa', pensativa: 'Reflexión', carinosa: 'Cariño', enamorada: 'Amor',
  nerviosa: 'Nervios', asustada: 'Miedo', confundida: 'Confusión',
};

export function initPersonality({ toast, onChange = () => {} }) {
  let data = null, editing = null, picked = [], busy = false;

  // Cambiar de personalidad puede tardar unos segundos (con el cerebro local, el modelo lee ya el prompt nuevo):
  // mientras tanto, «Ajustando…» encima de la lista y nada más se puede pulsar. Si el servidor no contesta en 30 s,
  // se deja de esperar y se avisa (antes se quedaba sin respuesta y parecía colgado).
  const post = async (url, body, method = 'POST') => {
    const stop = new AbortController();
    const timer = setTimeout(() => stop.abort(), 30000);
    try {
      const r = await fetch(url, { method, signal: stop.signal, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(out.detail || 'No se pudo guardar.');
      return out;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('El cambio tarda demasiado. Se aplicará en su próxima respuesta.');
      throw e;
    } finally { clearTimeout(timer); }
  };

  async function adjusting(work) {
    if (busy) return;
    busy = true;
    const shade = setTimeout(() => { $('personality-busy').hidden = false; }, 150);   // si es instantáneo, ni se ve
    $('personality-group').setAttribute('aria-busy', 'true');
    for (const b of $('personality-group').querySelectorAll('button, input, textarea, select')) b.disabled = true;
    try { await work(); }
    catch (e) { toast(e.message, true); refresh(); }
    finally {
      clearTimeout(shade);
      $('personality-busy').hidden = true;
      $('personality-group').removeAttribute('aria-busy');
      for (const b of $('personality-group').querySelectorAll('button, input, textarea, select')) b.disabled = false;
      busy = false;
    }
  }

  function render() {
    const box = $('personality-list');
    box.replaceChildren();
    for (const p of data.personalities) {
      const row = document.createElement('div');
      row.className = 'model-row' + (p.id === data.active ? ' on' : '');
      row.dataset.id = p.id;
      const pick = document.createElement('button');
      pick.className = 'pick';
      const name = document.createElement('b');
      name.textContent = p.name;
      const detail = document.createElement('small');
      detail.textContent = (p.builtin ? '' : 'Propia · ') + (p.summary || p.description.slice(0, 110));
      pick.append(name, detail);
      pick.onclick = () => select(p.id);
      const edit = document.createElement('button');
      edit.className = 'side';
      edit.textContent = p.builtin ? 'Personalizar' : 'Editar';
      edit.title = p.builtin ? 'Hacer una copia propia para ajustarla' : 'Cambiar esta personalidad';
      edit.onclick = () => open(p);
      row.append(pick, edit);
      if (!p.builtin) {
        const del = document.createElement('button');
        del.className = 'del';
        del.title = 'Borrar esta personalidad';
        del.setAttribute('aria-label', `Borrar ${p.name}`);
        del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>';
        del.onclick = () => remove(p);
        row.append(del);
      }
      box.append(row);
    }
    const active = data.personalities.find((p) => p.id === data.active);
    const mood = EMOTION_NAMES[data.mood?.emotion] || 'Neutral';
    $('sum-personalidad').textContent = `${active ? active.name : ''} · ánimo: ${mood.toLowerCase()}`;
    $('mood-line').textContent = `Ahora se le nota: ${mood.toLowerCase()}. De siempre: ${(EMOTION_NAMES[active?.base_mood] || 'Neutral').toLowerCase()}.`;
  }

  async function refresh() {
    try { data = await (await fetch('/api/personality')).json(); } catch { return; }
    render();
  }

  async function select(id) {
    if (busy || (data && id === data.active)) return;
    // Se marca ya la elegida, para que se vea al instante qué se pulsó.
    for (const row of $('personality-list').children) row.classList.toggle('on', row.dataset.id === id);
    await adjusting(async () => {
      data = await post('/api/personality/select', { id });
      render(); onChange(); toast('Listo: se nota desde su próxima respuesta.');
    });
  }

  async function remove(p) {
    if (!confirm(`¿Borrar la personalidad «${p.name}»? No se puede deshacer.`)) return;
    await adjusting(async () => {
      data = await post(`/api/personality/custom/${encodeURIComponent(p.id)}`, null, 'DELETE'); render(); onChange();
    });
  }

  function traitsForm(values) {
    const box = $('pf-traits');
    box.replaceChildren();
    for (const [key, meta] of Object.entries(data.traits)) {
      const wrap = document.createElement('div');
      wrap.className = 'trait';
      const head = document.createElement('div');
      head.className = 'trait-head';
      const label = document.createElement('span');
      label.textContent = meta.label;
      const ends = document.createElement('small');
      ends.textContent = `${meta.low} ↔ ${meta.high}`;
      head.append(label, ends);
      const range = document.createElement('input');
      range.type = 'range'; range.min = '0'; range.max = '100'; range.step = '5';
      range.dataset.trait = key;
      range.value = String(Math.round(100 * (values?.[key] ?? meta.default)));
      range.setAttribute('aria-label', meta.label);
      wrap.append(head, range);
      box.append(wrap);
    }
  }

  function emotionsForm() {
    const box = $('pf-emotions');
    box.replaceChildren();
    for (const e of data.emotions) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = EMOTION_NAMES[e] || e;
      b.className = picked.includes(e) ? 'on' : '';
      b.onclick = () => {
        picked = picked.includes(e) ? picked.filter((x) => x !== e) : [...picked, e].slice(-3);
        emotionsForm();
      };
      box.append(b);
    }
  }

  function open(p) {
    // p: una incluida (se copia), una propia (se cambia) o null (desde cero).
    editing = p && !p.builtin ? p.id : null;
    const src = p || { traits: {}, formality: 'casual', base_mood: 'feliz', emotions: [] };
    $('pf-title').textContent = !p ? 'Una personalidad nueva, a tu medida.'
      : p.builtin ? `Una copia de «${p.name}» para ajustarla a tu gusto. La incluida no cambia.` : `Cambiando «${p.name}».`;
    $('pf-name').value = !p ? '' : p.builtin ? `${p.name} (mía)` : p.name;
    $('pf-summary').value = src.summary || '';
    $('pf-description').value = src.description || '';
    $('pf-speech').value = src.speech || '';
    $('pf-catch').value = (src.catchphrases || []).join(', ');
    $('pf-likes').value = (src.likes || []).join(', ');
    $('pf-dislikes').value = (src.dislikes || []).join(', ');
    $('pf-examples').value = (src.examples || []).join('\n');
    $('pf-formality').replaceChildren(...Object.entries(data.formality).map(([v, t]) => new Option(t, v, false, v === src.formality)));
    $('pf-mood').replaceChildren(...data.emotions.map((e) => new Option(EMOTION_NAMES[e] || e, e, false, e === src.base_mood)));
    picked = [...(src.emotions || [])];
    traitsForm(src.traits);
    emotionsForm();
    $('personality-form').dataset.from = p && p.builtin ? p.id : (p?.from || '');
    $('personality-form').hidden = false;
    $('personality-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('pf-name').focus({ preventScroll: true });
  }

  const close = () => { $('personality-form').hidden = true; editing = null; };

  $('personality-new').onclick = () => open(null);
  $('pf-cancel').onclick = close;
  $('personality-form').onsubmit = async (ev) => {
    ev.preventDefault();
    const traits = {};
    for (const r of $('pf-traits').querySelectorAll('input[type=range]')) traits[r.dataset.trait] = Number(r.value) / 100;
    const body = {
      id: editing || undefined, from: $('personality-form').dataset.from || undefined,
      name: $('pf-name').value, summary: $('pf-summary').value, description: $('pf-description').value,
      traits, formality: $('pf-formality').value, speech: $('pf-speech').value, catchphrases: $('pf-catch').value,
      likes: $('pf-likes').value, dislikes: $('pf-dislikes').value, base_mood: $('pf-mood').value, emotions: picked,
      examples: $('pf-examples').value,
    };
    // El formulario se queda (con lo escrito) hasta que se guarda: si falla, no se pierde nada.
    $('personality-group').scrollIntoView({ behavior: 'smooth', block: 'start' });
    await adjusting(async () => {
      data = await post('/api/personality/custom', body);
      close();
      onChange();
      render();
      toast('Personalidad guardada y elegida: se nota desde su próxima respuesta.');
    });
  };

  return { refresh };
}
