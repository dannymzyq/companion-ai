"""Prueba de integración real con la Gemini Live API (usa tu GEMINI_API_KEY, datos aislados).

Valida:
  1. Conexión real por WebSocket a BidiGenerateContent (setupComplete).
  2. Turno de texto → audio PCM 24 kHz en streaming + subtítulos en vivo (caption_delta) + reply_end.
  3. Envío de imagen JPEG (visión en vivo) → respuesta describiendo el color de la imagen.

Uso:
  .venv\\Scripts\\python.exe scripts\\prueba_gemini_live.py
"""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Aislar DATA_DIR antes de importar companion para no tocar el historial ni los ajustes del usuario
_tmp = tempfile.TemporaryDirectory(prefix="companion_live_test_", ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = _tmp.name

from PIL import Image  # noqa: E402

from companion import gemini_live, profile, state  # noqa: E402
from companion.config import settings  # noqa: E402
from companion.prompt import load_persona  # noqa: E402
from companion.session import Session  # noqa: E402


class CaptureWS:
    def __init__(self):
        self.events: list[dict] = []
        self.audio = bytearray()
        self.reply_done = asyncio.Event()
        self.first_audio_at: float | None = None

    async def send_text(self, text: str):
        ev = json.loads(text)
        self.events.append(ev)
        if ev.get("type") == "reply_end":
            self.reply_done.set()

    async def send_bytes(self, data: bytes):
        if self.first_audio_at is None:
            self.first_audio_at = time.perf_counter()
        self.audio.extend(data)

    def reset_turn(self):
        self.audio.clear()
        self.reply_done.clear()
        self.first_audio_at = None


class DummyTranscriber:
    ready = False
    device = "cpu"
    engine = "nube"


def make_red_jpeg_b64() -> str:
    img = Image.new("RGB", (256, 256), color=(220, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main():
    # Cargar clave real desde .env o data/settings.json original (solo lectura)
    orig_data = ROOT / "data"
    if not settings.gemini_api_key:
        # Leer clave guardada en el data real si existe
        from companion import secret
        real_settings = orig_data / "settings.json"
        if real_settings.is_file():
            saved = json.loads(real_settings.read_text(encoding="utf-8"))
            raw_key = (saved.get("cloud") or {}).get("key", "")
            if raw_key:
                settings.gemini_api_key = secret.unprotect(raw_key)

    if not settings.gemini_api_key:
        print("ERROR: No hay GEMINI_API_KEY configurada en .env ni en data/settings.json.")
        sys.exit(2)

    settings.cloud_preset = "gemini"
    state.save(
        gemini_live=True,
        provider="gemini",
        cloud={"preset": "gemini", "key": settings.gemini_api_key, "base": settings.gemini_base, "model": ""},
    )
    profile.apply()

    persona = load_persona(settings.persona_path)
    ws = CaptureWS()
    sess = Session(ws, persona, DummyTranscriber())

    try:
        # --- Prueba 1: Turno de texto → voz nativa 24 kHz + subtítulos ---
        print(f"[1/2] Probando turno de texto con {settings.gemini_live_model}...")
        t0 = time.perf_counter()
        await sess.on_message({"type": "text", "text": "Hola, responde con una sola frase corta diciendo que Gemini Live funciona."})
        await asyncio.wait_for(ws.reply_done.wait(), timeout=25)
        first_s = (ws.first_audio_at - t0) if ws.first_audio_at else -1
        dur_s = len(ws.audio) / (gemini_live.OUTPUT_RATE * 2)
        reply = next((e["text"] for e in reversed(ws.events) if e.get("type") == "reply_end"), "")
        print(f"  OK · Primer audio: {first_s:.2f}s · Audio recibido: {len(ws.audio)} bytes ({dur_s:.2f}s a 24 kHz)")
        print(f"  OK · Transcripción: {reply!r}")
        assert len(ws.audio) > 4800, "No se recibió suficiente audio PCM 24 kHz"
        assert reply.strip(), "No se recibió transcripción de salida"

        # --- Prueba 2: Imagen JPEG en vivo (visión) ---
        print("[2/2] Probando visión en vivo (imagen JPEG roja)...")
        ws.reset_turn()
        sess._live_frame_at = 0.0
        await sess.on_message({"type": "frame", "source": "camera", "jpeg": make_red_jpeg_b64()})
        await asyncio.sleep(0.3)
        t1 = time.perf_counter()
        await sess.on_message({"type": "text", "text": "¿De qué color es la imagen que te acabo de mostrar? Responde en una frase muy corta."})
        await asyncio.wait_for(ws.reply_done.wait(), timeout=25)
        first_s2 = (ws.first_audio_at - t1) if ws.first_audio_at else -1
        dur_s2 = len(ws.audio) / (gemini_live.OUTPUT_RATE * 2)
        reply2 = next((e["text"] for e in reversed(ws.events) if e.get("type") == "reply_end"), "")
        print(f"  OK · Primer audio: {first_s2:.2f}s · Audio recibido: {len(ws.audio)} bytes ({dur_s2:.2f}s a 24 kHz)")
        print(f"  OK · Respuesta visión: {reply2!r}")
        assert len(ws.audio) > 2400, "No se recibió audio en el turno de visión"
        assert "roj" in reply2.lower(), f"Se esperaba mención al color rojo, llegó: {reply2!r}"

        # --- Prueba 3: Streaming de audio 16 kHz + Function Calling de acciones (sin ejecutar en la PC) ---
        print("[3/3] Probando streaming de audio 16 kHz + llamada a herramienta (Apple Music)...")
        ws.reset_turn()
        called_actions = []

        async def capture_exec(wanted, trusted, card=False):
            called_actions.extend(wanted)

        sess._live_exec_actions = capture_exec
        # Enviar 0.5 s de silencio PCM 16 kHz en bloques de 100 ms (valida que mediaChunks audio no da 1007)
        silence_100ms = b"\x00\x00" * 1600
        for _ in range(5):
            await sess.on_audio(silence_100ms)
            await asyncio.sleep(0.05)
        t2 = time.perf_counter()
        await sess.on_message({"type": "text", "text": "Abre Apple Music y reproduce La Barca de Luis Miguel."})
        await asyncio.wait_for(ws.reply_done.wait(), timeout=25)
        if sess.side:
            await asyncio.gather(*list(sess.side))
        reply3 = next((e["text"] for e in reversed(ws.events) if e.get("type") == "reply_end"), "")
        print(f"  OK · Tiempo total: {time.perf_counter() - t2:.2f}s · Acciones disparadas: {called_actions}")
        print(f"  OK · Respuesta: {reply3!r}")
        assert called_actions, "Gemini Live no disparó ninguna acción para Apple Music"

        print("\nTODAS LAS PRUEBAS EN VIVO DE GEMINI LIVE API PASARON CORRECTAMENTE.")
    finally:
        await sess.close()
        _tmp.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
