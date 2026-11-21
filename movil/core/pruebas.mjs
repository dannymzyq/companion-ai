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

// ---------------------------------------------------------------- En vivo (Gemini Live), con un socket de mentira
const live = await import('./live.js');
function liveSession() {
  const out = [], sentToGemini = [];
  let server = null;
  const socket = { open: async (onMsg) => { server = onMsg; return 7; },
    send: async (id, text) => { const m = JSON.parse(text); sentToGemini.push(m); if (m.setup) setTimeout(() => server('{"setupComplete":{}}'), 1); },
    close: () => {} };
  const s = new live.LiveSession((d) => out.push(typeof d === 'string' ? JSON.parse(d) : d), {
    persona: () => persona, profile: () => adulto, socket: () => socket, model: () => live.DEFAULT_MODEL, voice: () => 'Aoede' });
  return { s, out, sentToGemini, server: (o) => server(JSON.stringify(o)) };
}

await prueba('en vivo: el prompt nunca lleva el bloque +18 (adulto y ficha que lo permite)', async () => {
  await store.saveSettings({ mode: 'vivo' });
  const { s, sentToGemini } = liveSession();
  await s.onMessage({ type: 'text', text: 'hola' });
  const sys = sentToGemini[0].setup.systemInstruction.parts[0].text;
  assert.doesNotMatch(sys, /Temas \+18/);
  assert.match(sys, /Modo en vivo/);
  assert.ok(!/ejecutar_accion/.test(JSON.stringify(sentToGemini[0])), 'en el teléfono no hay acciones');
  assert.equal(llm.isCloud(), true);
  s.close();
});

await prueba('en vivo: texto, voz, subtítulos, expresar (silencioso) y fin de turno', async () => {
  await store.saveSettings({ mode: 'vivo' });
  const { s, out, sentToGemini, server } = liveSession();
  const antes = store.since(0).length;
  await s.onMessage({ type: 'text', text: '¿qué tal?' });
  assert.deepEqual(sentToGemini[1].clientContent.turns[0].parts, [{ text: '¿qué tal?' }]);
  server({ toolCall: { functionCalls: [{ id: 'a1', name: 'expresar', args: { emocion: 'feliz', gesto: 'saludar' } }] } });
  server({ serverContent: { outputTranscription: { text: '¡Muy bien, gracias!' } } });
  server({ serverContent: { modelTurn: { parts: [{ inlineData: { mimeType: 'audio/pcm;rate=24000', data: Buffer.alloc(480).toString('base64') } }] } } });
  server({ serverContent: { turnComplete: true } });
  const tool = sentToGemini.find((m) => m.toolResponse);
  assert.equal(tool.toolResponse.functionResponses[0].response.scheduling, 'SILENT');
  const types = out.filter((m) => !(m instanceof ArrayBuffer)).map((m) => m.type);
  for (const t of ['user_text', 'express', 'sentence', 'caption_delta', 'sentence_end', 'reply_end']) assert.ok(types.includes(t), `falta ${t}`);
  assert.equal(out.filter((m) => m instanceof ArrayBuffer).length, 1);
  assert.equal(out.find((m) => m.type === 'express').gestures[0], 'saludar');
  assert.equal(store.since(0).length, antes + 2, 'guarda lo dicho y la respuesta');
  s.close();
});

await prueba('en vivo: el micrófono va a Gemini a 16 kHz en trozos de ~96 ms', async () => {
  const { s, sentToGemini } = liveSession();
  await s.ensure();
  for (let i = 0; i < 3; i++) s.onAudio(new ArrayBuffer(1024));
  await new Promise((r) => setTimeout(r, 5));
  const audio = sentToGemini.filter((m) => m.realtimeInput);
  assert.equal(audio.length, 1);
  assert.equal(audio[0].realtimeInput.audio.mimeType, 'audio/pcm;rate=16000');
  assert.equal(Buffer.from(audio[0].realtimeInput.audio.data, 'base64').length, 3072);
  s.close();
});

await prueba('en vivo: si Gemini interrumpe, la interfaz corta la voz', async () => {
  const { s, out, server } = liveSession();
  await s.ensure();
  server({ serverContent: { outputTranscription: { text: 'Te iba a contar que' } } });
  server({ serverContent: { interrupted: true } });
  assert.ok(out.some((m) => m.type === 'interrupt'));
  s.close();
});

console.log(fallos ? `\n${fallos} pruebas fallaron` : '\nTodas bien');
process.exit(fallos ? 1 : 0);
