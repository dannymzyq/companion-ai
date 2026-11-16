// Pruebas del núcleo sin teléfono (node movil/core/pruebas.mjs). El puente nativo es de mentira: registra cada
// orden para comprobar qué sale del teléfono en cada modo.
import assert from 'node:assert/strict';

const sent = [];
let answer = () => ({ value: null });
globalThis.window = globalThis;
globalThis.location = { href: 'app://companion/' };
window.webkit = { messageHandlers: { native: { postMessage: async (msg) => { sent.push(msg); return answer(msg); } } } };

const store = await import('./store.js');
const llm = await import('./llm.js');
const { adultActive, buildSystemPrompt, loadPersona } = await import('./prompt.js');
const { Session, describeUser } = await import('./session.js');
const { readFile } = await import('node:fs/promises');

const persona = loadPersona(JSON.parse(await readFile(new URL('../../personas/mika.json', import.meta.url), 'utf8')));
let fallos = 0;
async function prueba(nombre, fn) {
  try { await fn(); console.log('ok  ', nombre); } catch (e) { fallos++; console.log('FALLO', nombre, '\n     ', e.message); }
}

const adulto = describeUser({ name: 'Prueba', birth_year: 1990, gender: '' });
const menor = describeUser({ name: 'Prueba', birth_year: new Date().getFullYear() - 15, gender: '' });

await prueba('la ficha permite +18 (si no, estas pruebas no prueban nada)', () => assert.ok(persona.adult && persona.adult.enabled));
await prueba('+18 nunca con la nube', () => assert.equal(adultActive(persona, { isCloud: true, userAdult: true }), false));
await prueba('+18 nunca con menores', () => assert.equal(adultActive(persona, { isCloud: false, userAdult: menor.adult }), false));
await prueba('+18 en el teléfono con adulto', () => assert.equal(adultActive(persona, { isCloud: false, userAdult: adulto.adult }), true));
await prueba('los límites duros van en el bloque +18', () => {
  const p = buildSystemPrompt(persona, { userName: 'Prueba', memories: [], adult: true });
  assert.match(p, /Temas \+18/); assert.match(p, /Todos los participantes son adultos/);
});

function session(mode) {
  const out = [];
  const s = new Session((d) => out.push(typeof d === 'string' ? JSON.parse(d) : d), {
    persona: () => persona, profile: () => adulto, voice: null, ear: null });
  return { s, out, system: () => s._messages(null)[0].content };
}

await prueba('modo nube: el prompt nunca lleva el bloque +18', async () => {
  await store.saveSettings({ mode: 'nube', profile: { name: 'Prueba', birth_year: 1990, gender: '' } });
  const { s, system } = session('nube');
  assert.doesNotMatch(system(), /Temas \+18/);
  s.close();
});

await prueba('modo teléfono: el prompt lleva el bloque +18 (adulto y ficha que lo permite)', async () => {
  await store.saveSettings({ mode: 'telefono' });
  const { s, system } = session('telefono');
  assert.match(system(), /Temas \+18/);
  s.close();
});

await prueba('modo teléfono: si el cerebro local falla, no se pregunta a la nube', async () => {
  await store.saveSettings({ mode: 'telefono' });
  llm.setLocal({ simulado: false, listo: true });
  llm.setHasKey(true);
  sent.length = 0;
  answer = (msg) => (msg.cmd === 'brain.load' ? { error: 'sin memoria' } : { value: true });
  await assert.rejects(async () => { for await (const _ of llm.streamChat([{ role: 'user', content: 'hola' }], { temperature: 0.7, top_p: 0.9, max_tokens: 50 })); },
    /cerebro del teléfono/);
  const red = sent.filter((m) => /^http\.|^ws\./.test(m.cmd));
  assert.deepEqual(red, [], `salió a la red: ${red.map((m) => m.cmd).join(', ')}`);
});

await prueba('modo nube: con la cuota agotada en todos los modelos no se usa un cerebro local', async () => {
  await store.saveSettings({ mode: 'nube' });
  llm.resetCloud();
  sent.length = 0;
  let id = 0;
  answer = (msg) => {
    if (msg.cmd === 'http.stream') {
      id = msg.args.stream;
      setTimeout(() => {
        window.__native.event(id, 'head', { status: 429, id });
        window.__native.event(id, 'line', '{"error": "quota perDay", "retryDelay": "60s"}');
        window.__native.event(id, 'end', null);
      }, 1);
    }
    return { value: true };
  };
  await assert.rejects(async () => { for await (const _ of llm.streamChat([{ role: 'user', content: 'hola' }], { temperature: 0.7, top_p: 0.9, max_tokens: 50 })); },
    /cuota/);
  assert.ok(!sent.some((m) => m.cmd.startsWith('brain.')), 'llamó al cerebro del teléfono');
});

await prueba('modo nube: un modelo lento dos turnos seguidos cede el primer puesto al siguiente', async () => {
  await store.saveSettings({ mode: 'nube' });
  llm.resetCloud();
  llm.setHasKey(true);
  sent.length = 0;
  answer = (msg) => {
    if (msg.cmd === 'http.stream') {
      const id = msg.args.stream;
      const model = JSON.parse(msg.args.body).model;
      const wait = model === 'gemini-3.6-flash' ? 8200 : 10;
      setTimeout(() => {
        window.__native.event(id, 'head', { status: 200, id });
        window.__native.event(id, 'line', 'data: {"choices":[{"delta":{"content":"hola"}}]}');
        window.__native.event(id, 'line', 'data: [DONE]');
        window.__native.event(id, 'end', null);
      }, wait);
    }
    return { value: true };
  };
  const turno = async () => { const out = []; for await (const p of llm.streamChat([{ role: 'user', content: 'hola' }], { temperature: 0.7, top_p: 0.9, max_tokens: 50 })) out.push(p); };
  await turno(); await turno();
  sent.length = 0;
  await turno();
  const usado = sent.filter((m) => m.cmd === 'http.stream').map((m) => JSON.parse(m.args.body).model);
  assert.deepEqual(usado, ['gemini-3.5-flash-lite']);
  assert.ok(llm.popNotices().some((n) => /va lento/.test(n)));
});

console.log(fallos ? `\n${fallos} pruebas fallaron` : '\nTodas bien');
process.exit(fallos ? 1 : 0);
