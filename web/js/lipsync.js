// Qué sonido se está diciendo, para la forma de la boca (17 nov 2026). Adaptado de wawa-lipsync 0.0.2
// (https://github.com/wass08/wawa-lipsync, MIT, © Wawa Sensei): mira 7 bandas de formantes y el centroide del
// espectro de la voz que suena (audio.js) y puntúa cada «visema» (vocales a/e/i/o/u, oclusivas p/t/k/n que cierran la
// boca, fricativas s/f/ch con los dientes casi juntos). Como allí, el visema actual gana un poco al principio (para
// que la boca no tiemble) y pierde si dura demasiado. Devuelve pesos para las expresiones de boca de VRM
// (aa, ee, ih, oh, ou) más `close`: cuánto debe cerrarse en una consonante.
const VOWEL = { aa: 'aa', E: 'ee', I: 'ih', O: 'oh', U: 'ou' };
const PLOSIVE = ['PP', 'DD', 'kk', 'nn'];
const FRICATIVE = ['FF', 'TH', 'SS', 'CH', 'RR'];
const ALL = ['sil', ...PLOSIVE, ...FRICATIVE, ...Object.keys(VOWEL)];
const KIND = Object.fromEntries(ALL.map((v) => [v, v === 'sil' ? 'silence' : PLOSIVE.includes(v) ? 'plosive' : FRICATIVE.includes(v) ? 'fricative' : 'vowel']));
const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0);

export class Lipsync {
  constructor(historySize = 8) {
    this.history = [];
    this.size = historySize;
    this.viseme = 'sil';
    this.since = 0;
    this.maxMs = 100;
    this.out = { aa: 0, ee: 0, ih: 0, oh: 0, ou: 0, close: 0, kind: 'silence' };
  }

  // bands: 7 valores 0..1 (audio.js, LIP_BANDS); centroid en Hz; now en ms.
  update(bands, centroid, now) {
    const out = this.out;
    if (!bands) { out.kind = 'silence'; return out; }
    const cur = { bands, centroid, volume: mean(bands) };
    if (cur.volume > 0) { this.history.push(cur); if (this.history.length > this.size) this.history.shift(); }
    const n = this.history.length || 1, avg = { volume: 0, centroid: 0, bands: [0, 0, 0, 0, 0, 0, 0] };
    for (const h of this.history) { avg.volume += h.volume / n; avg.centroid += h.centroid / n; h.bands.forEach((b, i) => (avg.bands[i] += b / n)); }
    const dVol = cur.volume - avg.volume, dCen = cur.centroid - avg.centroid;
    const sc = Object.fromEntries(ALL.map((v) => [v, 0]));
    if (avg.volume < 0.2 && cur.volume < 0.2) sc.sil = 1;
    for (const v of PLOSIVE) {
      if (dVol < 0.01) sc[v] -= 0.5;
      if (avg.volume < 0.2) sc[v] += 0.2;
      if (dCen > 1000) sc[v] += 0.2;
    }
    const c = cur.centroid, b7 = cur.bands[6];
    if (c > 1000 && c < 8000) {
      if (c > 7000) sc.DD += 0.6;
      else if (c > 5000) sc.kk += 0.6;
      else if (c > 4000) { sc.PP += 1; if (b7 > 0.25 && c < 6000) sc.DD += 1.4; }
      else sc.nn += 0.6;
    }
    if (dCen > 1000 && c > 6000 && avg.centroid > 5000 && cur.bands[6] > 0.4 && avg.bands[6] > 0.3) sc.FF = 0.7;
    if (avg.volume > 0.1 && avg.centroid < 6000 && c < 6000) {
      const [b1, b2, b3, b4, b5] = avg.bands;
      const d12 = Math.abs(b1 - b2), spread = Math.max(Math.abs(b2 - b3), Math.abs(b2 - b4), Math.abs(b3 - b4));
      if (b3 > 0.1 || b4 > 0.1) {
        if (b4 > b3) { sc.aa = 0.8; if (b3 > b2) sc.aa += 0.2; }
        if (b3 > b2 && b3 > b4) sc.I = 0.7;
        if (d12 < 0.25) sc.U = 0.7;
        if (spread < 0.25) sc.O = 0.9;
        if (b2 > b3 && b3 > b4) sc.E = 1;
        if (b3 < 0.2 && b4 > 0.3) sc.I = 0.7;
        if (b3 > 0.25 && b5 > 0.25) sc.O = 0.7;
        if (b3 < 0.15 && b5 < 0.15) sc.U = 0.7;
      }
    }
    // El visema actual se mantiene un poco (sin temblores) y se suelta si dura mucho.
    const held = now - this.since;
    const k = held <= 100 ? 1.3 : held <= this.maxMs ? 1.3 - 0.3 * ((held - 100) / Math.max(1, this.maxMs - 100)) : Math.max(0.5, 1 - (held - this.maxMs) / 1000);
    sc[this.viseme] *= k;
    let best = 'sil', top = -Infinity;
    for (const v of ALL) if (sc[v] > top) { top = sc[v]; best = v; }
    if (best !== this.viseme) { this.viseme = best; this.since = now; }
    // A pesos de VRM.
    for (const key of ['aa', 'ee', 'ih', 'oh', 'ou']) out[key] = 0;
    out.kind = KIND[best];
    out.close = 0;
    if (out.kind === 'vowel') out[VOWEL[best]] = 1;
    else if (out.kind === 'plosive') out.close = 1;                 // p, b, m, t, k: la boca se cierra un instante
    else if (out.kind === 'fricative') { out.ih = 0.6; out.ee = 0.3; out.close = 0.4; }   // s, f, ch: dientes casi juntos
    return out;
  }
}
