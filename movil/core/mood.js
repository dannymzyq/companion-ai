// Ánimo entre turnos (port de companion/mood.py): las emociones que muestra dejan un ánimo (agrado y energía) que
// vuelve poco a poco al habitual de su personalidad. Va en el contexto del turno, nunca en el prompt de sistema.
// Se guarda con kv ('mood'): solo dos números, la última emoción fuerte y cuándo; nada de lo que se dijo.
import { kv } from './platform.js';

const HALF_LIFE = 25 * 60, STRONG = 0.45, REMEMBER = 40 * 60;
export const VA = {
  neutral: [0, 0], feliz: [0.6, 0.35], emocionada: [0.75, 0.85], timida: [0.1, -0.2], sonrojada: [0.35, 0.3],
  triste: [-0.65, -0.45], molesta: [-0.55, 0.45], sorprendida: [0.15, 0.7], pensativa: [0, -0.25], carinosa: [0.7, -0.05],
  enamorada: [0.8, 0.3], nerviosa: [-0.25, 0.6], asustada: [-0.6, 0.75], confundida: [-0.15, 0.15],
};
const WORD_F = { timida: 'tímida', carinosa: 'cariñosa' };
const WORD_M = {
  timida: 'tímido', carinosa: 'cariñoso', emocionada: 'emocionado', sonrojada: 'sonrojado',
  molesta: 'molesto', sorprendida: 'sorprendido', pensativa: 'pensativo', enamorada: 'enamorado',
  nerviosa: 'nervioso', asustada: 'asustado', confundida: 'confundido',
};
let state = {};
const nowS = () => Date.now() / 1000;

export async function load() { state = (await kv.get('mood', {})) || {}; }
const save = () => kv.set('mood', state).catch(() => {});

function nowVA(base, now) {
  const [bv, ba] = VA[base] || [0, 0];
  if (!('v' in state)) return [bv, ba];
  const k = 0.5 ** (Math.max(0, now - (state.t ?? now)) / HALF_LIFE);
  return [bv + (state.v - bv) * k, ba + (state.a - ba) * k];
}

export function feel(emotion, personality, now = nowS()) {
  if (!(emotion in VA) || !personality) return;
  const base = personality.base_mood || 'neutral';
  const ex = Number((personality.traits || {}).expressiveness ?? 0.6);
  let [v, a] = nowVA(base, now);
  const [ev, ea] = VA[emotion];
  const step = 0.18 + 0.32 * ex;
  v += (ev - v) * step; a += (ea - a) * step;
  Object.assign(state, { v: Math.round(v * 1000) / 1000, a: Math.round(a * 1000) / 1000, t: now, base });
  const [bv, ba] = VA[base] || [0, 0];
  if (Math.hypot(ev - bv, ea - ba) >= STRONG + 0.25 * (1 - ex) && emotion !== base) Object.assign(state, { last: emotion, last_t: now });
  save();
}

export function describe(personality, now = nowS(), speaks = 'f') {
  if (!personality || !('v' in state)) return '';
  const masc = speaks === 'm';
  const base = personality.base_mood || 'neutral';
  const [v, a] = nowVA(base, now);
  const [bv, ba] = VA[base] || [0, 0];
  const parts = [];
  if (Math.hypot(v - bv, a - ba) >= 0.12) {
    const mood = v > 0.5 ? 'de muy buen humor' : v > 0.2 ? 'de buen humor'
      : v < -0.4 && a < 0 ? (masc ? 'algo decaído' : 'algo decaída')
      : v < -0.3 ? (masc ? 'molesto o tenso' : 'molesta o tensa')
      : v < -0.15 ? (masc ? 'un poco bajo de ánimo' : 'un poco baja de ánimo')
      : (masc ? 'tranquilo' : 'tranquila');
    const energy = a > 0.5 ? ' y con mucha energía' : a > 0.25 ? ' y con energía' : a < -0.25 ? ' y sin mucha energía' : '';
    parts.push(`Ahora mismo estás ${mood}${energy}`);
  }
  if (state.last && now - (state.last_t || 0) < REMEMBER) {
    const word = (masc ? WORD_M[state.last] : WORD_F[state.last]) || state.last;
    parts.push(`hace ${Math.max(1, Math.round((now - state.last_t) / 60))} min te sentiste ${word}`);
  }
  return parts.length ? `(Tu ánimo: ${parts.join('; ')}. Que se note un poco en cómo respondes, sin decirlo salvo que venga al caso.)` : '';
}

export function closest(v, a) {
  return Object.keys(VA).reduce((best, e) => (Math.hypot(VA[e][0] - v, VA[e][1] - a) < Math.hypot(VA[best][0] - v, VA[best][1] - a) ? e : best), 'neutral');
}
export function pub(personality, now = nowS()) {
  const [v, a] = nowVA((personality || {}).base_mood || 'neutral', now);
  return { valence: Math.round(v * 100) / 100, energy: Math.round(a * 100) / 100, emotion: closest(v, a) };
}
export function reset() { state = {}; save(); }

export function sinceLastTalk(lastTs, now = nowS()) {
  if (lastTs == null) return '';
  const gap = now - lastTs;
  if (gap < 6 * 3600) return '';
  if (gap < 36 * 3600) return '(La última vez que hablaron fue hace unas horas, ayer o anoche.)';
  return `(La última vez que hablaron fue hace ${Math.round(gap / 86400)} días.)`;
}
