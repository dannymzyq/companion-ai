// Objetos y accesorios 3D procedurales (sin archivos externos): tablet y móvil para los pasatiempos,
// taza humeante para «beber», y accesorios de personaje (gafas, auriculares, gorrito de dormir, taza).
import * as THREE from 'three';

const KINDS = {
  tablet: { w: 0.2, h: 0.14, d: 0.008, bezel: 0.008 },
  phone: { w: 0.072, h: 0.15, d: 0.008, bezel: 0.004 },
};

export const ACCESSORY_LIST = [
  { id: 'glasses', name: 'Gafas finas' },
  { id: 'headphones', name: 'Auriculares' },
  { id: 'mug', name: 'Taza caliente' },
  { id: 'sleepcap', name: 'Gorrito nocturno' },
];

export class Device {
  constructor(kind = 'tablet') {
    this.kind = kind;
    this.group = new THREE.Group();
    this.scale = 1;
    this.on = 1;
    this._next = 0;
    this._hue = Math.random() * 360;

    if (kind === 'mug') {
      const ceramic = new THREE.MeshStandardMaterial({ color: 0xf4efe6, roughness: 0.35, metalness: 0.05 });
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.038, 0.032, 0.082, 20, 1, false), ceramic);
      const tea = new THREE.Mesh(
        new THREE.CircleGeometry(0.033, 18),
        new THREE.MeshStandardMaterial({ color: 0x5c361e, roughness: 0.2 }),
      );
      tea.rotation.x = -Math.PI / 2;
      tea.position.y = 0.036;
      const handle = new THREE.Mesh(new THREE.TorusGeometry(0.022, 0.0055, 10, 18, Math.PI * 1.15), ceramic);
      handle.rotation.z = -Math.PI / 2;
      handle.position.set(0.038, 0.002, 0);
      this.group.add(cup, tea, handle);
      this.group.visible = false;
      this.canvas = null;
      this.tex = null;
      return;
    }

    const k = KINDS[kind] || KINDS.tablet;
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(k.w, k.h, k.d),
      new THREE.MeshStandardMaterial({ color: 0x1d1b26, roughness: 0.45, metalness: 0.3 }),
    );
    this.canvas = document.createElement('canvas');
    this.canvas.width = 128;
    this.canvas.height = Math.round(128 * (k.h - 2 * k.bezel) / (k.w - 2 * k.bezel));
    this.tex = new THREE.CanvasTexture(this.canvas);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    const screen = new THREE.Mesh(
      new THREE.PlaneGeometry(k.w - 2 * k.bezel, k.h - 2 * k.bezel),
      new THREE.MeshBasicMaterial({ map: this.tex, toneMapped: false }),
    );
    screen.position.z = k.d / 2 + 0.0005;
    this.screen = screen;
    this.group.add(body, screen);
    this.group.visible = false;
  }

  update(t) {
    if (!this.group.visible || !this.canvas || t < this._next) return;
    this._next = t + 0.12;
    const g = this.canvas.getContext('2d'), W = this.canvas.width, H = this.canvas.height;
    const on = this.on;
    this._hue = (this._hue + 3) % 360;
    const grad = g.createLinearGradient(0, 0, W, H);
    grad.addColorStop(0, `hsl(${this._hue}, 60%, ${12 + 40 * on}%)`);
    grad.addColorStop(1, `hsl(${(this._hue + 70) % 360}, 65%, ${8 + 30 * on}%)`);
    g.fillStyle = grad;
    g.fillRect(0, 0, W, H);
    if (on > 0.2) {
      for (let i = 0; i < 4; i++) {
        const x = W * (0.5 + 0.38 * Math.sin(t * (0.6 + i * 0.23) + i * 2));
        const y = H * (0.5 + 0.35 * Math.cos(t * (0.5 + i * 0.17) + i));
        g.fillStyle = `hsla(${(this._hue + i * 50) % 360}, 80%, 70%, ${0.35 * on})`;
        g.beginPath(); g.arc(x, y, W * (0.12 + 0.05 * i), 0, Math.PI * 2); g.fill();
      }
      g.fillStyle = `rgba(255,255,255,${0.8 * on})`;
      g.fillRect(W * 0.08, H * 0.9, W * 0.84 * ((t * 0.02) % 1), H * 0.025);
    }
    this.tex.needsUpdate = true;
  }

  dispose() {
    this.group.removeFromParent();
    this.group.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        if (Array.isArray(o.material)) o.material.forEach((m) => m.dispose());
        else o.material.dispose();
      }
    });
    if (this.tex) this.tex.dispose();
  }
}

// Crea un accesorio 3D acoplable al hueso de la cabeza o de la mano derecha (coordenadas en unidades de cara `unit`).
export function createAccessory(kind) {
  const group = new THREE.Group();
  let target = 'head';

  if (kind === 'glasses') {
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x262630, roughness: 0.28, metalness: 0.78 });
    const glassMat = new THREE.MeshBasicMaterial({ color: 0xaad8ff, transparent: true, opacity: 0.16, depthWrite: false });
    for (const s of [-1, 1]) {
      const rim = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.018, 10, 28), frameMat);
      rim.scale.set(1.12, 0.88, 1);
      rim.position.set(s * 0.28, 0, 0);
      const lens = new THREE.Mesh(new THREE.CircleGeometry(0.21, 24), glassMat);
      lens.scale.set(1.12, 0.88, 1);
      lens.position.set(s * 0.28, 0, 0.002);
      const temple = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.62, 8), frameMat);
      temple.rotation.x = Math.PI / 2;
      temple.position.set(s * 0.52, 0.02, -0.31);
      group.add(rim, lens, temple);
    }
    const bridge = new THREE.Mesh(new THREE.TorusGeometry(0.075, 0.015, 8, 14, Math.PI), frameMat);
    bridge.position.set(0, 0.02, 0.01);
    group.add(bridge);
    group.userData.anchor = 'eyes';
  } else if (kind === 'headphones') {
    const bandMat = new THREE.MeshStandardMaterial({ color: 0x242533, roughness: 0.4, metalness: 0.45 });
    const padMat = new THREE.MeshStandardMaterial({ color: 0x15161f, roughness: 0.8, metalness: 0.05 });
    const glowMat = new THREE.MeshBasicMaterial({ color: 0x5ac8fa });
    const band = new THREE.Mesh(new THREE.TorusGeometry(0.76, 0.048, 12, 32, Math.PI * 1.06), bandMat);
    band.rotation.z = -0.03 * Math.PI;
    band.position.set(0, 0.16, -0.04);
    group.add(band);
    for (const s of [-1, 1]) {
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.2, 0.14, 22), bandMat);
      cup.rotation.z = Math.PI / 2;
      cup.position.set(s * 0.77, 0.02, -0.04);
      const pad = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.055, 10, 22), padMat);
      pad.rotation.y = Math.PI / 2;
      pad.position.set(s * 0.70, 0.02, -0.04);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.012, 8, 22), glowMat);
      ring.rotation.y = Math.PI / 2;
      ring.position.set(s * 0.84, 0.02, -0.04);
      group.add(cup, pad, ring);
    }
    group.userData.anchor = 'center';
  } else if (kind === 'sleepcap') {
    const clothMat = new THREE.MeshStandardMaterial({ color: 0x6f7bf7, roughness: 0.82, metalness: 0.02 });
    const whiteMat = new THREE.MeshStandardMaterial({ color: 0xf7f7fb, roughness: 0.9, metalness: 0.0 });
    const brim = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.095, 12, 28), whiteMat);
    brim.rotation.x = Math.PI / 2 - 0.18;
    brim.position.set(0, 0.56, -0.04);
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.6, 0.95, 24), clothMat);
    cone.position.set(0.12, 0.96, -0.1);
    cone.rotation.z = -0.38;
    cone.rotation.x = -0.15;
    const pom = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 12), whiteMat);
    pom.position.set(0.34, 1.36, -0.18);
    group.add(brim, cone, pom);
    group.userData.anchor = 'center';
  } else if (kind === 'mug') {
    target = 'rightHand';
    const d = new Device('mug');
    d.group.visible = true;
    group.add(d.group);
    group.userData.anchor = 'hand';
  } else {
    return null;
  }

  const seenMats = new Set();
  return {
    kind,
    target,
    group,
    dispose() {
      group.removeFromParent();
      group.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          const list = Array.isArray(o.material) ? o.material : [o.material];
          for (const m of list) { if (!seenMats.has(m)) { seenMats.add(m); m.dispose(); } }
        }
      });
    },
  };
}
