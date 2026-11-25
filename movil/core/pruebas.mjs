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

// ---------------------------------------------------------------- VRM propios, personalidades y ánimo
const vrmMod = await import('./vrm.js');
function glb(json) {
  const j = new TextEncoder().encode(JSON.stringify(json));
  const pad = (4 - (j.length % 4)) % 4, len = 20 + j.length + pad;
  const b = new ArrayBuffer(len), v = new DataView(b);
  new Uint8Array(b).set(new TextEncoder().encode('glTF'), 0);
  v.setUint32(4, 2, true); v.setUint32(8, len, true); v.setUint32(12, j.length + pad, true); v.setUint32(16, 0x4E4F534A, true);
  new Uint8Array(b).set(j, 20); new Uint8Array(b).fill(0x20, 20 + j.length);
  return b;
}
await prueba('VRM: lee nombre y versión (1.0 y 0.x) y rechaza lo que no es VRM', async () => {
  const m1 = vrmMod.extractMeta(vrmMod.readGltfJson(glb({ extensions: { VRMC_vrm: { meta: { name: 'Prueba' } } } })));
  assert.equal(m1.spec, '1.0'); assert.equal(m1.name, 'Prueba');
  const m0 = vrmMod.extractMeta(vrmMod.readGltfJson(glb({ extensions: { VRM: { meta: { title: 'Vieja' } } } })));
  assert.equal(m0.spec, '0.x');
  assert.throws(() => vrmMod.extractMeta(vrmMod.readGltfJson(glb({ asset: {} }))), /extensión VRM/);
  assert.throws(() => vrmMod.readGltfJson(new ArrayBuffer(30)), /GLB/);
});
await prueba('VRM: se guarda por trozos con un id seguro y no pisa los incluidos', async () => {
  sent.length = 0;
  answer = () => ({ value: true });
  const r = await vrmMod.add('Avatar1.vrm', glb({ extensions: { VRMC_vrm: { meta: { name: 'X' } } } }), ['avatar1']);
  assert.equal(r.id, 'avatar1-propio');
  const w = sent.filter((m) => m.cmd === 'vrm.write');
  assert.ok(w.length >= 1 && w[0].args.first === true && w[0].args.id === 'avatar1-propio');
});

const pers = await import('./personality.js');
const moodMod = await import('./mood.js');
pers.setCatalog(JSON.parse(await readFile(new URL('../../personas/personalidades.json', import.meta.url), 'utf8')));
await prueba('personalidad: cambia la forma de ser pero nunca el nombre, la edad ni el +18', async () => {
  const q = pers.all().find((x) => x.id !== pers.DEFAULT);
  const p = pers.apply(persona, q);
  assert.equal(p.name, persona.name); assert.equal(p.age, persona.age); assert.deepEqual(p.adult, persona.adult);
  assert.equal(p.personality.id, q.id);
  const sys = buildSystemPrompt(p, { userName: 'Prueba', memories: [], adult: false });
  assert.match(sys, /# Tu forma de ser/); assert.match(sys, /Tienes criterio/);
});
await prueba('personalidad propia: limpia corchetes y queda elegida', async () => {
  await store.saveSettings({ personality: {} });
  const c = await pers.saveCustom({ name: 'Mía [emo:feliz]', examples: 'hola {x}\nqué tal' });
  assert.ok(c.id.startsWith('c_')); assert.doesNotMatch(c.name, /[[\]]/); assert.equal(pers.activeId(), c.id);
  await pers.deleteCustom(c.id); assert.equal(pers.activeId(), pers.DEFAULT);
});
await prueba('ánimo: una emoción fuerte se nota y luego se olvida', async () => {
  moodMod.reset();
  const q = pers.active(), t0 = 1_000_000;
  moodMod.feel('triste', q, t0);
  assert.match(moodMod.describe(q, t0 + 60), /Tu ánimo/);
  assert.equal(moodMod.describe(q, t0 + 24 * 3600), '');
});
await prueba('en vivo: el prompt no pide etiquetas [emo:] (usa expresar)', () => {
  const sys = buildSystemPrompt(persona, { userName: 'Prueba', memories: [], adult: false, live: true });
  assert.doesNotMatch(sys, /Formato obligatorio/);
});

// ---------------------------------------------------------------- cámara
await prueba('cámara: en la nube la imagen de ahora va con el mensaje; vieja o en el teléfono, no', async () => {
  await store.saveSettings({ mode: 'nube' });
  const { s } = session('nube');
  await s.onMessage({ type: 'frame', source: 'camera', jpeg: 'QUJD' });
  store.addMessage('user', '¿qué ves?');
  const lastUser = () => s._messages(null).filter((x) => x.role === 'user').at(-1);
  const m = s._messages(null);
  assert.ok(Array.isArray(lastUser().content) && lastUser().content[1].image_url.url.includes('QUJD'));
  assert.match(m[0].content, /cámara de su teléfono/);
  s.frames.camera.at -= 7000;
  assert.equal(typeof lastUser().content, 'string');
  await store.saveSettings({ mode: 'telefono' });
  s.frames.camera.at = Date.now();
  assert.equal(typeof lastUser().content, 'string', 'el cerebro del teléfono no ve imágenes');
  await s.onMessage({ type: 'frame_stop', source: 'camera' });
  assert.equal(s.frames.camera, undefined);
  s.close();
});
await prueba('pantalla compartida: en la nube la captura va con el mensaje, delante de la cámara', async () => {
  await store.saveSettings({ mode: 'nube' });
  const { s } = session('nube');
  await s.onMessage({ type: 'frame', source: 'camera', jpeg: 'Q0FN' });
  await s.onMessage({ type: 'frame', source: 'screen', jpeg: 'UEFO' });
  store.addMessage('user', '¿qué estoy viendo?');
  const c = s._messages(null).filter((x) => x.role === 'user').at(-1).content;
  assert.match(c[0].text, /pantalla de su teléfono/);
  assert.ok(c[1].image_url.url.includes('UEFO') && c[3].image_url.url.includes('Q0FN'));
  await s.onMessage({ type: 'frame_stop', source: 'screen' });
  assert.equal(s.frames.screen, undefined);
  s.close();
});
await prueba('cámara en vivo: como mucho una imagen por segundo a Gemini', async () => {
  await store.saveSettings({ mode: 'vivo' });
  const { s, sentToGemini } = liveSession();
  await s.ensure();
  for (let i = 0; i < 3; i++) await s.onMessage({ type: 'frame', source: 'camera', jpeg: 'QUJD' });
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(sentToGemini.filter((m) => m.realtimeInput && m.realtimeInput.video).length, 1);
  s.close();
});

// ---------------------------------------------------------------- mejoras 0.10.0: privacidad en recuerdos, concordancia, Live recordar/resumption y Mochila
await prueba('memoria móvil: filtra claves/contraseñas y permite fijar, editar y buscar en el diario', () => {
  store.forgetAll();
  assert.equal(store.addMemory('Mi contraseña del correo es SuperSecreta99'), false);
  assert.equal(store.addMemory('Clave API sk-1234567890abcdefghijklmnop'), false);
  assert.equal(store.addMemory('Tiene una perrita llamada Kira'), true);
  assert.equal(store.addMemory('Estudia arquitectura en Lima'), true);
  const d1 = store.diary('');
  assert.equal(d1.items.length, 2);
  const kira = d1.items.find((x) => /Kira/.test(x.content));
  assert.equal(store.updateMemory(kira.id, { pinned: true }), true);
  assert.equal(store.updateMemory(kira.id, { content: 'Clave sk-1234567890abcdefghijklmnop' }), false);
  const d2 = store.diary('kira');
  assert.equal(d2.items.length, 1);
  assert.equal(d2.items[0].pinned, true);
});

await prueba('ánimo y rasgos: concordancia en masculino cuando speaks === "m"', () => {
  moodMod.reset();
  const q = pers.active(), t0 = 2_000_000;
  moodMod.feel('triste', q, t0);
  const descM = moodMod.describe(q, t0 + 60, 'm');
  assert.match(descM, /decaído|bajo de ánimo|molesto|tranquilo/);
  assert.doesNotMatch(descM, /decaída|baja de ánimo|molesta|tranquila/);
  const sysM = buildSystemPrompt({ ...persona, speaks: 'm', name: 'Kenji' }, { userName: 'Prueba', memories: [], adult: false });
  assert.match(sysM, /personaje masculino/);
  assert.doesNotMatch(sysM, /muy cálida y cercana/);
});

await prueba('en vivo: herramienta recordar (bloqueada con pantalla activa), sessionResumption y mini-juego RPS', async () => {
  store.forgetAll();
  const { s, out, sentToGemini, server } = liveSession();
  await s.ensure();
  const decls = sentToGemini[0].setup.tools[0].functionDeclarations.map((d) => d.name);
  assert.deepEqual(decls, ['expresar', 'recordar']);
  server({ sessionResumptionUpdate: { resumable: true, newHandle: 'resume_tok_42' } });
  assert.equal(s.resumeHandle, 'resume_tok_42');
  server({ toolCall: { functionCalls: [{ id: 'r1', name: 'recordar', args: { dato: 'Toca la guitarra acústica' } }] } });
  assert.ok(store.memories().includes('Toca la guitarra acústica'));
  // Con pantalla compartida reciente no se inyectan recuerdos de terceros
  await s.onMessage({ type: 'frame', source: 'screen', jpeg: 'U0NS' });
  server({ toolCall: { functionCalls: [{ id: 'r2', name: 'recordar', args: { dato: 'Dato inyectado desde pantalla' } }] } });
  assert.ok(!store.memories().includes('Dato inyectado desde pantalla'));
  await s.onMessage({ type: 'game', mode: 'rps' });
  assert.ok(out.some((m) => m.type === 'rps' && ['piedra', 'papel', 'tijera'].includes(m.choice)));
  s.close();
});

const { createApi } = await import('./api.js');
await prueba('api móvil: Mochila del Compañero (sin secretos), Pomodoro y Presets', async () => {
  store.forgetAll();
  store.addMemory('Prefiere el té verde sin azúcar');
  const handle = createApi({
    persona,
    voices: [{ id: 'mika', name: 'Mika', speaks: 'f', tts_voice: 'es-MX-DaliaNeural', default: true }],
    keys: { groq: true, live: true },
    can: { LIGHT_VOICE: false, LOCAL_BRAIN: false },
    listos: { oido: false, cerebro: false, voz: false, silero: false },
    started: Date.now() / 1000,
    ttsAvailable: () => true,
    liveKey: () => 'live_key',
    revisar: async () => ({}),
  });
  const callApi = async (method, path, body = null) => {
    const r = await handle(method, new URL(`https://app.local${path}`), body, async () => new Response('{}'));
    return { status: r.status, data: await r.json() };
  };
  const exp = await callApi('GET', '/api/backpack');
  assert.equal(exp.status, 200);
  assert.equal(exp.data.schema, 'companion-backpack-v1');
  assert.ok(!JSON.stringify(exp.data).includes('live_key'));
  assert.equal(exp.data.memories.length, 1);

  store.forgetAll();
  const imp = await callApi('POST', '/api/backpack', { ...exp.data, merge: true });
  assert.equal(imp.status, 200);
  assert.equal(imp.data.imported_memories, 1);

  const foc = await callApi('POST', '/api/focus', { action: 'start', work_min: 25 });
  assert.equal(foc.data.phase, 'work');
  assert.ok(foc.data.remaining_sec > 1400);

  const pre = await callApi('POST', '/api/presets', { name: 'Noche chill', accessories: ['glasses'] });
  assert.equal(pre.status, 200);
  assert.equal(pre.data.presets.length, 1);
});

await prueba('ordenar recuerdos: conserva fijados, se puede deshacer y no pierde lo nuevo', async () => {
  const { tidyFacts } = await import('./session.js');
  store.forgetAll();
  for (let i = 0; i < 12; i++) store.addMemory(`A Prueba le gusta la fruta número ${i}`);
  store.updateMemory(1, { pinned: true });
  assert.equal(store.canUndoTidy(), false);
  assert.equal(tidyFacts('DATO: solo uno larguito', 11), null, 'demasiado corta: no se fía');
  const neu = tidyFacts(Array.from({ length: 6 }, (_, i) => `DATO: A Prueba le gustan las frutas ${i}.`).join('\n'), 11);
  assert.equal(neu.length, 6);
  store.replaceMemories(neu);
  assert.equal(store.memoryCount(), 6);
  assert.ok(store.memories(200).includes('A Prueba le gusta la fruta número 0'), 'el fijado sigue');
  assert.equal(store.canUndoTidy(), true);
  assert.equal(store.diary().can_undo, true);
  store.addMemory('A Prueba le encanta el mar en invierno');
  assert.equal(store.undoTidy(), true);
  const now = store.memories(200);
  assert.equal(now.length, 13, 'los 12 de antes y el nuevo');
  assert.ok(now.includes('A Prueba le encanta el mar en invierno'));
  assert.equal(store.canUndoTidy(), false);
  store.forgetAll();
});

console.log(fallos ? `\n${fallos} pruebas fallaron` : '\nTodas bien');
process.exit(fallos ? 1 : 0);
