// Pantalla de carga (15 nov 2026): al abrir el companion, y después de cambiar un ajuste que carga algo (el oído
// local, la voz completa, el modelo local), enseña qué se está preparando y se quita sola cuando todo está listo.
// El servidor dice qué carga (/api/loading); el personaje 3D lo añade la interfaz. Lo que falla no la bloquea: se
// marca y se sigue. Tras unos segundos aparece «Seguir sin esperar».
const STEP = 700;                         // ms entre consultas
const LIMIT = 4 * 60 * 1000;              // nunca se queda más de 4 minutos

export function initLoading({ avatarState = () => 'listo' } = {}) {
  const $ = (id) => document.getElementById(id);
  const box = $('loading');
  let timer = null, until = 0, shownAt = 0, withAvatar = false, skipped = false;

  function render(items) {
    const list = $('loading-items');
    list.replaceChildren();
    for (const it of items) {
      const li = document.createElement('li');
      li.className = it.state;
      const name = document.createElement('span');
      name.textContent = it.label;
      const detail = document.createElement('small');
      detail.textContent = it.state === 'cargando' ? (it.detail || 'cargando…')
        : it.state === 'error' ? (it.detail || 'no disponible') : (it.detail || 'listo');
      li.append(name, detail);
      list.append(li);
    }
    const total = items.length || 1;
    const done = items.filter((i) => i.state !== 'cargando').length;
    $('loading-bar').style.width = `${Math.round((100 * done) / total)}%`;
  }

  function hide() {
    clearTimeout(timer);
    timer = null;
    if (box.hidden) return;
    box.classList.add('leaving');
    setTimeout(() => { box.hidden = true; box.classList.remove('leaving'); }, 350);
  }

  async function tick(title) {
    let data;
    try { data = await (await fetch('/api/loading', { cache: 'no-store' })).json(); } catch { data = null; }
    const items = data ? [...data.items] : [{ id: 'servidor', label: 'El servidor del companion', state: 'cargando' }];
    if (withAvatar) {
      const s = avatarState();
      items.push({ id: 'avatar', label: 'El personaje 3D', state: s, detail: s === 'error' ? 'se queda la esfera' : '' });
    }
    const busy = items.some((i) => i.state === 'cargando');
    if (busy && box.hidden && !skipped) {
      $('loading-title').textContent = title;
      $('loading-skip').hidden = true;
      box.hidden = false;
      shownAt = Date.now();
    }
    if (!box.hidden) {
      render(items);
      if (Date.now() - shownAt > 4000) $('loading-skip').hidden = false;
    }
    if (!busy || Date.now() > until || skipped) {
      if (!box.hidden) setTimeout(hide, busy ? 0 : 500);      // un instante con todo marcado como listo
      timer = null;
      return;
    }
    timer = setTimeout(() => tick(title), STEP);
  }

  function run(title, avatar, delay) {
    clearTimeout(timer);
    withAvatar = avatar;
    skipped = false;
    until = Date.now() + LIMIT;
    timer = setTimeout(() => tick(title), delay);
  }

  $('loading-skip').onclick = () => { skipped = true; hide(); };

  return {
    // Al abrir: se enseña ya (hasta la primera respuesta) y espera también al personaje 3D.
    start(name) {
      $('loading-title').textContent = `Preparando a ${name}`;
      render([{ id: 'servidor', label: 'Conectando con el companion', state: 'cargando' }]);
      $('loading-skip').hidden = true;
      box.hidden = false;
      shownAt = Date.now();
      run(`Preparando a ${name}`, true, 0);
    },
    // Tras un cambio de ajustes: solo aparece si de verdad algo se está cargando.
    watch(title = 'Aplicando los cambios…') {
      if (timer && !box.hidden) return;   // ya está a la vista
      run(title, false, 400);
    },
    get visible() { return !box.hidden; },
  };
}
