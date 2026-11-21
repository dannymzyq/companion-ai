// En el Mac la interfaz es la misma, pero los textos hablan de una PC con tarjeta NVIDIA. Aquí se adaptan: los
// fijos de index.html al cargar y los que se escriben después (Ajustes, bienvenida, avisos) según aparecen.
export const MAC = /Macintosh|Mac OS X/.test(navigator.userAgent);

const RULES = [
  [/\bTu tarjeta gráfica tiene (\S+) GB de memoria de vídeo/g, 'Tu Mac deja $1 GB de memoria a la GPU'],
  [/\b(tu|la|una) tarjeta (gráfica|NVIDIA)\b/gi, 'la GPU del Mac'],
  [/\b([Ee])n tu tarjeta de (\S+) GB/g, (_, e, gb) => `${e}n tu Mac (${gb} GB para la GPU)`],
  [/\bmemoria de vídeo de la tarjeta\b/g, 'memoria del Mac'],
  [/\bno cabe en tu tarjeta\b/g, 'no cabe en la memoria'],
  [/\bmemoria de vídeo\b/g, 'memoria'],
  [/\bRecomendada para tu PC\b/g, 'Recomendada para tu Mac'],
  [/\b([Ee])sta PC\b/g, (_, e) => `${e}ste Mac`],
  [/\b([Ee])n la PC\b/g, (_, e) => `${e}n el Mac`],
  [/\btu PC\b/g, 'tu Mac'],
  [/\bdata\\(\w+\.log)/g, 'data/$1'],
];

// Siempre aplica las reglas (para probarlas desde la consola en Windows: (await import('/js/platform.js')).asMac('…')).
export function asMac(text) {
  let out = text || '';
  for (const [rx, to] of RULES) out = out.replace(rx, to);
  return out;
}

export function here(text) {
  return MAC && text ? asMac(text) : text;
}

function fix(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const t = here(node.nodeValue);
    if (t !== node.nodeValue) node.nodeValue = t;          // solo si cambia: no vuelve a disparar el observador
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE || node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
  for (const a of ['title', 'placeholder', 'data-tip', 'aria-label']) {
    const v = node.getAttribute(a);
    if (v) { const t = here(v); if (t !== v) node.setAttribute(a, t); }
  }
  for (const c of node.childNodes) fix(c);
}

export function adaptToMac(root = document.body) {
  if (!MAC) return;
  fix(root);
  new MutationObserver((list) => {
    for (const m of list) {
      if (m.type === 'characterData') fix(m.target);
      else for (const n of m.addedNodes) fix(n);
    }
  }).observe(root, { subtree: true, childList: true, characterData: true });
}
