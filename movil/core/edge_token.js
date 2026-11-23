// Ficha Sec-MS-GEC (v2) que pide la voz en la nube (lectura en voz alta de Edge). Port exacto de edge_tts/drm.py
// (edge-tts 7.3.1, el que usa la PC). Con BigInt, para que la aritmética sea la de Python; solo se calcula una vez
// cada 5 minutos. Si Microsoft cambia la ficha, hay que portar la versión nueva de edge-tts.

export const TRUSTED_CLIENT_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4';
export const CHROMIUM_FULL_VERSION = '143.0.3650.75';
export const SEC_MS_GEC_VERSION = `2-${CHROMIUM_FULL_VERSION}`;
const WIN_EPOCH = 11644473600;

const B = BigInt;
const M = 0xFFFFFFFFn;
const H = (xs) => xs.map(B);

const SHA256_INITIAL = H([0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]);
const SHA256_STATE = H([0xFD9FBEA2, 0x91243CE7, 0xBE499094, 0xCD2E1E0A, 0x6C006F49, 0x04BD35AB, 0xFEB0A7E4, 0x03EFFBD2]);
const SHA256_SCHEDULE = H([0xEB24BF9E, 0x1558691F, 0xA0C09EE2, 0x0CFA32BA, 0xA622EE8C, 0xD1DD9491, 0xC0DD25A0,
  0xF9E70AB6, 0xF0C31573, 0x7058CE4E, 0x7188E606, 0x00E5AB33, 0xD258B060, 0x72766564]);
const K = H([0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
  0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3, 0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174, 0xE49B69C1,
  0xEFBE4786, 0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA, 0x983E5152, 0xA831C66D,
  0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967, 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC,
  0x53380D13, 0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3,
  0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070, 0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3,
  0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208, 0x90BEFFFA, 0xA4506CEB,
  0xBEF9A3F7, 0xC67178F2]);
const SHA256_ADJUSTMENT = 0xC9DC06A7n;
const K_BLOCK = [...K.slice(0, 14), SHA256_ADJUSTMENT, ...K.slice(15)];
const SIGMA0_ADJ = 0x059C0B80n;
const SIGMA1_ADJ = 0x000B92C0n;
const CS64_COEFFICIENTS = [[0xE82E91B1, 0xB32700D0], [0x44DE24C6, 0x88DFF51D], [0x3BEB65BC, 0x29514038],
  [0xC89C5933, 0xB328CBDF], [0x8D1EC211, 0xD405B4D5], [0x314EF5D5, 0x26E55F3C], [0xE92491B1, 0x607801C6],
  [0xF0A5B9D5, 0x82B2C1FB], [0x06064CF3, 0xFA51A3DA], [0xDA79FA60, 0x207CC464], [0xBED20560, 0x3C3C74F3],
  [0x89F9C9F8, 0xD2D14B61], [0x35FA38C6, 0xBB04A2C1], [0xCB49E3C6, 0xC5626167]].map(([a, b]) => [B(a), B(b)]);
const CS64_FACTOR = 0x82893933n;
const CS64_ADJ0 = 0xF2F90B1An;
const CS64_ADJ1 = 0x0B1A0000n;

const rol16 = (v) => { v &= M; return ((v << 16n) | (v >> 16n)) & M; };
const sigma0 = (v) => ((v >> 7n) ^ (v << 25n) ^ (v >> 18n) ^ (v << 14n) ^ (v >> 3n)) & M;
const sigma1 = (v) => ((v >> 17n) ^ (v << 15n) ^ (v >> 19n) ^ (v << 13n) ^ (v >> 10n)) & M;
const ROT = 0x100000001n;
const bigS1 = (e) => { const r = e * ROT; return (r >> 6n) ^ (r >> 11n) ^ (r >> 25n); };
const bigS0 = (a) => { const r = a * ROT; return (r >> 2n) ^ (r >> 13n) ^ (r >> 22n); };

// Las 64 rondas de SHA-256 (las de edge-tts empiezan a veces en la 14, dentro del primer bloque).
function rounds(state, words, first = 0) {
  let [a, b, c, d, e, f, g, h] = state;
  const k = first === 14 ? K_BLOCK : K;
  for (let i = first; i < 64; i++) {
    const t1 = h + bigS1(e) + (g ^ (e & (f ^ g))) + k[i] + words[i];
    const t2 = bigS0(a) + ((a & b) | (c & (a | b)));
    [a, b, c, d, e, f, g, h] = [(t1 + t2) & M, a, b, c, (d + t1) & M, e, f, g];
  }
  return [a, b, c, d, e, f, g, h];
}

function expand(words, first = 16) {
  for (let i = first; i < 64; i++) {
    const x = words[i - 2], y = words[i - 15];
    const s1 = (x >> 17n) ^ (x << 15n) ^ (x >> 19n) ^ (x << 13n) ^ (x >> 10n);
    const s0 = (y >> 7n) ^ (y << 25n) ^ (y >> 18n) ^ (y << 14n) ^ (y >> 3n);
    words.push((s1 + words[i - 7] + s0 + words[i - 16]) & M);
  }
}

const beInt = (bytes) => bytes.reduce((acc, x) => (acc << 8n) | B(x), 0n);

function sha256Init(data) {
  const words = [...Array(14).fill(0n), beInt(data.slice(0, 3)), beInt(data.slice(3, 7))];
  for (let i = 16; i < 30; i++) {
    let value = SHA256_SCHEDULE[i - 16];
    if (i - 2 >= 14) value += i === 16 ? (sigma1(words[i - 2]) ^ SIGMA1_ADJ) : sigma1(words[i - 2]);
    if (i - 7 >= 14) value += words[i - 7];
    if (i - 15 >= 14) value += i === 29 ? (sigma0(words[i - 15]) ^ SIGMA0_ADJ) : sigma0(words[i - 15]);
    words.push(value & M);
  }
  words.push((sigma1(words[28]) + words[23] + sigma0(words[15]) + words[14] + SHA256_ADJUSTMENT - K[14]) & M);
  expand(words, 31);
  const working = rounds(SHA256_STATE, words, 14);
  return SHA256_INITIAL.map((x, i) => (x + working[i]) & M);
}

function sha256Digest(data) {
  const length = 57 + data.length;
  const padLen = ((55 - length) % 64 + 64) % 64;
  const padded = [...data.slice(7), 0x80, ...Array(padLen).fill(0)];
  const bits = B(length * 8);
  for (let i = 7; i >= 0; i--) padded.push(Number((bits >> B(i * 8)) & 0xFFn));
  let state = sha256Init(data.slice(0, 7));
  for (let off = 0; off < padded.length; off += 64) {
    const words = [];
    for (let j = 0; j < 16; j++) words.push(beInt(padded.slice(off + j * 4, off + j * 4 + 4)));
    expand(words);
    const working = rounds(state, words);
    state = state.map((x, i) => (x + working[i]) & M);
  }
  const out = [];
  for (const w of state) for (let i = 3; i >= 0; i--) out.push(Number((w >> B(i * 8)) & 0xFFn));
  return out;
}

const leInt = (bytes) => bytes.reduceRight((acc, x) => (acc << 8n) | B(x), 0n);

function wordsLe4Even(bytes) {
  const padded = [...bytes, ...Array((4 - (bytes.length % 4)) % 4).fill(0)];
  const words = [];
  for (let i = 0; i < padded.length; i += 4) words.push(leInt(padded.slice(i, i + 4)));
  if (words.length % 2) words.push(0n);
  return words;
}

function cs64Digest(data, digest) {
  const keyA = leInt(digest.slice(0, 4)) | 1n, keyB = leInt(digest.slice(4, 8)) | 1n;
  const factors = [(keyA * CS64_FACTOR) & M, (keyB * CS64_FACTOR) & M];
  const terms = CS64_COEFFICIENTS.map(([c], i) => (c * factors[i % 2]) & M);
  const offsets = CS64_COEFFICIENTS.map(([, o]) => o);
  wordsLe4Even([0, ...data]).forEach((word, i) => {
    let term = word * (i % 2 === 0 ? keyA : keyB);
    let offset = rol16(word) * (i % 2 === 0 ? 0xEF0569FBn : 0xC31713DBn);
    if (i === 0) { term += CS64_ADJ0 * factors[0]; offset += CS64_ADJ1; }
    terms.push(term & M);
    offsets.push(offset & M);
  });
  let swapAcc = 0n, swapLast = 0n, state = 0n, acc = 0n;
  for (let i = 0; i < terms.length; i += 2) {
    const x = terms[i], y = terms[i + 1];
    let t = rol16((offsets[i] + x) & M);
    let q = (t * 0x76F50F34n) & M;
    swapAcc += (rol16(q) * 0xC3EFEA97n + q) & M;
    t = rol16((offsets[i + 1] + y) & M);
    q = (t * 0x1881CE3Cn) & M;
    swapLast = (rol16(q) * 0x35BD1EC9n + q) & M;
    swapAcc = (swapAcc + swapLast) & M;
    state = (state * keyA + x) & M;
    state = (rol16(state) * 0xCF98B111n) & M;
    state = (rol16(state) * 0x87085B9Fn) & M;
    state = (rol16(state) * 0x12CEB96Dn) & M;
    state = (rol16(state) * 0x257E1D83n) & M;
    acc += state;
    t = (state * keyB + y) & M;
    t = (rol16(t) * 0xA27416F5n) & M;
    t = (rol16(t) * 0xD38396FFn) & M;
    state = (rol16((rol16(t) * 0x7C932B89n) & M) * 0xBFA49F69n) & M;
    acc = (acc + state) & M;
  }
  return [swapLast ^ state, swapAcc ^ acc];
}

const hex = (bytes) => bytes.map((x) => x.toString(16).padStart(2, '0')).join('').toUpperCase();
const le32 = (v) => [0, 1, 2, 3].map((i) => Number((v >> B(i * 8)) & 0xFFn));

// unixSeconds: la hora (con el desfase del reloj ya corregido)
export function secMsGec(unixSeconds = Date.now() / 1000) {
  let ticks = unixSeconds + WIN_EPOCH;
  ticks -= ticks % 300;
  // Python: f"{ticks * 1e7:.0f}" (un float); el resultado es entero de sobra en un float de 64 bits.
  const text = `${(ticks * 1e7).toFixed(0)}${TRUSTED_CLIENT_TOKEN}`;
  const data = [...text].map((ch) => ch.charCodeAt(0));
  const digest = sha256Digest(data);
  const [c0, c1] = cs64Digest(data, digest);
  return `${hex([...le32(c0), ...le32(c1)])}-${hex(digest)}`;
}
