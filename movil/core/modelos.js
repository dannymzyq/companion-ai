// Modelos del modo «todo dentro del teléfono»: qué hay que bajar, cuánto ocupa y en qué va.
// La lista de archivos se pide a Hugging Face al momento (así se sabe el tamaño exacto antes de bajar); la
// descarga la hace el teléfono (models.download): con progreso, se puede cancelar y reanudar, y solo con wifi
// salvo que se permitan los datos móviles.
import { call, kv, request, stream } from './platform.js';

const HF = 'https://huggingface.co';
const SILERO_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx';

// Medidos en el Mac (16 nov 2026, M5 Pro): ver movil/README.md. En el iPhone 15 Pro, por medir.
export const CATALOGO = {
  oido: [
    { id: 'whisper-turbo', nombre: 'Whisper large-v3 turbo', repo: 'argmaxinc/whisperkit-coreml',
      sub: 'openai_whisper-large-v3-v20240930_turbo_632MB', nota: 'Entiende mejor el español. Recomendado.' },
    { id: 'whisper-small', nombre: 'Whisper small', repo: 'argmaxinc/whisperkit-coreml',
      sub: 'openai_whisper-small_216MB', nota: 'Más pequeño; se equivoca más con nombres y títulos.' },
  ],
  cerebro: [
    { id: 'llama32-3b', nombre: 'Llama 3.2 3B', repo: 'mlx-community/Llama-3.2-3B-Instruct-4bit',
      nota: 'Respuestas cortas y naturales en español. Recomendado: cabe junto al oído en un iPhone de 8 GB.' },
    { id: 'lfm2-2.6b', nombre: 'LFM2 2.6B', repo: 'mlx-community/LFM2-2.6B-4bit',
      nota: 'Más rápido y más ligero; a veces se alarga.' },
    { id: 'gemma4-e2b', nombre: 'Gemma 4 E2B (solo texto)', repo: 'mlx-community/Gemma4-E2B-IT-Text-int4',
      nota: 'Más listo, pero en un iPhone de 8 GB no deja sitio para el oído.' },
    { id: 'gemma4-e2b-full', nombre: 'Gemma 4 E2B (completo)', repo: 'mlx-community/gemma-4-e2b-it-4bit',
      nota: 'También entiende imágenes (la app todavía no usa la cámara). Pide mucha memoria.' },
    { id: 'gemma4-e4b', nombre: 'Gemma 4 E4B', repo: 'mlx-community/gemma-4-e4b-it-4bit',
      nota: 'El más listo; solo en teléfonos con más memoria.' },
  ],
  silero: [{ id: 'silero-vad', nombre: 'Detector de voz (Silero)', archivos: [{ url: SILERO_URL, path: 'silero_vad.onnx', size: 643854 }] }],
};
// La voz ligera de cada voz de voices.json («light.model») en formato de sherpa-onnx.
export const vozLigera = (modelo) => ({ id: `piper-${modelo}`, nombre: `Voz ligera ${modelo}`, repo: `csukuangfj/vits-piper-${modelo}`,
  filtro: (p) => !/(^|\/)(MODEL_CARD|vits-piper.*\.(py|sh)|\.gitattributes)$/.test(p) });

const listas = new Map();

// [{url, path, size}] de un modelo (de Hugging Face o fija)
export async function archivos(m) {
  if (m.archivos) return m.archivos;
  if (listas.has(m.id)) return listas.get(m.id);
  // La lista se guarda: sin internet (el modo teléfono) se sigue sabiendo qué hay que tener.
  const guardada = await kv.get(`lista-${m.id.toLowerCase()}`);
  if (Array.isArray(guardada) && guardada.length) { listas.set(m.id, guardada); return guardada; }
  const sub = m.sub ? `/${m.sub}` : '';
  const r = await request({ url: `${HF}/api/models/${m.repo}/tree/main${sub}?recursive=true`, timeout: 20 });
  if (r.status !== 200) throw new Error(`Hugging Face respondió ${r.status}`);
  const lista = JSON.parse(r.body)
    .filter((x) => x.type === 'file' && !/(^|\/)\.|README\.md$/.test(x.path) && (!m.filtro || m.filtro(x.path)))
    .map((x) => ({ url: `${HF}/${m.repo}/resolve/main/${x.path}`, path: m.sub ? x.path.slice(m.sub.length + 1) : x.path,
      size: x.size || (x.lfs && x.lfs.size) || 0 }));
  listas.set(m.id, lista);
  kv.set(`lista-${m.id.toLowerCase()}`, lista).catch(() => {});
  return lista;
}

export async function estado(m) {
  const files = await archivos(m);
  const total = files.reduce((a, f) => a + f.size, 0);
  const { present } = await call('models.status', { id: m.id, files });
  return { id: m.id, nombre: m.nombre, total, present, listo: total > 0 ? present >= total : present > 0 };
}

const bajando = new Map();     // id → {done, total, error}
export const progreso = (id) => bajando.get(id) || null;

export async function bajar(m, { datosMoviles = false } = {}) {
  if (bajando.get(m.id) && !bajando.get(m.id).error && !bajando.get(m.id).fin) return;
  const files = await archivos(m);
  const p = { done: 0, total: files.reduce((a, f) => a + f.size, 0), error: null, fin: false };
  bajando.set(m.id, p);
  try {
    await stream('models.download', { id: m.id, files, cellular: datosMoviles }, (kind, data) => {
      if (kind === 'progress') Object.assign(p, data);
    });
    p.fin = true;
    p.done = p.total;
  } catch (e) {
    p.error = e.message;
    throw e;
  }
}

export const cancelar = (m) => call('models.cancel', { id: m.id });
export const borrar = (m) => { bajando.delete(m.id); return call('models.delete', { id: m.id }); };

// ¿Cabe en la memoria que iOS deja a la app? Medido en un iPhone 16 Pro (16 nov 2026): el cerebro ocupa 1,08 veces
// lo que pesa (+0,3 GB al generar) y la app tiene ~3,5 GB. Un cerebro solo cabe si deja sitio al oído más pequeño.
const OIDO_MIN = 217350763;
export function cabe(kind, total, memoria) {
  if (!memoria || !total) return true;
  if (kind === 'cerebro') return necesita('cerebro', total) + necesita('oido', OIDO_MIN) <= memoria;
  return necesita(kind, total) <= memoria;
}

export const necesita = (kind, total) => (kind === 'cerebro' ? total * 1.08 + 300e6 : kind === 'oido' ? total * 1.4 + 100e6 : total);

export const gb = (bytes) => `${(bytes / 1e9).toFixed(bytes > 1e9 ? 1 : 2).replace('.', ',')} GB`;
