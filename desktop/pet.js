// Mascota de escritorio: lo que hace el personaje con la ventana flotante (solo en modo flotante).
//   · sigue el ratón con la mirada (la página recibe dónde está el cursor)
//   · gravedad: al soltarla en el aire cae hasta la barra de tareas (o hasta el borde de una ventana)
//   · pasea de vez en cuando por el borde de abajo
//   · se sienta sobre la ventana activa y la sigue si la mueves
//   · acompaña las acciones «controlar»: va al lado de la ventana y, en cada paso que tiene un punto (un botón, un
//     campo), se coloca para que su mano derecha quede sobre él y lo «pulsa» ella: de pie, en cuclillas o de rodillas
//     si está abajo en la pantalla, de puntillas si está arriba (16 nov 2026). Mientras, la ventana no recibe clics.
// La página (web/js/main.js) pone las animaciones; aquí se decide qué hacer y se mueve la ventana. Todo en
// coordenadas de pantalla de Electron (DIP). La ventana activa se pregunta al servidor (/api/desktop/scene): solo
// su posición, nunca el título ni el contenido. Con algo a pantalla completa (un juego, un vídeo) se queda quieta.
const http = require('http');

const DEFAULT_PREFS = { follow: true, react: true, gravity: true, walk: 'aveces', sit: false, work: true, fade: true };
const WALK_EVERY = { aveces: [40, 110], amenudo: [12, 40] };     // segundos entre paseos
const WALK_HZ = 0.95;                     // ciclos de marcha por segundo (el mismo que web/js/avatar.js)
const GRAVITY = 2800;                     // px/s²
// Movimiento fluido (17 nov 2026): en Windows los temporizadores del proceso principal van a saltos de 15,6 ms, y
// setInterval(16) daba en realidad un cuadro cada 31 ms (medido): la caída, los saltos y los paseos se veían a ~32
// fps. Ahora cada cuadro lo marca la propia página (requestAnimationFrame, al ritmo de la pantalla) mientras algo se
// mueve, y este temporizador solo hace de respaldo si la página no los manda (oculta, en las pruebas).
const FALLBACK_MS = 8;                    // con el reloj de Windows, ~15,6 ms (64 Hz)
const SIT_POLL_MS = 150;                  // sentada: se mira a menudo dónde está su ventana, para seguirla sin saltos
const POLL_MS = 600;

function create({ screen, getWin, getView, getMode, urlBase, test }) {
  let prefs = { ...DEFAULT_PREFS };
  let anchors = null;                     // {feet, seat, head, hand, w, h} en px de la ventana (los manda la página)
  let pageState = 'idle';
  let mode = 'off';                       // off | stand | sit | drag | fall | walk | travel | work
  let anim = null;                        // movimiento en curso: { step(dt) → true al acabar }
  let loop = null, ticker = null, poller = null;
  let lastFrame = 0, pageFrameAt = 0, framesOn = false, moving = false;
  let follow = null;                      // posición con decimales mientras se acerca a un punto (sin quedarse corta)
  let sitGoal = null;                     // adonde va la ventana sentada cuando su ventana se mueve
  let insets = '';
  let restWanted = false;                 // le entró sueño: va a una esquina a recostarse (avatar.js, LEAN)
  let fps = { n: 0, t0: 0, last: 0, page: 0 };      // cuadros por segundo del último movimiento (para las pruebas)
  let lastCursor = null;
  let scene = { fg: null, sit: null };
  let testScene = null;
  let sitOn = null;                       // { id, relX } ventana sobre la que está sentada
  let nextWalk = 0;
  let fgSeen = { id: null, since: 0 };
  let lastJump = 0;
  let dragStart = null, carried = false;
  let work = null;                        // { home, ended, returnAt, sawSpeaking }
  let activity = 'none';
  let ticks = 0;

  const now = () => Date.now() / 1000;
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const win = () => { const w = getWin(); return w && !w.isDestroyed() ? w : null; };

  function send(ev) {
    const v = getView();
    if (v && !v.webContents.isDestroyed()) v.webContents.send('pet:event', ev);
  }
  function setActivity(name, opts = {}) {
    activity = name;
    send({ type: 'activity', name, opts });
  }

  // ---------------------------------------------------------------- pantallas y posición
  function displays() {
    if (test) return [{ id: 1, workArea: { x: -4000, y: -4000, width: 1600, height: 900 }, bounds: { x: -4000, y: -4000, width: 1600, height: 940 } }];
    return screen.getAllDisplays();
  }
  function A() {
    const w = win();
    const b = w ? w.getBounds() : { width: 340, height: 527 };
    const base = { feet: { x: b.width / 2, y: b.height }, seat: { x: b.width / 2, y: b.height * 0.62 }, head: { x: b.width / 2, y: b.height * 0.1 },
      hand: { x: b.width * 0.68, y: b.height * 0.42 }, w: b.width, h: b.height };
    if (!anchors) return base;
    // Muy acercada (Ctrl + rueda), los pies quedan por debajo de la ventana: entonces lo que «pisa» es el borde de
    // abajo de la ventana (si no, se quedaba flotando en el aire con las piernas cortadas, 17 nov 2026).
    const feet = anchors.feet.y > b.height ? { x: anchors.feet.x, y: b.height } : anchors.feet;
    return { ...base, ...anchors, feet, hand: anchors.hand || base.hand };
  }
  function point(anchor = 'feet', b = win().getBounds()) {
    const a = A()[anchor];
    return { x: b.x + a.x, y: b.y + a.y };
  }
  function displayAt(x, y) {
    let best = null, bestD = Infinity;
    for (const d of displays()) {
      const r = d.workArea;
      const dx = x < r.x ? r.x - x : x > r.x + r.width ? x - r.x - r.width : 0;
      const dy = y < r.y ? r.y - y : y > r.y + r.height ? y - r.y - r.height : 0;
      const dist = dx * dx + dy * dy;
      if (dist < bestD) { best = d; bestD = dist; }
    }
    return best;
  }
  function floorY(x, y) { const r = displayAt(x, y).workArea; return r.y + r.height; }
  // Coloca la ventana para que ese punto del personaje quede en (x, y).
  function boundsFor(x, y, anchor = 'feet') {
    const w = win(), b = w.getBounds(), a = A()[anchor];
    return { x: Math.round(x - a.x), y: Math.round(y - a.y), width: b.width, height: b.height };
  }
  // Siempre con el tamaño fijo: una ventana transparente sin marco, con el escalado de Windows al 150 %, crece unos
  // píxeles cada vez que se mueve con setPosition o con el tamaño que devuelve getBounds (medido, 16 nov 2026).
  let size = null;
  function moveTo(b) {
    const w = win();
    if (!w) return;
    if (!size) { const c = w.getBounds(); size = { width: c.width, height: c.height }; }
    w.setBounds({ x: Math.round(b.x), y: Math.round(b.y), width: size.width, height: size.height });
  }

  function dip(rect) {                    // [izq, arriba, der, abajo] en píxeles reales → {x, y, width, height} DIP
    if (!rect) return null;
    const r = { x: rect[0], y: rect[1], width: rect[2] - rect[0], height: rect[3] - rect[1] };
    if (process.platform === 'win32' && !test && screen.screenToDipRect) {
      try { return screen.screenToDipRect(null, r); } catch { /* sin conversión */ }
    }
    return r;
  }

  // ---------------------------------------------------------------- bucle de movimiento (solo mientras algo se mueve)
  function animate(a) {
    if (!anim) fps = { n: 0, t0: performance.now(), last: fps.last, page: 0 };
    anim = a;
    syncFrames();
  }
  function stopAnim() { anim = null; }
  function needFrames() { return !!anim || !!sitGoal || (mode === 'work' && !!work && !!work.target && !work.ended); }
  // Un cuadro: lo que esté en marcha avanza según el tiempo de verdad (dt), venga de la página o del respaldo.
  function frame() {
    const t = performance.now(), dt = Math.min(0.05, Math.max(0, (t - lastFrame) / 1000));
    lastFrame = t;
    if (!win() || mode === 'off') return syncFrames();
    if (anim) {
      const cur = anim;
      fps.n++;
      if (t - pageFrameAt < 1) fps.page++;
      if (cur.step(dt)) {
        if (anim === cur) anim = null;
        const secs = (performance.now() - fps.t0) / 1000;
        if (!anim && secs > 0.1) fps.last = { fps: Math.round(fps.n / secs), page: Math.round((100 * fps.page) / Math.max(1, fps.n)) };
        if (cur.done) cur.done();
      }
    }
    if (mode === 'work') followPoint(dt);
    if (sitGoal) followSeat(dt);
    syncFrames();
  }
  function syncFrames() {
    const need = needFrames() && mode !== 'off';
    if (need && !loop) {
      lastFrame = performance.now();
      loop = setInterval(() => { if (performance.now() - pageFrameAt > 60) frame(); }, FALLBACK_MS);
    } else if (!need && loop) { clearInterval(loop); loop = null; }
    if (need !== framesOn) { framesOn = need; send({ type: 'frames', on: need }); }
    syncMoving();
  }
  // Mientras se mueve (cae, salta, pasea, la llevas o está con una acción) solo se ve al personaje: la página
  // esconde la barra y los subtítulos.
  function syncMoving() {
    const on = mode !== 'off' && (!!anim || ['fall', 'walk', 'travel', 'work'].includes(mode) || (mode === 'drag' && carried)
      || (!!work && !work.ended));
    if (on !== moving) { moving = on; send({ type: 'moving', on }); }
  }
  // Lo que queda fuera del área de trabajo de la pantalla (debajo de la barra de tareas, fuera por un lado), en px de
  // la ventana: con el personaje acercado (Ctrl + rueda) los pies quedan más abajo y la barra se iría con ellos.
  function syncInsets() {
    const w = win();
    if (!w) return;
    const b = w.getBounds(), wa = displayAt(b.x + b.width / 2, b.y + b.height / 2).workArea;
    const cut = {
      top: Math.max(0, wa.y - b.y), bottom: Math.max(0, b.y + b.height - (wa.y + wa.height)),
      left: Math.max(0, wa.x - b.x), right: Math.max(0, b.x + b.width - (wa.x + wa.width)),
    };
    const key = JSON.stringify(cut);
    if (key !== insets) { insets = key; send({ type: 'insets', ...cut }); }
  }

  // Caer hasta el suelo o hasta el borde de la ventana que tenga debajo.
  function fall() {
    const w = win();
    if (!w) return;
    const b = w.getBounds(), feet = point('feet', b), seat = point('seat', b);
    const floor = floorY(feet.x, feet.y);
    let targetY = floor - A().feet.y, sitTarget = null;
    const fg = scene.fg && dip(scene.fg.rect);
    if (prefs.sit && fg && suitable(scene.fg) && seat.x >= fg.x + 20 && seat.x <= fg.x + fg.width - 20 && seat.y <= fg.y + 4) {
      const y = fg.y - A().seat.y;
      if (y < targetY) { targetY = y; sitTarget = { id: scene.fg.id, relX: seat.x - fg.x, side: sideOf(seat.x - fg.x, fg.width) }; }
    }
    if (b.y >= targetY - 1) {             // ya está en el suelo (o por debajo: se coloca encima)
      if (b.y > targetY + 1) moveTo({ ...b, y: Math.round(targetY) });
      return landed(sitTarget);
    }
    mode = 'fall';
    setActivity('fall');
    let y = b.y, vy = 0;
    animate({
      step(dt) {
        vy += GRAVITY * dt;
        y = Math.min(targetY, y + vy * dt);
        const cur = win().getBounds();
        moveTo({ ...cur, y: Math.round(y) });
        return y >= targetY;
      },
      done: () => landed(sitTarget),
    });
  }
  function landed(sitTarget) {
    if (sitTarget) {
      mode = 'sit';
      sitOn = sitTarget;
      setActivity('sit', { side: sitOn.side || 1 });
    } else {
      mode = 'stand';
      sitOn = null;
      setActivity(work && !work.ended ? 'work' : 'none', work && !work.ended ? { side: work.side } : {});
    }
    if (work && !work.ended && !sitTarget) mode = 'work';
    scheduleWalk();
    settle();
  }

  // Que siga pisando el suelo (o sentada en su borde) con el encuadre de ahora: los puntos del personaje cambian si
  // cambia el tamaño de la ventana, el modelo o el encuadre, también a mitad de una caída.
  function settle() {
    const w = win();
    if (!w || anim) return;
    const b = w.getBounds();
    if ((mode === 'stand' || (mode === 'work' && !(work && work.target))) && prefs.gravity) {
      const feet = point('feet', b), y = floorY(feet.x, feet.y) - A().feet.y;
      if (Math.abs(b.y - y) > 1) moveTo({ ...b, y: Math.round(y) });
    } else if (mode === 'sit' && sitOn && scene.sit) {
      const nb = seatOn(scene.sit, sitOn.relX).bounds;
      if (Math.abs(nb.x - b.x) > 1 || Math.abs(nb.y - b.y) > 1) moveTo(nb);
    }
  }

  // Viaje en un salto (de la barra a una ventana, al lado de la ventana que maneja, de vuelta a casa).
  function travel(target, then) {
    const w = win();
    if (!w) return;
    const from = w.getBounds();
    const dist = Math.hypot(target.x - from.x, target.y - from.y);
    if (dist < 4) { moveTo(target); if (then) then(); return; }
    const dur = clamp(dist / 900, 0.45, 1.3), arc = Math.min(220, dist * 0.3);
    mode = 'travel';
    setActivity('fall');
    const after = then;
    then = () => { if (after) after(); settle(); };
    let u = 0;
    animate({
      step(dt) {
        u = Math.min(1, u + dt / dur);
        const e = u * u * (3 - 2 * u);
        moveTo({ ...from, x: Math.round(from.x + (target.x - from.x) * e), y: Math.round(from.y + (target.y - from.y) * e - arc * Math.sin(Math.PI * u)) });
        return u >= 1;
      },
      done: then,
    });
  }

  // ---------------------------------------------------------------- paseos
  function scheduleWalk() {
    const r = WALK_EVERY[prefs.walk];
    nextWalk = r ? now() + rand(r[0], r[1]) : Infinity;
  }
  function paused() { return !!(scene.fg && scene.fg.fullscreen && !scene.fg.own); }
  function maybeWalk() {
    if (mode !== 'stand' || anim || pageState !== 'idle' || paused() || work || now() < nextWalk) return;
    const w = win(), b = w.getBounds(), feet = point('feet', b);
    const wa = displayAt(feet.x, feet.y).workArea, margin = A().w * 0.3;
    const lo = wa.x + margin, hi = wa.x + wa.width - margin;
    let dx = rand(120, 420) * (Math.random() < 0.5 ? -1 : 1);
    if (feet.x + dx < lo || feet.x + dx > hi) dx = -dx;
    const goal = clamp(feet.x + dx, lo, hi);
    scheduleWalk();
    if (Math.abs(goal - feet.x) < 60) return;
    // La ventana avanza lo que avanzan los pies (si no, parece que patina): dos pasos por ciclo de WALK_HZ, cada
    // uno de ~0,65 veces el largo de la pierna, visto casi de perfil.
    // Con las animaciones grabadas (17 nov 2026) la página manda el largo de su paso (`step`, en px) y, con los
    // estilos de 100STYLE, su ritmo (`hz`) y lo que avanza la persona grabada (`speed`, px/s): se mira en cada
    // cuadro, porque el estilo cambia con la emoción.
    const speedNow = () => {
      const a = A(), leg = Math.max(40, a.feet.y - a.seat.y);
      if (a.speed) return clamp(a.speed * 0.93, 25, 420);
      return clamp(a.step ? 2 * a.step * (a.hz || WALK_HZ) * 0.93 : 2 * 0.65 * leg * WALK_HZ * 0.93, 25, 420);
    };
    walkTo(goal, speedNow);
  }
  // Andar hasta `goal` (x de los pies en la pantalla). toRest: va a recostarse (no se para porque esté «dormida»).
  function walkTo(goal, speedNow, then, toRest = false) {
    const feet = point('feet');
    const dir = goal > feet.x ? 1 : -1;
    mode = 'walk';
    setActivity('walk', { dir });
    let x = feet.x;
    animate({
      step(dt) {
        if (mode !== 'walk') return true;
        if (toRest ? !restWanted : pageState !== 'idle') return true;     // le hablas (o se despertó): se para
        x += dir * speedNow() * dt;
        const done = dir > 0 ? x >= goal : x <= goal;
        const cur = win().getBounds();
        moveTo({ ...cur, x: Math.round((done ? goal : x) - A().feet.x) });
        return done;
      },
      done: () => {
        const arrived = Math.abs(point('feet').x - goal) < 3;
        if (mode === 'walk') { mode = 'stand'; setActivity('none'); }
        if (then && arrived) then();
      },
    });
  }
  // Le entró sueño (17 nov 2026): va andando a la esquina de abajo más cercana y avisa a la página para que se
  // recueste con la espalda hacia el borde de la pantalla (side = +1 si el borde queda a su derecha).
  function rest(on) {
    restWanted = !!on;
    if (!on || getMode() !== 'float' || !win()) return;
    const feet = point('feet'), wa = displayAt(feet.x, feet.y).workArea;
    const side = feet.x > wa.x + wa.width / 2 ? 1 : -1;
    const there = () => { if (restWanted) send({ type: 'rest', side }); };
    if (mode !== 'stand' || work || paused()) return there();              // ocupada o con un juego: ahí mismo
    const half = A().w / 2;
    const goal = side > 0 ? wa.x + wa.width - half : wa.x + half;
    if (Math.abs(goal - feet.x) < 6) return there();
    const speed = () => {
      const a = A(), leg = Math.max(40, a.feet.y - a.seat.y);
      return clamp(a.speed ? a.speed * 0.8 : 2 * 0.65 * leg * WALK_HZ * 0.8, 25, 360);      // con sueño, algo más despacio
    };
    walkTo(goal, speed, there, true);
  }

  // ---------------------------------------------------------------- sentarse sobre ventanas
  // Sentada de costado, mirando hacia el centro de la ventana (las piernas no cuelgan por fuera del borde).
  function sideOf(relX, width) { return relX > width / 2 ? -1 : 1; }
  function suitable(fg) {
    if (!fg || fg.own || fg.minimized || fg.maximized || fg.fullscreen) return false;
    const r = dip(fg.rect);
    if (!r || r.width < 220 || r.height < 120) return false;
    const d = displayAt(r.x + r.width / 2, r.y);
    return r.y - A().seat.y + A().head.y >= d.workArea.y - 4;          // le cabe la cabeza por encima
  }
  function seatOn(fg, relX) {
    const r = dip(fg.rect);
    const margin = A().w * 0.25;
    const x = relX !== undefined ? r.x + clamp(relX, margin, r.width - margin) : r.x + clamp(r.width * 0.78, margin, r.width - margin);
    return { bounds: boundsFor(x, r.y, 'seat'), relX: x - r.x };
  }
  function onScene() {
    if (getMode() !== 'float' || mode === 'off') return;
    // Sentada: sigue a su ventana; si se minimiza, se maximiza o se cierra, cae.
    if (mode === 'sit' && sitOn) {
      const s = scene.sit;
      if (!prefs.sit || !s || s.minimized || s.maximized || s.fullscreen) { sitOn = null; mode = 'stand'; return prefs.gravity ? fall() : setActivity('none'); }
      const { bounds } = seatOn({ ...s, rect: s.rect }, sitOn.relX);
      const b = win().getBounds();
      if (Math.abs(bounds.x - b.x) > 1 || Math.abs(bounds.y - b.y) > 1) {
        if (Math.hypot(bounds.x - b.x, bounds.y - b.y) > 600) moveTo(bounds);       // otra pantalla: de golpe
        else { sitGoal = { x: bounds.x, y: bounds.y, pos: sitGoal && sitGoal.pos }; syncFrames(); }
      }
    }
    // De pie y sin nada que hacer: si cambias a otra ventana (y se queda un momento), salta a sentarse encima.
    const fg = scene.fg;
    if (!fg || fg.own) return;
    if (fg.id !== fgSeen.id) { fgSeen = { id: fg.id, since: now() }; return; }
    if (!prefs.sit || paused() || work || anim || pageState !== 'idle' || !['stand', 'sit'].includes(mode)) return;
    if (sitOn && sitOn.id === fg.id) return;
    if (now() - fgSeen.since < 1.2 || now() - lastJump < 12 || !suitable(fg)) return;
    lastJump = now();
    const { bounds, relX } = seatOn(fg);
    const side = sideOf(relX, dip(fg.rect).width);
    travel(bounds, () => { mode = 'sit'; sitOn = { id: fg.id, relX, side }; setActivity('sit', { side }); });
  }
  function poll() {
    // Solo hace falta saber de las ventanas para sentarse, para no pasear con un juego a pantalla completa y mientras
    // vuelve de una acción.
    if (!prefs.sit && prefs.walk === 'nunca' && !work) return;
    if (test) {                            // pruebas: ventanas inventadas, nunca las de verdad
      const t = testScene || {};
      scene = { fg: t.fg || null, sit: sitOn && t.windows ? t.windows[sitOn.id] || null : null };
      onScene();
      return;
    }
    const q = sitOn ? `?sit=${encodeURIComponent(sitOn.id)}` : '';
    const req = http.get(`${urlBase}/api/desktop/scene${q}`, { timeout: 1500 }, (r) => {
      let body = '';
      r.on('data', (c) => { body += c; });
      r.on('end', () => { try { scene = JSON.parse(body); onScene(); } catch { /* sin datos */ } });
    });
    req.on('error', () => {});
    req.on('timeout', () => req.destroy());
  }

  // ---------------------------------------------------------------- trabajar en una ventana (acción «controlar»)
  function workStart(info) {
    if (!prefs.work || getMode() !== 'float') return;
    const w = win();
    if (!w) return;
    stopAnim();
    const b = w.getBounds(), feet = point('feet', b);
    const d0 = displayAt(feet.x, feet.y).workArea;
    work = { home: { bounds: b, mode: mode === 'sit' ? 'sit' : 'stand', sitOn }, ended: false, returnAt: 0, sawSpeaking: false,
      side: feet.x < d0.x + d0.width / 2 ? 1 : -1 };
    const r = info && info.window && !info.window.minimized && dip(info.window.rect);
    const there = () => { mode = 'work'; sitOn = null; setActivity('work', { side: work.side }); };
    if (!r) return there();                                  // minimizada o sin saber dónde: trabaja donde está
    const d = displayAt(r.x + r.width / 2, r.y + r.height / 2).workArea;
    const need = A().w * 0.6;
    const right = d.x + d.width - (r.x + r.width), left = r.x - d.x;
    let x;
    if (right >= need) { x = r.x + r.width + need / 2; work.side = -1; }      // a su derecha, mirando a la izquierda
    else if (left >= need) { x = r.x - need / 2; work.side = 1; }
    else { x = d.x + d.width - need / 2; work.side = -1; }                     // ventana maximizada: en la esquina
    travel(boundsFor(x, d.y + d.height, 'feet'), there);
  }
  // Un paso con punto: la postura según la altura del punto en su pantalla, y allá va la mano.
  function workPoint(msg) {
    const r = dip([msg.point[0], msg.point[1], msg.point[0] + 1, msg.point[1] + 1]);
    if (!r) return;
    const d = displayAt(r.x, r.y).workArea, rel = (r.y - d.y) / Math.max(1, d.height);
    const kind = msg.kind || 'click';
    const stance = rel > 0.7 ? (kind === 'type' ? 'kneel' : (Math.random() < 0.5 ? 'crouch' : 'kneel')) : rel < 0.28 ? 'reach' : 'stand';
    work.target = { x: r.x, y: r.y };
    work.side = 1;
    const pose = () => { mode = 'work'; setActivity('work', { side: 1, point: true }); send({ type: 'workmode', mode: kind, stance }); };
    const w = win();
    if (w && !anim) {
      const b = w.getBounds(), goal = boundsFor(r.x, r.y, 'hand');
      if (Math.hypot(goal.x - b.x, goal.y - b.y) > 160) return travel(goal, pose);   // lejos: de un salto, y al llegar, la postura
    }
    pose();                                       // cerca (o a mitad de un salto): la postura ya, y tick() la acerca
    if (anim) { const cur = anim, done = cur.done; cur.done = () => { if (done) done(); if (work && !work.ended) pose(); }; }
  }
  // Que la punta del índice siga sobre el punto (la mano cambia de sitio al cambiar de postura).
  function followPoint(dt) {
    const w = win();
    if (!w || anim || !work || !work.target || work.ended) { follow = null; return; }
    const b = w.getBounds(), goal = boundsFor(work.target.x, work.target.y, 'hand');
    if (!follow || Math.hypot(follow.x - b.x, follow.y - b.y) > 2) follow = { x: b.x, y: b.y };
    const dx = goal.x - follow.x, dy = goal.y - follow.y;
    if (Math.hypot(dx, dy) < 0.6) return;
    const k = 1 - Math.exp(-9 * dt);                  // se acerca con suavidad, cuadro a cuadro
    follow.x += dx * k; follow.y += dy * k;
    moveTo({ ...b, x: follow.x, y: follow.y });
  }
  // Sentada sobre una ventana que se mueve: la sigue con suavidad (los datos llegan cada SIT_POLL_MS).
  function followSeat(dt) {
    const w = win();
    if (!w || mode !== 'sit' || anim) { sitGoal = null; return; }
    const b = w.getBounds();
    const cur = sitGoal.pos || (sitGoal.pos = { x: b.x, y: b.y });
    const dx = sitGoal.x - cur.x, dy = sitGoal.y - cur.y;
    if (Math.hypot(dx, dy) < 0.6) { moveTo({ ...b, x: sitGoal.x, y: sitGoal.y }); sitGoal = null; return; }
    const k = 1 - Math.exp(-18 * dt);
    cur.x += dx * k; cur.y += dy * k;
    moveTo({ ...b, x: cur.x, y: cur.y });
  }
  function workEnd(ok) {
    if (!work) return;
    work.target = null;
    work.ended = true;
    work.returnAt = now() + 14;
    if (mode === 'work') mode = 'stand';
    setActivity('none');
    send({ type: 'gesture', name: ok ? 'celebrar' : 'encogerse' });
  }
  function workReturn() {
    const home = work.home;
    work = null;
    if (getMode() !== 'float' || !win()) return;
    if (home.mode === 'sit' && home.sitOn && prefs.sit && scene.fg && scene.fg.id === home.sitOn.id && suitable(scene.fg)) {
      const { bounds, relX } = seatOn(scene.fg, home.sitOn.relX);
      const side = home.sitOn.side || 1;
      return travel(bounds, () => { mode = 'sit'; sitOn = { id: home.sitOn.id, relX, side }; setActivity('sit', { side }); });
    }
    const feet = point('feet', home.bounds);
    travel(boundsFor(feet.x, floorY(feet.x, feet.y), 'feet'), () => { mode = 'stand'; setActivity('none'); scheduleWalk(); });
  }
  function quick() {                       // acciones sencillas (abrir una app, una web…): se gira un momento
    if (!prefs.work || work || getMode() !== 'float') return;
    const w = win(), feet = point('feet', w.getBounds()), d = displayAt(feet.x, feet.y).workArea;
    const side = feet.x < d.x + d.width / 2 ? 1 : -1;
    setActivity('work', { side });
    send({ type: 'workmode', mode: 'click' });
    setTimeout(() => {
      if (activity === 'work' && !work) setActivity(mode === 'sit' ? 'sit' : 'none', mode === 'sit' && sitOn ? { side: sitOn.side || 1 } : {});
    }, 1700);
  }

  // ---------------------------------------------------------------- cada ~30 ms mientras flota
  function tick() {
    const w = win();
    if (!w || getMode() !== 'float') return;
    if (prefs.follow) {
      const c = screen.getCursorScreenPoint(), b = w.getBounds();
      if (!lastCursor || c.x !== lastCursor.x || c.y !== lastCursor.y) {
        lastCursor = c;
        send({ type: 'cursor', x: c.x - b.x, y: c.y - b.y });
      }
    }
    maybeWalk();
    syncFrames();
    if (++ticks % 8 === 0) syncInsets();
    if (ticks % 60 === 0) settle();
    if (work && work.ended) {
      if (pageState === 'speaking') work.sawSpeaking = true;
      if ((work.sawSpeaking && pageState === 'idle') || now() > work.returnAt) workReturn();
    }
  }

  function start() {
    if (mode !== 'off') return;
    size = null;
    mode = 'stand';
    scheduleWalk();
    ticker = setInterval(tick, 16);                  // ~15,6 ms en Windows: mirada y estado
    const again = () => { poll(); poller = setTimeout(again, mode === 'sit' ? SIT_POLL_MS : POLL_MS); };
    poller = setTimeout(again, POLL_MS);
    setTimeout(() => { if (mode === 'stand' && prefs.gravity) fall(); }, 700);   // al empezar a flotar: al suelo
  }
  function stop() {
    mode = 'off';
    stopAnim();
    clearInterval(ticker); clearTimeout(poller);
    ticker = poller = null;
    sitGoal = null; follow = null;
    syncFrames();
    sitOn = null;
    work = null;
    activity = 'none';
  }

  return {
    start, stop,
    // La página dibujó un cuadro (requestAnimationFrame): mientras algo se mueve, se mueve con ella.
    pageFrame() { pageFrameAt = performance.now(); if (framesOn) frame(); },
    // ---- de main.js
    onDrag(phase) {
      if (mode === 'off') return;
      const w = win();
      if (phase === 'start') {
        stopAnim();
        dragStart = w.getBounds();
        carried = false;
        mode = 'drag';
        sitOn = null;
      } else if (phase === 'move') {
        const b = w.getBounds();
        if (!carried && dragStart && Math.hypot(b.x - dragStart.x, b.y - dragStart.y) > 6) { carried = true; setActivity('carried'); syncMoving(); }
      } else {
        mode = 'stand';
        syncMoving();
        if (!carried) return setActivity(work && !work.ended ? 'work' : 'none', work && !work.ended ? { side: work.side } : {});
        if (prefs.gravity) fall();
        else { setActivity(work && !work.ended ? 'work' : 'none', work && !work.ended ? { side: work.side } : {}); scheduleWalk(); }
      }
    },
    // ---- de la página
    setPrefs(p) {
      const before = prefs;
      prefs = { ...DEFAULT_PREFS, ...(p || {}) };
      if (!WALK_EVERY[prefs.walk] && prefs.walk !== 'nunca') prefs.walk = 'aveces';
      if (before.walk !== prefs.walk) scheduleWalk();
      if (before.sit && !prefs.sit && mode === 'sit') { sitOn = null; mode = 'stand'; if (prefs.gravity) fall(); else setActivity('none'); }
      if (!before.gravity && prefs.gravity && mode === 'stand') fall();
    },
    setAnchors(a) {
      if (!a || !a.feet || !a.seat) return;
      const first = !anchors;
      anchors = a;
      if (first && mode === 'stand' && prefs.gravity) return fall();
      settle();                         // cambió el encuadre: que siga pisando el suelo o sentada
    },
    setState(s) { pageState = String(s || 'idle'); },
    rest,
    work(msg) {
      if (!msg) return;
      if (msg.phase === 'start') workStart(msg);
      else if (msg.phase === 'step' && work && !work.ended) {
        if (Array.isArray(msg.point) && msg.point.length === 2 && msg.point.every(Number.isFinite)) workPoint(msg);
        else send({ type: 'workmode', mode: msg.kind || 'read' });
      }
      else if (msg.phase === 'end') workEnd(!!msg.ok);
      else if (msg.phase === 'quick') quick();
    },
    setTestScene(s) { if (test) testScene = s; },
    // main.js cambió el tamaño de la ventana flotante (rueda del ratón): ese es el tamaño fijo desde ahora.
    resized(b) { if (b) size = { width: b.width, height: b.height }; },
    // Solo en las pruebas: subirla para verla caer, o pasear ya.
    testCmd(cmd) {
      if (!test || !win()) return;
      if (cmd.cmd === 'lift') { const b = win().getBounds(); moveTo({ ...b, y: b.y - (cmd.dy || 300) }); mode = 'stand'; fall(); }
      if (cmd.cmd === 'walk') { mode = 'stand'; nextWalk = 0; maybeWalk(); }
    },
    info() {
      const w = win(), b = w ? w.getBounds() : null, h = A().hand;
      return { mode, activity, sitOn, working: !!work, paused: paused(), anchors: !!anchors, feetY: anchors ? anchors.feet.y : null, prefs,
        moving, lastMoveFps: fps.last,
        target: work && work.target, hand: b ? { x: b.x + h.x, y: b.y + h.y } : null };
    },
  };
}

module.exports = { create, DEFAULT_PREFS };
