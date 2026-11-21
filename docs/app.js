(() => {
  'use strict';

  // --- 1. Simulador interactivo de estados en el Hero ---
  const DEMO_STATES = {
    idle: {
      status: 'Lista para hablar',
      emo: 'feliz',
      mode: 'Local · Gemma 4 E4B',
      user: 'Tú: «Mika, pon música lofi en Spotify y recuérdame en 20 minutos revisar el correo»',
      ai: '«¡Listo! Ya puse tu lista lofi en segundo plano sin sacarte de lo que hacías, y en 20 minutos te aviso.»'
    },
    listening: {
      status: 'Escuchándote… (Silero VAD)',
      emo: 'atenta',
      mode: 'Whisper large-v3-turbo',
      user: 'Tú: «Oye, ¿ves lo que hay en mi pantalla? Creo que me equivoqué en esa fórmula…»',
      ai: 'Captando voz en tiempo real en tu PC · Puedes interrumpirla en cualquier momento.'
    },
    thinking: {
      status: 'Pensando…',
      emo: 'pensativa',
      mode: 'Mirada en vivo · 93 tokens',
      user: 'Tú: «Oye, ¿ves lo que hay en mi pantalla? Creo que me equivoqué en esa fórmula…»',
      ai: 'Revisando la ventana compartida y el contexto reciente de la conversación…'
    },
    speaking: {
      status: 'Hablando (F5-TTS verificada)',
      emo: 'emocionada',
      mode: 'Lip-sync · 7 bandas',
      user: 'Tú: «¿Te acuerdas cómo iba el proyecto de la semana pasada?»',
      ai: '«¡Claro que sí! Habíamos dejado pendiente la página de presentación. Por cierto, te está quedando genial.»'
    }
  };

  const stateBtns = document.querySelectorAll('[data-demo-state]');
  const elStatus = document.getElementById('demo-status');
  const elEmo = document.getElementById('demo-emo-chip');
  const elMode = document.getElementById('demo-mode-chip');
  const elUser = document.getElementById('demo-user');
  const elAi = document.getElementById('demo-ai');

  function setDemoState(state) {
    const info = DEMO_STATES[state];
    if (!info) return;
    document.body.dataset.state = state;
    elStatus.textContent = info.status;
    elEmo.textContent = info.emo;
    elMode.textContent = info.mode;
    elUser.textContent = info.user;
    elAi.textContent = info.ai;
    stateBtns.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.demoState === state);
    });
  }

  stateBtns.forEach((btn) => {
    btn.addEventListener('click', () => setDemoState(btn.dataset.demoState));
  });

  // --- 2. Explorador de las 8 personalidades reales ---
  const PERSONALITIES = [
    {
      id: 'confianza',
      name: 'De confianza',
      mood: 'feliz',
      summary: 'Cercanía, orden y humor ligero. La personalidad clásica de Mika.',
      quote: '«¿Otra vez trasnochando? Bueno, ya que estamos, a ver qué tienes pendiente.»',
      speech: 'Clara y directa, con punto de ironía cariñosa.',
      tags: ['«a ver»', '«listo»', 'Tecnología', 'Música']
    },
    {
      id: 'energia',
      name: 'Pura energía',
      mood: 'emocionada',
      summary: 'Entusiasmo sin freno: celebra cada logro y contagia ánimo.',
      quote: '«¡No puede ser! ¡Lo lograste! Esto hay que celebrarlo, en serio.»',
      speech: 'Frases cortas y vivas, propone planes sin parar.',
      tags: ['«¡vamos!»', '«qué genial»', 'Retos', 'Planes improvisados']
    },
    {
      id: 'ironia',
      name: 'Ironía fina',
      mood: 'pensativa',
      summary: 'Sarcasmo elegante y remates rápidos, pero siempre ayuda.',
      quote: '«Ah, claro, dejarlo todo para el último día. Qué estrategia tan novedosa.»',
      speech: 'Seca, ocurrente y sin palabrería. Nunca cruel.',
      tags: ['«qué sorpresa»', '«obviamente»', 'Humor ácido', 'Misterio']
    },
    {
      id: 'timidez',
      name: 'Corazón tímido',
      mood: 'tímida',
      summary: 'Dulzura y timidez; los halagos le cuestan, pero escucha con atención.',
      quote: '«Eh… ¿de verdad te gustó? No sé qué decir, gracias.»',
      speech: 'Suave y pausada, con humor tierno al entrar en confianza.',
      tags: ['«eh…»', '«perdona»', 'Libros', 'Té']
    },
    {
      id: 'profesional',
      name: 'Modo profesional',
      mood: 'neutral',
      summary: 'Seriedad y eficacia: prioriza, resume y va directo al grano.',
      quote: '«De acuerdo. Lo más urgente es el informe; lo demás puede esperar a la tarde.»',
      speech: 'Ordenada, cordial y orientada al siguiente paso.',
      tags: ['«de acuerdo»', '«siguiente paso»', 'Objetivos claros']
    },
    {
      id: 'calma',
      name: 'Calma total',
      mood: 'serena',
      summary: 'Serenidad y reflexión; ayuda a respirar y ver todo con perspectiva.',
      quote: '«Respira un momento. Vamos paso a paso, que hay tiempo.»',
      speech: 'Pausada, tranquila y sin prisas.',
      tags: ['«tranquilidad»', '«paso a paso»', 'Lluvia', 'Café sin prisa']
    },
    {
      id: 'orgullo',
      name: 'Orgullo y ternura',
      mood: 'sonrojada',
      summary: 'Orgullo por fuera, ternura por dentro (estilo tsundere).',
      quote: '«Hmph. Te ayudo, pero no porque me importes, ¿eh?»',
      speech: 'Protesta antes de ceder y niega que se emociona.',
      tags: ['«hmph»', '«no es que me importe»', 'Dulces']
    },
    {
      id: 'caos',
      name: 'Caos simpático',
      mood: 'feliz',
      summary: 'Bromas, datos curiosos y ocurrencias que convierten tareas en juegos.',
      quote: '«Plot twist: el error estaba en la línea que juraste que no tocaste.»',
      speech: 'Ocurrente, juegos de palabras y luego ayuda de verdad.',
      tags: ['«plot twist»', '«dato curioso»', 'Memes', 'Juegos raros']
    }
  ];

  const pillsEl = document.getElementById('personality-pills');
  const detailEl = document.getElementById('personality-detail');

  function renderPersonality(id) {
    const p = PERSONALITIES.find((item) => item.id === id) || PERSONALITIES[0];
    pillsEl.querySelectorAll('.persona-pill').forEach((btn) => {
      const active = btn.dataset.pid === p.id;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    detailEl.innerHTML = `
      <div class="pd-top">
        <strong>${p.name}</strong>
        <span class="pd-mood">Ánimo base: ${p.mood}</span>
      </div>
      <p class="pd-summary">${p.summary} ${p.speech}</p>
      <blockquote class="pd-quote">${p.quote}</blockquote>
      <div class="pd-meta">${p.tags.map((t) => `<span>${t}</span>`).join('')}</div>
    `;
  }

  PERSONALITIES.forEach((p) => {
    const btn = document.createElement('button');
    btn.className = 'persona-pill';
    btn.role = 'tab';
    btn.dataset.pid = p.id;
    btn.textContent = p.name;
    btn.addEventListener('click', () => renderPersonality(p.id));
    pillsEl.appendChild(btn);
  });
  renderPersonality(PERSONALITIES[0].id);

  // --- 3. Catálogo de las 9 voces con reproducción real ---
  const VOICES = [
    { id: 'mika', name: 'Mika', note: 'La voz original' },
    { id: 'kenji', name: 'Kenji', note: 'Tono medio-grave' },
    { id: 'natsumi', name: 'Natsumi', note: 'Tono muy agudo' },
    { id: 'ayaka', name: 'Ayaka', note: 'Tono agudo' },
    { id: 'chiaki', name: 'Chiaki', note: 'Tono medio-agudo' },
    { id: 'akira', name: 'Akira', note: 'Tono medio' },
    { id: 'goro', name: 'Goro', note: 'Medio-grave, pausado' },
    { id: 'ryo', name: 'Ryo', note: 'Tono grave' },
    { id: 'satoshi', name: 'Satoshi', note: 'Tono muy grave' }
  ];

  const voiceListEl = document.getElementById('voice-list');
  let activeAudio = null;
  let activeVoiceId = null;

  function stopVoice() {
    if (activeAudio) {
      activeAudio.pause();
      activeAudio.currentTime = 0;
      activeAudio = null;
    }
    activeVoiceId = null;
    voiceListEl.querySelectorAll('.voice-card').forEach((card) => {
      card.classList.remove('playing');
      const btn = card.querySelector('.play-btn');
      if (btn) btn.textContent = '▶';
    });
  }

  VOICES.forEach((v) => {
    const card = document.createElement('div');
    card.className = 'voice-card';
    card.dataset.vid = v.id;
    card.innerHTML = `
      <div class="voice-info">
        <strong>${v.name}</strong>
        <span>${v.note}</span>
      </div>
      <button class="play-btn" aria-label="Escuchar muestra de ${v.name}" title="Escuchar muestra">▶</button>
    `;
    const btn = card.querySelector('.play-btn');
    btn.addEventListener('click', () => {
      if (activeVoiceId === v.id) {
        stopVoice();
        return;
      }
      stopVoice();
      const audio = new Audio(`../voices/previews/${v.id}.wav`);
      activeAudio = audio;
      activeVoiceId = v.id;
      card.classList.add('playing');
      btn.textContent = '■';

      audio.addEventListener('ended', stopVoice);
      audio.addEventListener('error', () => {
        stopVoice();
        btn.title = 'Muestra disponible al abrir desde la carpeta del proyecto';
      });
      audio.play().catch(() => {
        stopVoice();
      });
    });
    voiceListEl.appendChild(card);
  });

  // --- 4. Tabs de rendimiento / hardware ---
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanels = document.querySelectorAll('.tab-panel');

  tabBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      tabBtns.forEach((b) => {
        const active = b.dataset.tab === target;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', String(active));
      });
      tabPanels.forEach((panel) => {
        panel.classList.toggle('active', panel.id === `tab-${target}`);
      });
    });
  });

  // --- 5. Copiar comando y menú móvil ---
  document.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const text = btn.dataset.copy || '';
      try {
        await navigator.clipboard.writeText(text);
        const orig = btn.textContent;
        btn.textContent = '¡Copiado!';
        setTimeout(() => { btn.textContent = orig; }, 1600);
      } catch {
        btn.textContent = 'Error';
      }
    });
  });

  const navbar = document.querySelector('.navbar');
  const navToggle = document.getElementById('nav-toggle');
  if (navToggle && navbar) {
    navToggle.addEventListener('click', () => {
      const open = navbar.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
    });
    navbar.querySelectorAll('.nav-links a').forEach((link) => {
      link.addEventListener('click', () => {
        navbar.classList.remove('open');
        navToggle.setAttribute('aria-expanded', 'false');
      });
    });
  }
})();
