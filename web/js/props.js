// Objetos que el personaje tiene en la mano (17 nov 2026): una tablet o un móvil para mirar cosas recostada hasta
// que se duerme. Se dibujan aquí (sin archivos): un marco oscuro con la pantalla encendida, que va cambiando como si
// viera un vídeo. avatar.js los coloca cada cuadro entre las manos, mirando a su cara.
import * as THREE from 'three';

const KINDS = {
  tablet: { w: 0.2, h: 0.14, d: 0.008, bezel: 0.008 },
  phone: { w: 0.072, h: 0.15, d: 0.008, bezel: 0.004 },
};

export class Device {
  constructor(kind = 'tablet') {
    const k = KINDS[kind] || KINDS.tablet;
    this.kind = kind;
    this.group = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(k.w, k.h, k.d),
      new THREE.MeshStandardMaterial({ color: 0x1d1b26, roughness: 0.45, metalness: 0.3 }));
    this.canvas = document.createElement('canvas');
    this.canvas.width = 128; this.canvas.height = Math.round(128 * (k.h - 2 * k.bezel) / (k.w - 2 * k.bezel));
    this.tex = new THREE.CanvasTexture(this.canvas);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(k.w - 2 * k.bezel, k.h - 2 * k.bezel),
      new THREE.MeshBasicMaterial({ map: this.tex, toneMapped: false }));
    screen.position.z = k.d / 2 + 0.0005;
    this.screen = screen;
    this.group.add(body, screen);
    this.group.visible = false;
    this.scale = 1;
    this.on = 1;                              // pantalla encendida (se apaga al dormirse)
    this._next = 0;
    this._hue = Math.random() * 360;
  }

  // Lo que se ve en la pantalla: colores que cambian y formas que se mueven (un vídeo cualquiera).
  update(t) {
    if (!this.group.visible || t < this._next) return;
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
      g.fillStyle = `rgba(255,255,255,${0.8 * on})`;                     // barra de progreso del «vídeo»
      g.fillRect(W * 0.08, H * 0.9, W * 0.84 * ((t * 0.02) % 1), H * 0.025);
    }
    this.tex.needsUpdate = true;
  }

  dispose() {
    this.group.removeFromParent();
    this.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    this.tex.dispose();
  }
}
