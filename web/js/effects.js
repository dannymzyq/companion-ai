// Lo que se ve de los sentimientos de Mika además de su cara: rubor en las mejillas, corazones, gotas de
// sudor, signos de sorpresa o de duda, destellos, la marca de enfado… al estilo del anime.
// Son carteles pequeños (sprites) dibujados aquí mismo, sin archivos de imagen, y colocados alrededor de la
// cabeza del modelo; por eso funcionan con cualquier VRM, traiga o no sus propias expresiones.

import * as THREE from 'three';

const SIZE = 128;
const rand = (a, b) => a + Math.random() * (b - a);
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));

function texture(draw) {
  const c = document.createElement('canvas');
  c.width = c.height = SIZE;
  const g = c.getContext('2d');
  g.lineJoin = g.lineCap = 'round';
  draw(g);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function heart(g, cx, cy, s) {
  g.beginPath();
  g.moveTo(cx, cy + s * 0.9);
  g.bezierCurveTo(cx - s * 1.5, cy - s * 0.1, cx - s * 0.8, cy - s * 1.15, cx, cy - s * 0.35);
  g.bezierCurveTo(cx + s * 0.8, cy - s * 1.15, cx + s * 1.5, cy - s * 0.1, cx, cy + s * 0.9);
  g.closePath();
}

function glyph(g, text, fill, stroke, size = 104) {
  g.font = `900 ${size}px "Segoe UI", Arial, sans-serif`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.lineWidth = 14;
  g.strokeStyle = stroke;
  g.strokeText(text, 64, 70);
  g.fillStyle = fill;
  g.fillText(text, 64, 70);
}

const DRAW = {
  heart(g) {
    heart(g, 64, 62, 40);
    g.lineWidth = 9; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#ff4f8b'; g.fill();
    g.beginPath(); g.ellipse(46, 46, 9, 6, -0.6, 0, 7); g.fillStyle = 'rgba(255,255,255,.75)'; g.fill();
  },
  drop(g) {                                   // gota de sudor
    g.beginPath();
    g.moveTo(64, 12);
    g.bezierCurveTo(64, 40, 98, 62, 98, 86);
    g.arc(64, 86, 34, 0, Math.PI);
    g.bezierCurveTo(30, 62, 64, 40, 64, 12);
    g.closePath();
    g.lineWidth = 8; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#8fd3ff'; g.fill();
    g.beginPath(); g.ellipse(50, 84, 7, 13, 0.3, 0, 7); g.fillStyle = 'rgba(255,255,255,.8)'; g.fill();
  },
  tear(g) {
    g.beginPath();
    g.moveTo(64, 20);
    g.bezierCurveTo(64, 48, 90, 66, 90, 86);
    g.arc(64, 86, 26, 0, Math.PI);
    g.bezierCurveTo(38, 66, 64, 48, 64, 20);
    g.closePath();
    g.fillStyle = 'rgba(150,215,255,.95)'; g.fill();
    g.lineWidth = 5; g.strokeStyle = 'rgba(255,255,255,.9)'; g.stroke();
  },
  spark(g) {                                  // destello de cuatro puntas
    g.beginPath();
    for (let i = 0; i < 8; i++) {
      const r = i % 2 ? 13 : 56, a = (i * Math.PI) / 4 - Math.PI / 2;
      g.lineTo(64 + r * Math.cos(a), 64 + r * Math.sin(a));
    }
    g.closePath();
    g.lineWidth = 7; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#ffe066'; g.fill();
  },
  anger(g) {                                  // la «vena» de enfado
    g.lineWidth = 22; g.strokeStyle = '#fff';
    const arcs = [[38, 38, 0], [90, 38, 0.5], [90, 90, 1], [38, 90, 1.5]];
    for (const pass of [['#fff', 24], ['#ff3b3b', 13]]) {
      g.strokeStyle = pass[0]; g.lineWidth = pass[1];
      for (const [x, y, a] of arcs) { g.beginPath(); g.arc(x, y, 22, a * Math.PI, (a + 0.5) * Math.PI); g.stroke(); }
    }
  },
  exclaim(g) { glyph(g, '!', '#ffd23f', '#fff'); },
  question(g) { glyph(g, '?', '#7cc4ff', '#fff'); },
  dots(g) {                                   // puntos suspensivos
    for (const x of [28, 64, 100]) {
      g.beginPath(); g.arc(x, 64, 13, 0, 7);
      g.lineWidth = 7; g.strokeStyle = '#fff'; g.stroke();
      g.fillStyle = '#b9b4d6'; g.fill();
    }
  },
  gloom(g) {                                  // rayas de desánimo o de susto
    g.strokeStyle = 'rgba(96,108,180,.9)'; g.lineWidth = 9;
    [[26, 96], [48, 112], [70, 88], [92, 108]].forEach(([x, len]) => { g.beginPath(); g.moveTo(x, 10); g.lineTo(x, len); g.stroke(); });
  },
  blush(g) {                                  // rubor: mancha suave y tres trazos diagonales
    const r = g.createRadialGradient(64, 64, 4, 64, 64, 60);
    r.addColorStop(0, 'rgba(255,105,130,.78)');
    r.addColorStop(0.55, 'rgba(255,105,130,.4)');
    r.addColorStop(1, 'rgba(255,105,130,0)');
    g.save(); g.translate(64, 64); g.scale(1, 0.58); g.translate(-64, -64);
    g.fillStyle = r; g.fillRect(0, 0, SIZE, SIZE);
    g.restore();
    g.strokeStyle = 'rgba(232,60,96,.7)'; g.lineWidth = 6;
    for (const x of [44, 64, 84]) { g.beginPath(); g.moveTo(x + 9, 50); g.lineTo(x - 9, 78); g.stroke(); }
  },
};

// Qué efectos acompañan a cada emoción.
//   burst: lo que salta en el momento de sentirla · stream: lo que sigue saliendo mientras dura (cada `every` s)
//   hold: un signo que se queda junto a la cabeza · blush: intensidad del rubor (0..1)
export const FEELINGS = {
  neutral: {},
  feliz: { burst: ['spark', 2] },
  emocionada: { burst: ['spark', 4], stream: ['spark', 0.55] },
  timida: { blush: 0.7 },
  sonrojada: { blush: 1 },
  triste: { hold: 'gloom', stream: ['tear', 2.6] },
  molesta: { hold: 'anger' },
  sorprendida: { burst: ['exclaim', 2] },
  pensativa: { hold: 'dots' },
  carinosa: { blush: 0.4, burst: ['heart', 1], stream: ['heart', 2.4] },
  enamorada: { blush: 0.85, burst: ['heart', 4], stream: ['heart', 0.5] },
  nerviosa: { blush: 0.3, stream: ['drop', 1.5] },
  asustada: { hold: 'gloom', burst: ['exclaim', 3], stream: ['drop', 1.1] },
  confundida: { burst: ['question', 2], stream: ['question', 2.2] },
};

export class Effects {
  constructor(scene, camera) {
    this.scene = scene;
    this.camera = camera;
    this.tex = {};
    for (const k in DRAW) this.tex[k] = texture(DRAW[k]);
    this.group = new THREE.Group();
    this.group.renderOrder = 20;
    scene.add(this.group);
    this.parts = [];                        // partículas vivas
    this.blush = [this._sprite('blush'), this._sprite('blush')];
    this.blushW = 0;
    this.hold = this._sprite('dots');
    this.holdKind = null;
    this.holdW = 0;
    this.feeling = 'neutral';
    this.age = 0;                           // segundos sintiendo lo actual
    this.nextStream = 0;
    this._r = new THREE.Vector3();
    this._u = new THREE.Vector3();
    this._p = new THREE.Vector3();
  }

  _sprite(kind) {
    const m = new THREE.SpriteMaterial({ map: this.tex[kind], transparent: true, depthTest: false, depthWrite: false, opacity: 0 });
    const s = new THREE.Sprite(m);
    s.renderOrder = 20;
    s.visible = false;
    this.group.add(s);
    return s;
  }

  setFeeling(name) {
    if (!(name in FEELINGS) || name === this.feeling) return;
    this.feeling = name;
    this.age = 0;
    this.nextStream = 0.5;
    const f = FEELINGS[name];
    if (f.burst) for (let i = 0; i < f.burst[1]; i++) this._spawn(f.burst[0], i * 0.09, true);
  }

  // Una partícula: nace junto a la cabeza y sube (o cae, si es una gota o una lágrima) mientras se desvanece.
  _spawn(kind, delay = 0, burst = false) {
    const falls = kind === 'drop' || kind === 'tear';
    const side = Math.random() < 0.5 ? -1 : 1;
    const p = {
      sprite: this._sprite(kind), kind, age: -delay, falls,
      life: falls ? 1.5 : kind === 'spark' ? 0.9 : kind === 'exclaim' || kind === 'question' ? 1.3 : 1.9,
      // posición en «cabezas»: x a los lados, y hacia arriba desde la altura de los ojos
      x: kind === 'tear' ? side * 0.36 : falls ? side * rand(0.78, 0.95) : kind === 'exclaim' || kind === 'question' ? side * rand(0.55, 1.0) : rand(-1.15, 1.15),
      y: kind === 'tear' ? -0.25 : falls ? rand(0.75, 1.0) : kind === 'exclaim' || kind === 'question' ? rand(1.2, 1.6) : rand(0.5, 1.5),
      vx: falls ? 0 : rand(-0.12, 0.12), vy: falls ? (kind === 'tear' ? -0.55 : -0.42) : kind === 'spark' ? rand(0.1, 0.4) : rand(0.35, 0.6),
      size: kind === 'tear' ? 0.26 : falls ? 0.42 : kind === 'spark' ? rand(0.3, 0.5) : kind === 'heart' ? rand(0.36, 0.56) : 0.62,
      spin: kind === 'spark' ? rand(-2.5, 2.5) : kind === 'heart' ? rand(-0.4, 0.4) : 0,
      wobble: rand(0, 6.28), pop: burst || kind === 'exclaim' || kind === 'question',
    };
    this.parts.push(p);
  }

  // head: { eyes: Vector3 (punto entre los ojos), top, unit (alto de la cara, m), facing (0..1), cheeks: [Vector3, Vector3] }
  update(dt, head) {
    const f = FEELINGS[this.feeling] || {};
    this.age += dt;
    if (f.stream && this.age >= this.nextStream && head) {
      this._spawn(f.stream[0]);
      this.nextStream = this.age + f.stream[1] * rand(0.75, 1.3);
    }
    if (!head) return;
    const cam = this.camera;
    this._r.setFromMatrixColumn(cam.matrixWorld, 0);      // derecha y arriba de la cámara: los signos siempre de frente
    this._u.setFromMatrixColumn(cam.matrixWorld, 1);
    const k = head.unit;

    for (const p of this.parts) {
      p.age += dt;
      if (p.age < 0) continue;
      const a = p.age / p.life;
      p.x += p.vx * dt; p.y += p.vy * dt;
      const sway = p.falls ? 0 : 0.05 * Math.sin(p.wobble + p.age * 3);
      this._p.copy(head.eyes).addScaledVector(this._r, (p.x + sway) * k).addScaledVector(this._u, p.y * k);
      p.sprite.position.copy(this._p);
      const grow = p.pop ? 1 + 0.5 * Math.max(0, 1 - a * 6) : Math.min(1, a * 7 + 0.3);     // los signos «saltan»; el resto aparece suave
      p.sprite.scale.setScalar(p.size * k * grow);
      p.sprite.material.rotation = p.spin * p.age;
      p.sprite.material.opacity = clamp(a * 8) * clamp((1 - a) * 3);
      p.sprite.visible = true;
    }
    this.parts = this.parts.filter((p) => {
      if (p.age < p.life) return true;
      this.group.remove(p.sprite);
      p.sprite.material.dispose();
      return false;
    });

    // Rubor: sobre cada mejilla, solo cuando se le ve la cara.
    this.blushW += ((f.blush || 0) * head.facing - this.blushW) * Math.min(1, dt * 4);
    this.blush.forEach((s, i) => {
      s.visible = this.blushW > 0.01;
      s.position.copy(head.cheeks[i]);
      s.scale.set(0.5 * k, 0.5 * k, 1);
      s.material.opacity = this.blushW;
    });

    // Signo fijo (puntos suspensivos, marca de enfado, rayas): flota junto a la cabeza.
    if (f.hold && f.hold !== this.holdKind && this.holdW < 0.05) {
      this.holdKind = f.hold;
      this.hold.material.map = this.tex[f.hold];
      this.hold.material.needsUpdate = true;
    }
    const want = f.hold && f.hold === this.holdKind ? 1 : 0;
    this.holdW += (want - this.holdW) * Math.min(1, dt * 6);
    if (!want && this.holdW < 0.03) this.holdKind = null;
    this.hold.visible = this.holdW > 0.02;
    if (this.hold.visible) {
      const kind = this.holdKind, t = this.age;
      const [ox, oy, size] = kind === 'anger' ? [0.72, 1.05, 0.5] : kind === 'gloom' ? [-0.55, 1.2, 0.62] : [0.9, 1.35, 0.6];
      const pulse = kind === 'anger' ? 1 + 0.14 * Math.sin(t * 9) : 1;
      const bob = kind === 'dots' ? 0.05 * Math.sin(t * 2.2) : 0;
      this.hold.position.copy(head.eyes).addScaledVector(this._r, ox * k).addScaledVector(this._u, (oy + bob) * k);
      this.hold.scale.setScalar(size * k * pulse);
      this.hold.material.opacity = this.holdW;
    }
  }

  clear() {
    for (const p of this.parts) { this.group.remove(p.sprite); p.sprite.material.dispose(); }
    this.parts = [];
    this.blushW = this.holdW = 0;
    this.blush.forEach((s) => (s.visible = false));
    this.hold.visible = false;
  }
}
