"""Conversación de prueba contra el servidor en marcha, sin micrófono ni interfaz.

Genera una pregunta con la propia voz del nodo GPU, la envía como si fuera el micrófono y muestra
lo que responde el companion con sus tiempos. Con --interrumpir, vuelve a hablar encima de la respuesta.

    .venv\\Scripts\\python.exe scripts\\prueba_ws.py [--texto "hola"] [--interrumpir]
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*: servidor, datos y modelos de prueba, no los reales)

if "--local" in sys.argv:                 # con el cerebro local (Ollama) en vez de Gemini
    import os
    os.environ["LLM_PROVIDER"] = "local"

from companion import tts  # noqa: E402
from companion.config import settings  # noqa: E402

FRAME = 512


async def voz_16k(frase: str) -> np.ndarray:
    pcm = b"".join([c async for c in tts.stream_speech(frase, settings.tts_voice)])
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = int(len(x) * 16000 / 24000)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=f"ws://{settings.host}:{settings.port}/ws")
    ap.add_argument("--frase", default="Hola Mika, me llamo Danny y me encanta el café sin azúcar. ¿Qué me recomiendas para concentrarme esta tarde?")
    ap.add_argument("--texto", default="", help="envía texto escrito en vez de voz")
    ap.add_argument("--interrumpir", action="store_true")
    ap.add_argument("--local", action="store_true", help="usa el cerebro local (Ollama) en vez de Gemini")
    args = ap.parse_args()

    habla = None if args.texto else await voz_16k(args.frase)
    corte = await voz_16k("Espera, espera, mejor cuéntame otra cosa.") if args.interrumpir else None
    silencio = np.zeros(FRAME, dtype=np.int16)

    async with connect(args.url, max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print("hello:", {k: hello[k] for k in ("name", "llm", "stt", "tts", "adult", "model")})
        while not hello["stt"]["ready"]:
            await asyncio.sleep(1)
            print("  (esperando a que cargue Whisper…)")
            import httpx
            hello["stt"] = httpx.get(f"http://{settings.host}:{settings.port}/api/config").json()["stt"]

        marca = {"t": time.perf_counter()}
        estado = {"audio": 0, "fin": False, "interrumpido": False, "primer_audio": None}

        async def microfono():
            cola = [] if habla is None else [habla[i:i + FRAME] for i in range(0, len(habla) - FRAME, FRAME)]
            for f in cola:
                await ws.send(f.tobytes())
                await asyncio.sleep(FRAME / 16000)
            marca["t"] = time.perf_counter()
            if habla is not None:
                print(f"[{0:5.2f}s] (el usuario dejó de hablar)")
            enviado_corte = False
            while not estado["fin"]:
                if corte is not None and not enviado_corte and estado["audio"] > 24000 * 2 * 1.0:
                    enviado_corte = True
                    print(f"[{time.perf_counter() - marca['t']:5.2f}s] (el usuario interrumpe)")
                    for i in range(0, len(corte) - FRAME, FRAME):
                        await ws.send(corte[i:i + FRAME].tobytes())
                        await asyncio.sleep(FRAME / 16000)
                await ws.send(silencio.tobytes())
                await asyncio.sleep(FRAME / 16000)

        async def escucha():
            if args.texto:
                await ws.send(json.dumps({"type": "text", "text": args.texto}))
            respuestas = 0
            async for msg in ws:
                t = time.perf_counter() - marca["t"]
                if isinstance(msg, bytes):
                    if estado["primer_audio"] is None:
                        estado["primer_audio"] = t
                        print(f"[{t:5.2f}s] ♪ primer audio")
                    estado["audio"] += len(msg)
                    continue
                ev = json.loads(msg)
                print(f"[{t:5.2f}s] {ev}")
                if ev["type"] == "interrupt":
                    estado["interrumpido"] = True
                    estado["primer_audio"] = None
                if ev["type"] in ("reply_end", "error"):
                    respuestas += 1
                    if not args.interrumpir or estado["interrumpido"] or ev["type"] == "error":
                        await ws.send(json.dumps({"type": "playback_end"}))
                        await asyncio.sleep(0.3)
                        estado["fin"] = True
                        return

        await asyncio.gather(microfono(), escucha())
        print(f"audio recibido: {estado['audio'] / 48000:.1f}s")


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
