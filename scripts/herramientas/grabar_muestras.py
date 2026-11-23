"""Graba la muestra ▶ de cada voz del catálogo en voices/previews/<voz>.wav, para que oír muestras en la
bienvenida no cargue voces en el nodo de voz (cada voz que el nodo usa le ocupa memoria de vídeo hasta que se
reinicia). Hay que repetirlo si se cambia la muestra de una voz. Instala cada voz en el nodo para grabarla.

    .venv\\Scripts\\python.exe scripts\\herramientas\\grabar_muestras.py [voz ...]
"""
import asyncio
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from companion import profile, tts  # noqa: E402


async def main():
    profile.PREVIEWS.mkdir(exist_ok=True)
    for v in profile.voices():
        if sys.argv[1:] and v["id"] not in sys.argv[1:]:
            continue
        profile.install_voice(v["tts_voice"])
        t = time.perf_counter()
        pcm = b"".join([c async for c in tts.stream_speech(profile.PREVIEW_TEXT.format(name=v["name"]), v["tts_voice"])])
        with wave.open(str(profile.PREVIEWS / f"{v['id']}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(tts.SAMPLE_RATE)
            w.writeframes(pcm)
        print(f"{v['name']:8} {len(pcm) / 2 / tts.SAMPLE_RATE:4.1f} s de audio · tardó {time.perf_counter() - t:4.1f} s")


asyncio.run(main())
