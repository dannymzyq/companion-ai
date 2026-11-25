// Escenarios dinámicos 3D según la hora/ambiente y Cabina de Fotos (N-05).
// Cambia la iluminación 3D (luz principal, ambiental y contraluz rim) y el tinte del fondo sin tocar el modo flotante,
// y permite posar al personaje y guardar una captura PNG en alta resolución con fondo transparente o de ambiente.
import { EMOTION_NAMES } from './personality.js';

const $ = (id) => document.getElementById(id);
const SCENE_KEY = 'companion.scene';

export const SCENES = {
  auto: { name: 'Automático (según la hora)' },
  estudio: {
    name: 'Estudio neutro',
    keyColor: 0xffffff, keyIntensity: Math.PI * 0.85,
    ambColor: 0xffffff, ambIntensity: 0.55,
    rimColor: 0x9ec5ff, rimIntensity: 0.42,
    bgTop: '#14141d', bgBottom: '#08080c', glow: '#8b7cf8',
  },
  manana: {
    name: 'Mañana soleada',
    keyColor: 0xfff1dc, keyIntensity: Math.PI * 0.92,
    ambColor: 0xdbeafe, ambIntensity: 0.62,
    rimColor: 0xffe4b5, rimIntensity: 0.48,
    bgTop: '#1d2233', bgBottom: '#0d1018', glow: '#64d2ff',
  },
  atardecer: {
    name: 'Atardecer dorado',
    keyColor: 0xffb37a, keyIntensity: Math.PI * 0.9,
    ambColor: 0x7c5c99, ambIntensity: 0.52,
    rimColor: 0xff7b54, rimIntensity: 0.65,
    bgTop: '#2a1824', bgBottom: '#0c0810', glow: '#ff9f43',
  },
  lluvia: {
    name: 'Tarde de lluvia',
    keyColor: 0xcbd5f5, keyIntensity: Math.PI * 0.72,
    ambColor: 0x64748b, ambIntensity: 0.56,
    rimColor: 0x7dd3fc, rimIntensity: 0.45,
    bgTop: '#111a28', bgBottom: '#070b12', glow: '#5ac8fa',
  },
  neon: {
    name: 'Noche neón',
    keyColor: 0xebd4ff, keyIntensity: Math.PI * 0.78,
    ambColor: 0x3b2667, ambIntensity: 0.5,
    rimColor: 0x00f0ff, rimIntensity: 0.78,
    bgTop: '#160d29', bgBottom: '#06050d', glow: '#bf5af2',
  },
};

export const PHOTO_POSES = [
  { id: '', label: 'Postura actual' },
  { id: 'saludar', label: 'Saludar' },
  { id: 'paz', label: 'V de la paz' },
  { id: 'posar', label: 'Posar en cadera' },
  { id: 'celebrar', label: 'Celebrar' },
  { id: 'pulgar', label: 'Pulgar arriba' },
  { id: 'pensar', label: 'Pensativa' },
  { id: 'bailar', label: 'Bailando' },
  { id: 'reverencia', label: 'Reverencia' },
  { id: 'beso', label: 'Lanzar beso' },
];

function resolveAutoKey() {
  const h = new Date().getHours();
  if (h >= 6 && h < 11) return 'manana';
  if (h >= 11 && h < 17) return 'estudio';
  if (h >= 17 && h < 20) return 'atardecer';
  return 'neon';
}

export function initPhotoAndScene({ getAvatar, getName, toast }) {
  let pref = 'auto';
  try { pref = localStorage.getItem(SCENE_KEY) || 'auto'; } catch {}
  if (!(pref in SCENES)) pref = 'auto';

  function resolvedKey() {
    return pref === 'auto' ? resolveAutoKey() : pref;
  }

  function applyScene() {
    const key = resolvedKey();
    const spec = SCENES[key] || SCENES.estudio;
    document.body.dataset.ambience = key;
    document.documentElement.style.setProperty('--scene-top', spec.bgTop);
    document.documentElement.style.setProperty('--scene-bottom', spec.bgBottom);
    const av = getAvatar();
    if (av && av.setLighting) av.setLighting(spec);
    const sel = $('scene-select');
    if (sel && sel.value !== pref) sel.value = pref;
  }

  const sel = $('scene-select');
  if (sel) {
    sel.replaceChildren(...Object.entries(SCENES).map(([k, v]) => new Option(v.name, k)));
    sel.value = pref;
    sel.onchange = () => {
      pref = sel.value in SCENES ? sel.value : 'auto';
      try { localStorage.setItem(SCENE_KEY, pref); } catch {}
      applyScene();
    };
  }

  // Re-evalúa cada 10 minutos cuando está en automático.
  setInterval(() => { if (pref === 'auto') applyScene(); }, 600000);
  applyScene();

  // ---------------- Cabina de Fotos (#photo-modal) ----------------
  const modal = $('photo-modal');
  const openBtn = $('photo-open');
  const closeBtn = $('photo-close');
  const poseSel = $('photo-pose');
  const emoSel = $('photo-emo');
  const bgSel = $('photo-bg');
  const fullChk = $('photo-full');
  const snapBtn = $('photo-snap');

  if (poseSel) {
    poseSel.replaceChildren(...PHOTO_POSES.map((p) => new Option(p.label, p.id)));
  }
  if (emoSel) {
    emoSel.replaceChildren(...Object.entries(EMOTION_NAMES).map(([k, label]) => new Option(label, k)));
  }

  let prevFull = false;
  let prevEmo = 'neutral';

  function openBooth(open) {
    if (!modal) return;
    const av = getAvatar();
    if (open && !av) {
      toast('La cabina de fotos necesita el modo 3D activo.', true);
      return;
    }
    modal.hidden = !open;
    document.body.classList.toggle('photo-mode', open);
    if (open && av) {
      prevFull = !!av.fullBody;
      prevEmo = av.emotion || 'neutral';
      if (emoSel) emoSel.value = prevEmo;
      if (poseSel) poseSel.value = '';
      if (fullChk) fullChk.checked = av.floating ? prevFull : false;
      av.wake?.();
    } else if (!open && av) {
      av.setFullBody(prevFull, false);
      if (!av.floating) { av.userMoved = false; av.frame(); }
      av.setEmotion(prevEmo);
    }
  }

  if (openBtn) openBtn.onclick = () => openBooth(true);
  if (closeBtn) closeBtn.onclick = () => openBooth(false);
  if (modal) modal.onclick = (e) => { if (e.target === modal) openBooth(false); };

  if (poseSel) {
    poseSel.onchange = () => {
      const av = getAvatar();
      if (av && poseSel.value) av.playGesture(poseSel.value);
    };
  }
  if (emoSel) {
    emoSel.onchange = () => {
      const av = getAvatar();
      if (av && emoSel.value) av.setEmotion(emoSel.value);
    };
  }
  if (fullChk) {
    fullChk.onchange = () => {
      const av = getAvatar();
      if (av) av.setFullBody(fullChk.checked, true);
    };
  }

  if (snapBtn) {
    snapBtn.onclick = async () => {
      const av = getAvatar();
      if (!av || !av.capturePng) return;
      snapBtn.disabled = true;
      try {
        const spec = SCENES[resolvedKey()] || SCENES.estudio;
        const transparent = !bgSel || bgSel.value === 'transparent';
        const blob = await av.capturePng({
          transparent,
          bgTop: spec.bgTop,
          bgBottom: spec.bgBottom,
          glow: spec.glow,
        });
        if (!blob) throw new Error('No se pudo capturar la imagen.');
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        const safeName = (getName?.() || 'companion').toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
        a.href = url;
        a.download = `${safeName}-${stamp}.png`;
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
        toast('Foto guardada en tus descargas.');
      } catch (err) {
        toast(err.message || 'No pude guardar la foto.', true);
      } finally {
        snapBtn.disabled = false;
      }
    };
  }

  return { applyScene, closeBooth: () => openBooth(false), get isOpen() { return !!(modal && !modal.hidden); } };
}
