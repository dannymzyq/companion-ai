(() => {
  'use strict';

  // --- 1. Simulador interactivo de estados en el Hero ---
  const DEMO_STATES = {
    idle: {
      status: 'Lista para hablar',
      emo: 'feliz',
      mode: 'En vivo · Gemini Live',
      user: 'Tú: «Mika, pon música lofi en Spotify y recuérdame en 20 minutos revisar el correo»',
      ai: '«¡Listo! Ya puse tu lista lofi en segundo plano sin sacarte de lo que hacías, y en 20 minutos te aviso.»'
    },
    listening: {
      status: 'Escuchándote…',
      emo: 'atenta',
      mode: 'Audio 16 kHz · Silero VAD',
      user: 'Tú: «Oye, ¿ves lo que hay en mi pantalla? Creo que me equivoqué en esa fórmula…»',
      ai: 'Captando tu voz en tiempo real · Puedes interrumpirla con naturalidad en cualquier momento.'
    },
    thinking: {
      status: 'Pensando…',
      emo: 'pensativa',
      mode: 'Mirada en vivo · 60 fps',
      user: 'Tú: «Oye, ¿ves lo que hay en mi pantalla? Creo que me equivoqué en esa fórmula…»',
      ai: 'Analizando la ventana compartida y el contexto reciente de la conversación…'
    },
    speaking: {
      status: 'Hablando (24 kHz nativa)',
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
    if (elStatus) elStatus.textContent = info.status;
    if (elEmo) elEmo.textContent = info.emo;
    if (elMode) elMode.textContent = info.mode;
    if (elUser) elUser.textContent = info.user;
    if (elAi) elAi.textContent = info.ai;
    stateBtns.forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.demoState === state);
    });
  }

  stateBtns.forEach((btn) => {
    btn.addEventListener('click', () => setDemoState(btn.dataset.demoState));
  });

  // --- 2. Explorador interactivo de los 4 modos de Cerebro y voz (v0.9.1+) ---
  const MODES = {
    live: {
      badge: 'Recomendado · Sesiones largas estables',
      title: 'Conversación en vivo',
      desc: 'Conexión directa por WebSocket con voz nativa de 24 kHz, visión de cámara/pantalla con sonido (compatible con Discord), memoria duradera sin interrumpir la voz y reconexión fluida de contexto, sin cargar modelos en tu GPU.',
      providers: ['Gemini Live', 'OpenAI Realtime', 'xAI Grok Voice', 'Qwen Omni Realtime', 'Servidor propio'],
      stats: [
        { label: 'VRAM usada', value: '0 MB' },
        { label: 'Voz', value: 'Nativa 24 kHz' },
        { label: 'Memoria en vivo', value: 'Silenciosa' },
        { label: 'Ideal para', value: 'Jugar y multitarea' }
      ]
    },
    hybrid: {
      badge: 'Mejor equilibrio',
      title: 'Nube + voz en tu PC',
      desc: 'Combina la inteligencia de los mejores modelos en la nube con tu propia voz clonada localmente mediante F5-TTS (o Piper en CPU) y oído local con Whisper.',
      providers: ['Gemini', 'OpenAI', 'Anthropic', 'xAI', 'DeepSeek', 'Qwen', 'Groq', 'Cerebras', 'Together'],
      stats: [
        { label: 'VRAM voz', value: '~1,5 GB' },
        { label: 'Voz', value: 'F5-TTS clonada' },
        { label: 'Oído', value: 'Whisper local' },
        { label: 'Relevo cuotas', value: 'Automático' }
      ]
    },
    cloud: {
      badge: 'Ultra ligero',
      title: 'Solo nube',
      desc: 'Mueve el cerebro, el oído (Groq Whisper gratuito o Gemini) y las voces neuronales a la nube. Tu PC apenas usa 62 MB de RAM y menos del 1 % de CPU.',
      providers: ['Gemini Flash', 'Groq Whisper', 'Edge Neural', 'OpenAI', 'Anthropic', 'DeepSeek'],
      stats: [
        { label: 'VRAM usada', value: '0 MB' },
        { label: 'RAM reposo', value: '62 MB' },
        { label: 'Pico de CPU', value: '< 1 %' },
        { label: 'Sin GPU', value: '100 % compatible' }
      ]
    },
    local: {
      badge: 'Privacidad absoluta',
      title: '100 % en tu PC',
      desc: 'Nada sale de tu equipo. Todo corre en tu carpeta con Ollama en Windows o aceleración MLX en Apple Silicon, Whisper local y voz F5-TTS o Piper.',
      providers: ['Ollama', 'Apple Silicon MLX', 'Gemma 4 E2B / E4B / 12B', 'Qwen 3', 'F5-TTS / Piper'],
      stats: [
        { label: 'Datos en la nube', value: '0 bytes' },
        { label: 'Velocidad Mac', value: '124–173 tok/s' },
        { label: 'Velocidad RTX', value: '110–250 tok/s' },
        { label: 'Sin internet', value: 'Funciona offline' }
      ]
    }
  };

  const modeBtns = document.querySelectorAll('[data-mode]');
  const modeDetailEl = document.getElementById('mode-detail');

  function renderMode(key) {
    const m = MODES[key] || MODES.live;
    modeBtns.forEach((btn) => {
      const active = btn.dataset.mode === key;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    if (!modeDetailEl) return;
    modeDetailEl.innerHTML = `
      <div>
        <span class="mode-badge">${m.badge}</span>
        <h3>${m.title}</h3>
        <p>${m.desc}</p>
        <div class="mode-providers">
          ${m.providers.map((p) => `<span>${p}</span>`).join('')}
        </div>
      </div>
      <div class="mode-stats">
        ${m.stats.map((s) => `
          <div class="mode-stat-box">
            <span>${s.label}</span>
            <strong>${s.value}</strong>
          </div>
        `).join('')}
      </div>
    `;
  }

  modeBtns.forEach((btn) => {
    btn.addEventListener('click', () => renderMode(btn.dataset.mode));
  });
  renderMode('live');

  // --- 3. Explorador de las 8 personalidades reales ---
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
    if (!pillsEl || !detailEl) return;
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

  if (pillsEl) {
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
  }

  // --- 4. Catálogo de las 9 voces con reproducción real ---
  const VOICES = [
    { id: 'mika', name: 'Mika', note: 'Voz original' },
    { id: 'kenji', name: 'Kenji', note: 'Medio-grave' },
    { id: 'natsumi', name: 'Natsumi', note: 'Muy agudo' },
    { id: 'ayaka', name: 'Ayaka', note: 'Agudo' },
    { id: 'chiaki', name: 'Chiaki', note: 'Medio-agudo' },
    { id: 'akira', name: 'Akira', note: 'Tono medio' },
    { id: 'goro', name: 'Goro', note: 'Pausado' },
    { id: 'ryo', name: 'Ryo', note: 'Tono grave' },
    { id: 'satoshi', name: 'Satoshi', note: 'Muy grave' }
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
    if (!voiceListEl) return;
    voiceListEl.querySelectorAll('.voice-card').forEach((card) => {
      card.classList.remove('playing');
      const btn = card.querySelector('.play-btn');
      if (btn) btn.textContent = '▶';
    });
  }

  if (voiceListEl) {
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
        const audio = new Audio(`previews/${v.id}.wav`);
        activeAudio = audio;
        activeVoiceId = v.id;
        card.classList.add('playing');
        btn.textContent = '■';

        audio.addEventListener('ended', stopVoice);
        audio.addEventListener('error', () => {
          stopVoice();
          btn.title = 'No se pudo cargar la muestra de audio';
        });
        audio.play().catch(() => {
          stopVoice();
        });
      });
      voiceListEl.appendChild(card);
    });
  }

  // --- 5. Tabs de rendimiento / hardware ---
  const tabBtns = document.querySelectorAll('[data-tab]');
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

  // --- 6. Copiar comando ---
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

  // --- 7. Navbar glass scroll + menú móvil ---
  const navbar = document.getElementById('navbar');
  const navToggle = document.getElementById('nav-toggle');

  function handleScroll() {
    if (navbar) {
      navbar.classList.toggle('scrolled', window.scrollY > 16);
    }
  }
  window.addEventListener('scroll', handleScroll, { passive: true });
  handleScroll();

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

  // --- 8. Scroll Reveal (estilo Apple) ---
  const revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.05, rootMargin: '0px 0px -10px 0px' }
    );
    revealEls.forEach((el) => observer.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  }
})();
