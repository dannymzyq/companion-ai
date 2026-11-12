"""Prueba las piezas por separado: etiquetas, voz (nodo GPU), detección de voz y oído (Whisper).

    .venv\\Scripts\\python.exe scripts\\prueba_componentes.py
"""
import asyncio
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion import tts  # noqa: E402
from companion.config import settings  # noqa: E402
from companion.stt import Transcriber  # noqa: E402
from companion.tags import TagStream  # noqa: E402
from companion.vad import FRAME, StreamingVAD  # noqa: E402

FRASE = "Hola Mika, ¿me puedes decir qué hora es en este momento?"


def prueba_etiquetas():
    p = TagStream()
    texto = ("[emo:feliz] [gesto:saludar] ¡Hola, Danny! Qué gusto verte. [emo:pens" "ativa] A ver, déjame pensar un "
             "momento en eso. **Listo**, ya lo tengo. [recordar: Le gusta el café sin azúcar]")
    frases = []
    for i in range(0, len(texto), 7):                 # llega en trocitos, como del LLM
        frases += p.feed(texto[i:i + 7])
    frases += p.flush()
    for f in frases:
        print("   ", f)
    assert frases[0].emotion == "feliz" and frases[0].gestures == ["saludar"], frases[0]
    assert any(f.emotion == "pensativa" for f in frases)
    assert all("[" not in f.text and "*" not in f.text for f in frases)
    assert p.memories == ["Le gusta el café sin azúcar"], p.memories
    print("etiquetas: OK")


async def prueba_voz() -> np.ndarray:
    print("nodo de voz disponible:", await tts.available(), "| token leído:", bool(settings.tts_token))
    t0, first, pcm = time.perf_counter(), None, b""
    async for chunk in tts.stream_speech(FRASE, settings.tts_voice):
        first = first or time.perf_counter() - t0
        pcm += chunk
    audio = np.frombuffer(pcm, dtype=np.int16)
    print(f"voz: primer trozo {first:.2f}s, total {time.perf_counter() - t0:.2f}s, {len(audio) / 24000:.1f}s de audio")
    return audio


def a_16k(audio24: np.ndarray) -> np.ndarray:
    x = audio24.astype(np.float32) / 32768
    n = int(len(x) * 16000 / 24000)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def prueba_vad(audio: np.ndarray):
    vad = StreamingVAD()
    silencio = np.zeros(16000, dtype=np.float32)
    señal = np.concatenate([silencio, audio, silencio])
    probs = [vad.prob(señal[i:i + FRAME]) for i in range(0, len(señal) - FRAME, FRAME)]
    n = 16000 // FRAME
    print(f"vad: silencio inicial {max(probs[:n - 2]):.2f} máx · habla {np.mean(probs[n + 3:-n - 3]):.2f} media · "
          f"silencio final {max(probs[-n + 8:]):.2f} máx")
    assert max(probs[:n - 2]) < 0.3 and np.mean(probs[n + 3:-n - 3]) > 0.6
    print("vad: OK")


def prueba_oido(audio: np.ndarray):
    t = Transcriber(settings.stt_model, settings.stt_device, settings.stt_compute, settings.stt_language)
    t0 = time.perf_counter()
    t.load()
    print(f"whisper: {t.model_name} en {t.device} (carga {time.perf_counter() - t0:.1f}s) error={t.error}")
    for _ in range(2):
        t0 = time.perf_counter()
        texto = t.transcribe(audio)
        print(f"oído: {time.perf_counter() - t0:.2f}s → {texto!r}")
    print("silencio →", repr(t.transcribe(np.zeros(16000, dtype=np.float32))))


async def main():
    prueba_etiquetas()
    audio = a_16k(await prueba_voz())
    prueba_vad(audio)
    prueba_oido(audio)


if __name__ == "__main__":
    asyncio.run(main())
