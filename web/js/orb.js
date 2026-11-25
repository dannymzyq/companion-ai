// El personaje neutro: una esfera con cara y dos manitas flotantes. No tiene esqueleto como los VRM, pero
// muestra lo mismo: cambia de color con cada emoción, mueve ojos, cejas y boca, se encoge, tiembla o salta,
// mueve la boca con la voz y hace los gestos ([gesto:...]) con las manos.

import * as THREE from 'three';

const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const damp = (rate, dt) => 1 - Math.exp(-rate * dt);
const R = 0.23;            // radio (m)
export const ORB_Y = 1.28; // altura del centro: más o menos donde queda la cabeza de un personaje

// color · eye: alto de los ojos (1 normal, <1 entornados, >1 muy abiertos) · brow: cejas (+ enfado, − pena)
// smile: boca (−1 triste … 1 sonrisa) · open: boca abierta sin hablar · look: [x, y] hacia dónde mira
// tilt: ladeo · lean: inclinación · bounce/shake/droop: salto, temblor, caída
const FEEL = {
  neutral:     { color: 0xb9a6ff, smile: 0.25 },
  feliz:       { color: 0xffd166, smile: 0.9, eye: 0.8, bounce: 0.3 },
  emocionada:  { color: 0xff9f43, smile: 1, eye: 1.15, open: 0.35, bounce: 1 },
  timida:      { color: 0xffb3c7, smile: 0.3, eye: 0.75, look: [-0.5, -0.5], tilt: 0.16, lean: 0.14 },
  sonrojada:   { color: 0xff8fab, smile: 0.45, eye: 0.7, look: [0.5, -0.4], tilt: -0.14 },
  triste:      { color: 0x6c8cff, smile: -0.9, eye: 0.7, brow: -0.5, look: [0, -0.6], lean: 0.2, droop: 1 },
  molesta:     { color: 0xff5a5a, smile: -0.5, eye: 0.7, brow: 0.6, lean: 0.08 },
  sorprendida: { color: 0x7ee0ff, smile: 0, eye: 1.35, open: 0.7, brow: -0.2, lean: -0.1 },
  pensativa:   { color: 0x9aa4c7, smile: 0.05, eye: 0.9, look: [0.6, 0.6], tilt: 0.14 },
  carinosa:    { color: 0xff9ecf, smile: 0.8, eye: 0.75, tilt: 0.12 },
  enamorada:   { color: 0xff6fa5, smile: 1, eye: 0.6, tilt: 0.16, bounce: 0.25 },
  nerviosa:    { color: 0xc8e06a, smile: -0.2, eye: 1.05, brow: -0.3, shake: 0.4, dart: 1 },
  asustada:    { color: 0xa9b7ff, smile: -0.6, eye: 1.4, open: 0.45, brow: -0.45, shake: 1, lean: -0.14 },
  confundida:  { color: 0x7fd1c7, smile: -0.1, eye: 1, brow: -0.15, tilt: 0.26, look: [0.3, 0.3] },
};
const KEYS = ['smile', 'eye', 'brow', 'open', 'tilt', 'lean', 'bounce', 'shake', 'droop', 'dart'];
const BASE = { smile: 0.25, eye: 1, brow: 0, open: 0, tilt: 0, lean: 0, bounce: 0, shake: 0, droop: 0, dart: 0 };

export class Orb {
  constructor() {
    this.group = new THREE.Group();          // posición en el mundo
    this.body = new THREE.Group();           // gira y se deforma (la «cabeza»)
    this.group.add(this.body);
    this.mat = new THREE.MeshStandardMaterial({ color: FEEL.neutral.color, roughness: 0.32, metalness: 0.05, emissive: FEEL.neutral.color, emissiveIntensity: 0.18 });
    this.body.add(new THREE.Mesh(new THREE.SphereGeometry(R, 56, 40), this.mat));

    const dark = new THREE.MeshBasicMaterial({ color: 0x2a2440 });
    const white = new THREE.MeshBasicMaterial({ color: 0xffffff });
    this.eyes = [-1, 1].map((s) => {
      const eye = new THREE.Group();
      eye.position.set(s * 0.082, 0.045, R * 0.93);
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.034, 24, 16), dark);
      ball.scale.set(1, 1.25, 0.35);
      const shine = new THREE.Mesh(new THREE.SphereGeometry(0.011, 12, 8), white);
      shine.position.set(0.012, 0.018, 0.012);
      eye.add(ball, shine);
      this.body.add(eye);
      return eye;
    });
    this.brows = [-1, 1].map((s) => {
      const brow = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.011, 0.01), dark);
      brow.position.set(s * 0.084, 0.115, R * 0.9);
      this.body.add(brow);
      return brow;
    });
    // Boca: un arco (sonrisa o pena) cuando está cerrada y un óvalo cuando se abre.
    this.arc = new THREE.Mesh(new THREE.TorusGeometry(0.045, 0.0075, 8, 24, Math.PI), dark);
    this.arc.position.set(0, -0.05, R * 0.95);
    this.open = new THREE.Mesh(new THREE.SphereGeometry(0.03, 24, 16), dark);
    this.open.position.set(0, -0.07, R * 0.94);
    this.body.add(this.arc, this.open);

    this.hands = [-1, 1].map((s) => {
      const hand = new THREE.Mesh(new THREE.SphereGeometry(0.052, 24, 16), this.mat);
      hand.userData.side = s;
      this.group.add(hand);
      return hand;
    });

    this.v = { ...BASE };
    this.look = [0, 0];
    this.color = new THREE.Color(FEEL.neutral.color);
    this.goal = new THREE.Color();
    this.blink = { next: 2, t: -1 };
    this.dart = { next: 1, x: 0, y: 0 };
    this.mouthOpen = 0;
    this._q = new THREE.Quaternion();
    this._e = new THREE.Euler();
    this._v = new THREE.Vector3();
    this._fwd = new THREE.Vector3();
    this._camDir = new THREE.Vector3();
  }

  // c: { t, dt, emotion, emoAge, state: {idle, listening, thinking, speaking}, voice, beat, gestures: [{name, t, dur}] }
  update(c) {
    const { t, dt } = c;
    const f = FEEL[c.emotion] || FEEL.neutral;
    for (const k of KEYS) this.v[k] = lerp(this.v[k], f[k] ?? BASE[k], damp(5, dt));
    const lk = f.look || [0, 0];
    this.goal.setHex(f.color);
    this.color.lerp(this.goal, damp(4, dt));
    this.mat.color.copy(this.color);
    this.mat.emissive.copy(this.color);
    const v = this.v, st = c.state;

    // Gestos: mueven la cabeza (giro) y las manos.
    let nod = 0, shakeHead = 0, hop = 0, bow = 0;
    const hand = [{ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }];           // desplazamiento de cada mano (izq. de quien mira, der.)
    for (const g of c.gestures) {
      const p = g.t / g.dur, w = Math.sin(clamp(p) * Math.PI);            // entra y sale suave
      const wave = Math.sin(g.t * Math.PI * 2 * 2.4);
      switch (g.name) {
        case 'asentir': nod += 0.3 * Math.max(0, Math.sin(g.t * 12)) * w; break;
        case 'negar': shakeHead += 0.4 * Math.sin(g.t * 13) * w; break;
        case 'saludar': hand[1].y += 0.34 * w; hand[1].x += (0.06 + 0.07 * wave) * w; break;
        case 'pensar': hand[1].x -= 0.2 * w; hand[1].y += 0.02 * w; hand[1].z += 0.2 * w; break;
        case 'risita': hand[1].x -= 0.24 * w; hand[1].y += 0.08 * w; hand[1].z += 0.2 * w; hop += 0.012 * Math.abs(Math.sin(g.t * 17)) * w; break;
        case 'encogerse': hand[0].y += 0.16 * w; hand[1].y += 0.16 * w; hand[0].x -= 0.08 * w; hand[1].x += 0.08 * w; break;
        case 'reverencia': bow += 0.55 * w; break;
        case 'celebrar': hand[0].y += 0.36 * w; hand[1].y += 0.36 * w; hop += 0.06 * Math.abs(Math.sin(g.t * 8)) * w; break;
        case 'pulgar': hand[1].y += 0.22 * w; hand[1].z += 0.15 * w; nod += 0.08 * w; break;
        case 'paz': hand[1].y += 0.3 * w; hand[1].x -= 0.12 * w; this.v.tilt += 0.03 * w; break;
        // Pasatiempos (17 nov 2026): la vuelta la da avatar.js (spinYaw); aquí, saltitos y balanceo.
        case '_bailar': case 'bailar': hop += 0.04 * Math.abs(Math.sin(g.t * 6.9)) * w; this.v.tilt += 0.05 * Math.sin(g.t * 3.4) * w; hand[0].y += 0.15 * w; hand[1].y += 0.15 * w; break;
        case '_saltar': case 'saltar': hop += 0.35 * Math.max(0, Math.sin(Math.PI * Math.min(1, Math.max(0, (g.t - 0.35) / 0.8)))) * w; break;
        case '_girar': case 'girar': hop += 0.03 * w; break;
        // Más pasatiempos (18 nov 2026)
        case '_sensual': case 'sensual': this.v.tilt += 0.07 * Math.sin(g.t * 3.5) * w; hop += 0.015 * Math.abs(Math.sin(g.t * 3.5)) * w; break;
        case '_posar': case 'posar': this.v.tilt += 0.06 * g.side * w; hand[0].y += 0.2 * w; break;
        case '_beso': case 'beso': hand[1].z += 0.2 * w; hand[1].y += 0.1 * w; break;
        case '_melena': case 'melena': this.v.tilt -= 0.05 * g.side * w; hand[1].y += 0.3 * w; break;
        case '_ninja': case 'ninja': hop += 0.42 * Math.max(0, Math.sin(Math.PI * Math.min(1, Math.max(0, (g.t - 0.55) / 1.1)))) * w; break;
        case '_zombi': case 'zombi': hand[0].z += 0.3 * w; hand[1].z += 0.3 * w; hand[0].y += 0.12 * w; hand[1].y += 0.12 * w; this.v.tilt += 0.06 * Math.sin(g.t * 1.7) * w; break;
        case '_llamar': case 'llamar': hand[1].y += 0.32 * w; hand[1].x += 0.06 * Math.sin(g.t * 7) * w; break;
        case '_boxear': case 'boxear': { const jab = Math.max(0, Math.sin(g.t * 9)); hop += 0.015 * Math.abs(Math.sin(g.t * 7.5)) * w; hand[0].z += 0.25 * jab * w; hand[1].z += 0.25 * (1 - jab) * w; break; }
        case '_concentrar': case 'concentrarse': hand[0].x += 0.15 * w; hand[1].x -= 0.15 * w; hand[0].z += 0.15 * w; hand[1].z += 0.15 * w; nod += 0.05 * w; break;
        case '_tararear': case 'tararear': this.v.tilt += 0.04 * Math.sin(g.t * 3.4) * w; break;
        case 'aplaudir': { const clap = 0.5 + 0.5 * Math.sin(g.t * 26); hand[0].x += (0.2 + 0.07 * clap) * w; hand[1].x -= (0.2 + 0.07 * clap) * w; hand[0].y += 0.1 * w; hand[1].y += 0.1 * w; hand[0].z += 0.16 * w; hand[1].z += 0.16 * w; break; }
        case '_mirar': shakeHead += 0.45 * g.side * w; break;
        case '_ladear': nod += 0; this.v.tilt += 0.02 * g.side * w; break;
        case '_hombros': hop += 0.02 * w; break;
        case '_toque': hop += 0.05 * Math.max(0, 1 - g.t * 3) * w; hand[0].y += 0.12 * w; hand[1].y += 0.12 * w; break;
        case '_aterrizar': hop -= 0.05 * Math.max(0, 1 - g.t / 0.75) * w; break;
        // Toques y miradas (16 nov 2026, avatar.js react / lookReact)
        case '_mimos': this.v.tilt += 0.03 * Math.sin(g.t * 3.2) * w; nod += 0.08 * w; break;
        case '_cubrir': hand[0].x += 0.16 * w; hand[1].x -= 0.16 * w; hand[0].y += 0.08 * w; hand[1].y += 0.08 * w; shakeHead -= 0.3 * w; break;
        case '_falda': hand[0].y -= 0.1 * w; hand[1].y -= 0.1 * w; hand[0].x += 0.08 * w; hand[1].x -= 0.08 * w; nod += 0.12 * w; break;
        case '_rechazo': hand[1].y += 0.2 * w; hand[1].z += 0.15 * w; hand[1].x += 0.08 * Math.sin(g.t * 11) * w; shakeHead += 0.3 * Math.sin(g.t * 9) * w; break;
        case '_pisoton': hop -= 0.04 * Math.max(0, Math.sin(g.t * 6)) * w; break;
        case '_cosquillas': hop += 0.02 * Math.abs(Math.sin(g.t * 14)) * w; shakeHead += 0.15 * Math.sin(g.t * 14) * w; break;
        case '_saltito': hop += 0.07 * Math.max(0, Math.sin(Math.min(1, g.t / 0.5) * Math.PI)) * w; break;
        case '_mirar_mano': shakeHead += 0.35 * g.side * w; break;
        // Piedra, papel o tijera (N-08)
        case '_rps_piedra': case '_rps_papel': case '_rps_tijera': {
          const swing = g.t < 1.2 ? Math.abs(Math.sin(g.t * Math.PI * 2.5)) * 0.18 : 0;
          const show = g.t >= 1.2 ? 1 : 0;
          hand[1].y += (0.14 + swing + 0.14 * show) * w;
          hand[1].z += (0.12 + 0.14 * show) * w;
          if (show && g.name === '_rps_papel') hand[1].x += 0.06 * w;
          if (show && g.name === '_rps_tijera') this.v.tilt += 0.05 * w;
          hop += 0.02 * swing * w;
          break;
        }
      }
    }
    // Mascota de escritorio (modo flotante): andar, en brazos, cayendo, sentada, trabajando (avatar.js ACTIVITIES).
    const a = c.act || { w: {}, work: {} }, aw = a.w;
    if (aw.walk) hop += 0.035 * Math.abs(Math.sin(a.walkPhase)) * aw.walk;
    if (aw.carried) { const k = aw.carried; hand[0].y += 0.22 * k; hand[1].y += 0.22 * k; hand[0].x -= 0.05 * k; hand[1].x += 0.05 * k; nod += 0.08 * Math.sin(t * 2.3) * k; }
    if (aw.fall) { const k = aw.fall; hand[0].y += 0.3 * k; hand[1].y += 0.3 * k; hand[0].x -= 0.12 * k; hand[1].x += 0.12 * k; }
    if (aw.sit) { hop -= 0.04 * aw.sit; hand[0].y -= 0.08 * aw.sit; hand[1].y -= 0.08 * aw.sit; }
    if (aw.work) {
      const k = aw.work, typing = (a.work.type || 0) * k, clicking = Math.max(a.work.click || 0, a.work.scroll || 0) * k;
      for (const i of [0, 1]) { hand[i].z += 0.2 * k; hand[i].y += 0.05 * k + 0.03 * typing * Math.max(0, Math.sin(t * 15 + i * 2.5)); }
      hand[1].y += 0.12 * clicking; hand[1].z += 0.08 * clicking * Math.max(0, Math.sin(t * 6));
      bow += 0.12 * k;
    }

    // Cuerpo: flota, respira, salta con la emoción, con la voz y con el pulso musical (music.js).
    const voice = c.voice * st.speaking;
    const mBeat = (c.musicBeat || 0) * (1 - st.speaking);
    const bounce = Math.abs(Math.sin(t * 5.2)) * 0.03 * v.bounce + 0.022 * mBeat;
    const jolt = Math.max(0, 1 - c.emoAge * 2.5) * (c.emotion === 'sorprendida' || c.emotion === 'asustada' ? 0.06 : 0);
    const shake = v.shake * 0.006;
    this.group.position.set(shake * Math.sin(t * 47), ORB_Y + 0.018 * Math.sin(t * 1.3) + bounce + hop + jolt - 0.05 * v.droop + 0.012 * c.beat, shake * Math.sin(t * 41));
    const breath = 1 + 0.012 * Math.sin(t * 1.5);
    const squash = 1 + 0.05 * voice * Math.sin(t * 9) + 0.035 * c.beat + 0.02 * mBeat - 0.04 * v.droop;
    this.body.scale.set(breath / Math.sqrt(squash), breath * squash, breath / Math.sqrt(squash));
    this._e.set(
      v.lean + bow + nod + 0.05 * st.listening - 0.1 * st.thinking - 0.05 * voice + 0.03 * Math.sin(t * 0.9),
      shakeHead + 0.16 * st.thinking + 0.08 * Math.sin(t * 0.33) + 0.07 * voice * Math.sin(t * 1.7) - 0.25 * this.look[0],
      v.tilt + 0.07 * st.listening + 0.04 * Math.sin(t * 0.51), 'XYZ');
    this._q.setFromEuler(this._e);
    this.body.quaternion.slerp(this._q, damp(12, dt));

    // Ojos: parpadeo, apertura según la emoción y mirada.
    // Parpadeo como uno de verdad: cierra rápido, se queda un instante y abre más despacio.
    const b = this.blink;
    if (b.t < 0 && t > b.next) b.t = 0;
    let blink = 0;
    if (b.t >= 0) {
      b.t += dt;
      blink = b.t < 0.065 ? b.t / 0.065 : b.t < 0.095 ? 1 : 1 - clamp((b.t - 0.095) / 0.13);
      if (b.t >= 0.225) { b.t = -1; b.next = t + 2 + Math.random() * 4; }
    }
    const d = this.dart;
    if (t > d.next) {
      const far = Math.random() < 0.2 + 0.6 * v.dart;
      d.x = (Math.random() - 0.5) * (far ? 1.2 : 0.2); d.y = (Math.random() - 0.5) * (far ? 0.6 : 0.1);
      d.next = t + (0.6 + Math.random() * 2.2) / (1 + 2 * v.dart);
      if (far && b.t < 0 && Math.random() < 0.45) b.next = t;       // un desvío grande suele llevar parpadeo
    }
    this.look[0] = lerp(this.look[0], lk[0] + d.x + 0.6 * st.thinking, damp(8, dt));
    this.look[1] = lerp(this.look[1], lk[1] + d.y + 0.6 * st.thinking, damp(8, dt));
    const happy = clamp(v.smile - 0.55) * 1.6;                              // muy contenta: ojos en arco (más bajos)
    this.eyes.forEach((eye, i) => {
      const s = i ? 1 : -1;
      eye.position.set(s * 0.082 + 0.016 * this.look[0], 0.045 + 0.014 * this.look[1], R * 0.93);
      eye.scale.set(1 + 0.12 * happy, Math.max(0.08, v.eye * (1 - 0.92 * blink) * (1 - 0.45 * happy)), 1);
      this.brows[i].position.y = 0.115 + 0.02 * (v.eye - 1) - 0.012 * Math.abs(v.brow);
      this.brows[i].rotation.z = -s * v.brow * 0.75;
    });

    // Boca: el arco se curva hacia arriba o abajo; al hablar se modula el ancho/alto según las vocales (a/e/i/o/u).
    const vis = c.visemes || {};
    const closeK = st.speaking > 0.2 ? 1 - 0.85 * (vis.close || 0) : 1;
    const open = clamp(Math.max(v.open, c.mouth * 1.9 * st.speaking * closeK));
    this.mouthOpen = lerp(this.mouthOpen, open, damp(open > this.mouthOpen ? 28 : 14, dt));
    const o = this.mouthOpen;
    const wide = (vis.ee || 0) * 0.35 + (vis.ih || 0) * 0.28 - (vis.ou || 0) * 0.38 - (vis.oh || 0) * 0.22;
    const tall = (vis.aa || 0) * 0.25 + (vis.oh || 0) * 0.22 + (vis.ou || 0) * 0.15 - (vis.ee || 0) * 0.18;
    this.open.visible = o > 0.04;
    this.open.scale.set(Math.max(0.45, 0.9 + 0.5 * o + wide * st.speaking), Math.max(0.18, 0.25 + 1.25 * o + tall * o), 0.3);
    this.arc.visible = o < 0.35;
    const curve = v.smile;                                                  // torus: media circunferencia hacia arriba; se gira para sonreír
    this.arc.rotation.z = curve >= 0 ? Math.PI : 0;
    this.arc.scale.set(1, Math.max(0.12, Math.abs(curve)), 1);
    this.arc.position.y = -0.055 + (curve >= 0 ? 0.012 : -0.03) * Math.abs(curve);

    // Manos: flotan a los lados, acompañan la voz y hacen los gestos.
    this.hands.forEach((h, i) => {
      const s = h.userData.side;
      const talk = st.speaking * (0.04 + 0.1 * c.voice) * (0.5 + 0.5 * Math.sin(t * 2.3 + i * 2.1));
      const shy = (c.emotion === 'timida' || c.emotion === 'nerviosa' || c.emotion === 'enamorada') ? 1 : 0;
      const scared = c.emotion === 'asustada' ? 1 : 0;
      this._v.set(
        s * (0.31 - 0.17 * shy - 0.12 * scared) + hand[i].x,
        -0.13 + 0.02 * Math.sin(t * 1.3 + i * 1.7) + talk + 0.06 * c.beat + 0.1 * scared + 0.03 * shy - 0.06 * v.droop + hand[i].y,   // relativo al cuerpo
        0.06 + 0.14 * shy + 0.14 * scared + 0.05 * st.speaking + hand[i].z);
      // Las manos van como un muelle: llegan con un poco de inercia y rebote, no a velocidad fija.
      const vel = h.userData.vel || (h.userData.vel = new THREE.Vector3());
      const w = 11, z = 0.62;
      vel.addScaledVector(this._v.sub(h.position), w * w * dt).multiplyScalar(Math.max(0, 1 - 2 * z * w * dt));
      h.position.addScaledVector(vel, dt);
    });
  }

  // Dónde está la cara, para los efectos (rubor, corazones…).
  head(camera, out) {
    this.body.updateWorldMatrix(true, false);
    const q = this.body.getWorldQuaternion(this._q);
    const pos = this.body.getWorldPosition(this._v);
    out.unit = 0.15;
    out.eyes.set(0, 0.03, R * 0.9).applyQuaternion(q).add(pos);
    out.cheeks[0].set(0.125, -0.02, R * 0.9).applyQuaternion(q).add(pos);
    out.cheeks[1].set(-0.125, -0.02, R * 0.9).applyQuaternion(q).add(pos);
    const fwd = this._fwd.set(0, 0, 1).applyQuaternion(q);
    out.facing = clamp(fwd.dot(this._camDir.copy(camera.position).sub(out.eyes).normalize()) * 2.2 - 0.5);
    return out;
  }

  dispose() {
    this.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    this.mat.dispose();
  }
}
