"""Prueba la memoria a largo plazo con el cerebro local: una conversación de once turnos, se cierra la
sesión, se vuelve a entrar y, tras un rato de calma, el tramo antiguo queda resumido como recuerdo. Después
se le pregunta por algo que solo está en ese resumen. Todo escrito, sin voz; nada sale de la PC.

    .venv\\Scripts\\python.exe scripts\\pruebas\\prueba_memoria.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*: aísla datos, modelos y puerto)

os.environ.update(LLM_PROVIDER="local", WATCH_INTERVAL="3")

TURNOS = [
    "Hola. Hoy quiero organizar un viaje a Cusco con mi hermana Lucía.",
    "Queremos ir la segunda semana de marzo, unos cinco días.",
    "A Lucía le da miedo volar, así que estamos pensando ir en bus desde Arequipa.",
    "El presupuesto es de unos dos mil soles para los dos.",
    "Me preocupa el mal de altura, la última vez me sentí fatal.",
    "Sí, buena idea, llevaré pastillas y nos quedaremos un día tranquilo al llegar.",
    "También quiero visitar Machu Picchu, pero aún no compré las entradas.",
    "Recuérdame que tengo que comprar las entradas antes de fin de mes.",
    "Cambiando de tema, estoy aprendiendo a tocar el ukelele.",
    "Llevo dos semanas practicando una canción de los Beatles.",
    "Bueno, ya me voy a dormir. Hasta mañana.",
]


async def turno(ws, texto: str) -> str:
    await ws.send(json.dumps({"type": "text", "text": texto}))
    while True:
        msg = await ws.recv()
        if isinstance(msg, bytes):
            continue
        ev = json.loads(msg)
        if ev["type"] == "reply_end":
            await ws.send(json.dumps({"type": "playback_end"}))
            return ev["text"]
        if ev["type"] == "error":
            raise SystemExit(f"error del companion: {ev['message']}")


async def main():
    api = httpx.Client(base_url=_prueba.URL, timeout=30)
    async with connect(f"ws://127.0.0.1:{_prueba.PORT}/ws", max_size=None) as ws:
        await ws.recv()
        for i, texto in enumerate(TURNOS, 1):
            r = await turno(ws, texto)
            if i in (1, len(TURNOS)):
                print(f"turno {i:2}: {texto!r}\n          → {r[:110]!r}")
    print("sesión cerrada. Recuerdos antes de volver:", {k: len(v) for k, v in api.get("/api/memory").json().items()})

    async with connect(f"ws://127.0.0.1:{_prueba.PORT}/ws", max_size=None) as ws:      # otra sesión, como al día siguiente
        await ws.recv()
        resumen = []
        for _ in range(40):                                # el resumen se hace solo, en un rato de calma
            await asyncio.sleep(1.5)
            resumen = api.get("/api/memory").json()["summaries"]
            if resumen:
                break
        mem = api.get("/api/memory").json()
        print("datos recordados   :", mem["facts"])
        print("resumen del tramo antiguo:", resumen[0] if resumen else "NO SE HIZO")
        assert resumen, "no se resumió la conversación antigua"
        r = await turno(ws, "Oye, ¿te acuerdas de con quién iba a viajar y a dónde? ¿Y qué me daba miedo del viaje?")
        print("pregunta sobre lo antiguo →", repr(r[:260]))
        ok = "cusco" in r.lower() and ("luc" in r.lower() or "hermana" in r.lower())
        print("OK: recuerda la conversación anterior." if ok else "AVISO: la respuesta no menciona Cusco y a Lucía.")


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
