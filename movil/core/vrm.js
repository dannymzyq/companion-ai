// VRM propios en el teléfono (port de companion/vrm.py y de la parte de models.py). El archivo lo guarda el nativo
// en la carpeta de la app (vrm.write por trozos) y la interfaz lo carga de app://companion/propios/<id>.vrm.
// La lista (id, nombre, versión, tamaño) va en kv ('vrm_propios').
import { call, kv } from './platform.js';

export const MAX_MB = 150;              // más grande, y el teléfono se queda sin memoria al cargarlo
const CHUNK = 2 * 1024 * 1024;
const ID_RE = /^[a-z0-9_-]{1,60}$/;

export class VRMError extends Error {}

export function readGltfJson(buf) {
  const v = new DataView(buf);
  if (buf.byteLength < 20 || String.fromCharCode(...new Uint8Array(buf, 0, 4)) !== 'glTF') throw new VRMError('No es un archivo GLB/VRM válido');
  if (v.getUint32(4, true) !== 2) throw new VRMError(`glTF versión ${v.getUint32(4, true)} no soportada`);
  if (v.getUint32(8, true) > buf.byteLength) throw new VRMError('Archivo truncado');
  const len = v.getUint32(12, true);
  if (v.getUint32(16, true) !== 0x4E4F534A) throw new VRMError('El primer chunk no es JSON');
  return JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, len)));
}

export function extractMeta(gltf) {
  const ext = gltf.extensions || {};
  if (ext.VRMC_vrm) {
    const m = ext.VRMC_vrm.meta || {};
    return { spec: '1.0', name: m.name || null, authors: m.authors || [], license_url: m.licenseUrl || null,
      avatar_permission: m.avatarPermission || 'onlyAuthor', commercial_usage: m.commercialUsage || 'personalNonProfit',
      allow_sexual: !!m.allowExcessivelySexualUsage };
  }
  if (ext.VRM) {
    const m = ext.VRM.meta || {};
    return { spec: '0.x', name: m.title || null, authors: m.author ? [m.author] : [],
      license_url: m.otherPermissionUrl || m.licenseName || null, avatar_permission: m.allowedUserName || 'OnlyAuthor',
      commercial_usage: m.commercialUssageName || 'Disallow', allow_sexual: m.sexualUssageName === 'Allow' };
  }
  throw new VRMError('El archivo es glTF pero no tiene extensión VRM (VRMC_vrm ni VRM)');
}

export function licenseWarnings(meta) {
  const w = [];
  if (!meta.allow_sexual) w.push('La licencia del autor no permite usos sexuales; no lo uses en modo +18 fuera de tus pruebas privadas.');
  if (['onlyAuthor', 'OnlyAuthor'].includes(meta.avatar_permission)) w.push('La licencia solo permite que el autor use el avatar.');
  if (['personalNonProfit', 'Disallow'].includes(meta.commercial_usage)) w.push('La licencia no permite uso comercial.');
  return w;
}

export const list = async () => { const l = await kv.get('vrm_propios', []); return Array.isArray(l) ? l : []; };
const saveList = (l) => kv.set('vrm_propios', l);
export const url = (id) => `/propios/${id}.vrm`;

function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// Valida y guarda; devuelve {id, meta, license_warnings}. `taken`: ids que no se pueden usar (los incluidos).
export async function add(filename, buf, taken = []) {
  if (buf.byteLength > MAX_MB * 1024 * 1024) throw new VRMError(`El VRM supera ${MAX_MB} MB: en el teléfono no cabe.`);
  let meta;
  try { meta = extractMeta(readGltfJson(buf)); } catch (e) { throw new VRMError(`VRM inválido: ${e.message}`); }
  let stem = String(filename || 'modelo').replace(/\.[^.]*$/, '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'modelo';
  if (taken.includes(stem)) stem = `${stem}-propio`;
  const l = await list();
  let id = stem, n = 2;
  while (l.some((m) => m.id === id) || taken.includes(id)) id = `${stem}-${n++}`;
  if (!ID_RE.test(id)) throw new VRMError('Nombre de archivo no válido');
  const bytes = new Uint8Array(buf);
  for (let o = 0; o < bytes.length; o += CHUNK) {
    await call('vrm.write', { id, first: o === 0, data: b64(bytes.subarray(o, o + CHUNK)) });
  }
  l.push({ id, name: meta.name || id, spec: meta.spec, size_mb: Math.round(buf.byteLength / 1e5) / 10 });
  await saveList(l);
  return { id, meta, license_warnings: licenseWarnings(meta) };
}

export async function remove(id) {
  const l = await list();
  if (!l.some((m) => m.id === id)) throw new VRMError('Solo se pueden quitar los modelos propios');
  await call('vrm.remove', { id });
  await saveList(l.filter((m) => m.id !== id));
}
