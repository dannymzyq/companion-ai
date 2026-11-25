// Qué sonido se está diciendo, para la forma de la boca (17 nov 2026). Adaptado de wawa-lipsync 0.0.2
// (https://github.com/wass08/wawa-lipsync, MIT, © Wawa Sensei) y recalibrado para voz PCM a 24 kHz en español:
// mira 7 bandas de formantes y el centroide del espectro (audio.js) y puntúa vocales (a/e/i/o/u), oclusivas
// (p/t/k/n) y fricativas/vibrantes (f/z/s/ch/rr) sin reservar objetos en cada fotograma.
const VOWEL = { aa: 'aa', E: 'ee', I: 'ih', O: 'oh', U: 'ou' };
const PLOSIVE = ['PP', 'DD', 'kk', 'nn'];
const FRICATIVE = ['FF', 'TH', 'SS', 'CH', 'RR'];
const ALL = ['sil', ...PLOSIVE, ...FRICATIVE, ...Object.keys(VOWEL)];
const KIND = Object.fromEntries(ALL.map((v) => [v, v === 'sil' ? 'silence' : PLOSIVE.includes(v) ? 'plosive' : FRICATIVE.includes(v) ? 'fricative' : 'vowel']));

export class Lipsync {
  constructor(historySize = 8) {
    this.size = historySize;
    this.ring = Array.from({ length: historySize }, () => ({ volume: 0, centroid: 0, bands: new Float32Array(7) }));
    this.head = 0;
    this.count = 0;
    this.viseme = 'sil';
    this.since = 0;
    this.maxMs = 260;
    this._sc = Object.fromEntries(ALL.map((v) => [v, 0]));
    this._avgBands = new Float32Array(7);
    this.out = { aa: 0, ee: 0, ih: 0, oh: 0, ou: 0, close: 0, kind: 'silence' };
  }

  // bands: 7 valores 0..1 (audio.js, LIP_BANDS); centroid en Hz; now en ms.
  update(bands, centroid, now) {
    const out = this.out;
    if (!bands) {
      out.aa = out.ee = out.ih = out.oh = out.ou = out.close = 0;
      out.kind = 'silence';
      return out;
    }
    let curVol = 0;
    for (let i = 0; i < 7; i++) curVol += bands[i];
    curVol /= 7;

    if (curVol > 0) {
      const slot = this.ring[this.head];
      slot.volume = curVol;
      slot.centroid = centroid;
      slot.bands.set(bands);
      this.head = (this.head + 1) % this.size;
      if (this.count < this.size) this.count++;
    }

    const n = this.count || 1;
    let avgVol = 0, avgCen = 0;
    const ab = this._avgBands;
    ab.fill(0);
    for (let k = 0; k < this.count; k++) {
      const h = this.ring[k];
      avgVol += h.volume;
      avgCen += h.centroid;
      for (let i = 0; i < 7; i++) ab[i] += h.bands[i];
    }
    avgVol /= n;
    avgCen /= n;
    for (let i = 0; i < 7; i++) ab[i] /= n;

    const dVol = curVol - avgVol, dCen = centroid - avgCen;
    const sc = this._sc;
    for (let i = 0; i < ALL.length; i++) sc[ALL[i]] = 0;

    if (avgVol < 0.16 && curVol < 0.16) sc.sil = 1;

    for (let i = 0; i < PLOSIVE.length; i++) {
      const v = PLOSIVE[i];
      if (dVol < 0.01) sc[v] -= 0.5;
      if (avgVol < 0.2) sc[v] += 0.2;
      if (dCen > 750) sc[v] += 0.2;
    }

    const c = centroid, b6 = bands[5], b7 = bands[6];
    // Oclusivas calibradas para voz de 24 kHz (Nyquist 12 kHz, centroide típico 2.4–5.8 kHz).
    if (c > 900 && c < 8500) {
      if (c > 5200) sc.DD += 0.65;
      else if (c > 3600) sc.kk += 0.65;
      else if (c > 2400) { sc.PP += 0.95; if (b7 > 0.22 && c < 5000) sc.DD += 1.25; }
      else sc.nn += 0.6;
    }

    // Fricativas y vibrante española (f, z/c, s, ch, r/rr).
    if (curVol > 0.05) {
      if (c > 4200 && (b7 > 0.26 || b6 > 0.34)) sc.SS = 0.85 + 0.3 * b7;
      if (c > 2900 && c < 5400 && b6 > 0.30 && bands[4] > 0.20) sc.CH = 0.86;
      if (dCen > 600 && c > 3500 && b7 > 0.24 && ab[6] > 0.18) sc.FF = 0.78;
      if (c > 3100 && c < 6000 && b7 > 0.18 && bands[2] < 0.24) sc.TH = 0.72;
      if (c > 1400 && c < 3300 && bands[3] > 0.24 && bands[4] > 0.18 && Math.abs(dVol) > 0.035) sc.RR = 0.75;
    }

    // Vocales por relaciones de formantes (F1/F2 en bandas 1..5).
    if (avgVol > 0.09 && avgCen < 5200 && c < 5400) {
      const b1 = ab[0], b2 = ab[1], b3 = ab[2], b4 = ab[3], b5 = ab[4];
      const d12 = Math.abs(b1 - b2), spread = Math.max(Math.abs(b2 - b3), Math.abs(b2 - b4), Math.abs(b3 - b4));
      if (b3 > 0.09 || b4 > 0.09) {
        if (b4 > b3) { sc.aa = 0.82; if (b3 > b2) sc.aa += 0.2; }
        if (b3 > b2 && b3 > b4) sc.I = 0.75;
        if (d12 < 0.25) sc.U = 0.72;
        if (spread < 0.25) sc.O = 0.9;
        if (b2 > b3 && b3 > b4) sc.E = 1;
        if (b3 < 0.2 && b4 > 0.3) sc.I = 0.75;
        if (b3 > 0.25 && b5 > 0.25) sc.O = 0.72;
        if (b3 < 0.15 && b5 < 0.15) sc.U = 0.72;
      }
    }

    // Estabilidad: el visema actual gana en los primeros 100 ms y decae pasado maxMs (260 ms).
    const held = now - this.since;
    const k = held <= 100 ? 1.3 : held <= this.maxMs ? 1.3 - 0.3 * ((held - 100) / Math.max(1, this.maxMs - 100)) : Math.max(0.5, 1 - (held - this.maxMs) / 900);
    sc[this.viseme] *= k;

    let best = 'sil', top = -Infinity;
    for (let i = 0; i < ALL.length; i++) {
      const v = ALL[i];
      if (sc[v] > top) { top = sc[v]; best = v; }
    }
    if (best !== this.viseme) { this.viseme = best; this.since = now; }

    out.aa = out.ee = out.ih = out.oh = out.ou = out.close = 0;
    out.kind = KIND[best];
    if (out.kind === 'vowel') {
      out[VOWEL[best]] = 1;
    } else if (out.kind === 'plosive') {
      out.close = best === 'PP' ? 1 : 0.78;
    } else if (out.kind === 'fricative') {
      if (best === 'CH') { out.oh = 0.35; out.ih = 0.35; out.close = 0.35; }
      else if (best === 'FF' || best === 'TH') { out.ih = 0.35; out.close = 0.55; }
      else if (best === 'RR') { out.ee = 0.45; out.aa = 0.2; out.close = 0.25; }
      else { out.ih = 0.6; out.ee = 0.3; out.close = 0.4; }
    }
    return out;
  }
}
