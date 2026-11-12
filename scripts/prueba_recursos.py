"""Prueba la elección de modelo local y de voz según los recursos de la PC, contra el servidor de prueba:

1. La recomendación (qué cabe en la tarjeta con cada voz).
2. Cada modelo local del catálogo: se elige, queda guardado, es el que Ollama carga (y el anterior se descarga),
   y responde a un turno escrito; se anota cuánta memoria de vídeo ocupa y a qué velocidad va.
3. La voz ligera (Piper): una muestra de cada voz y un turno completo con ella.

Usa Ollama: no la corras mientras se conversa con el cerebro local (frena los turnos).

    .venv\\Scripts\\python.exe scripts\\prueba_recursos.py [modelo ...]
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402

from companion import profile  # noqa: E402
from companion.config import settings  # noqa: E402

OLLAMA = settings.ollama_url


async def turno(texto: str) -> dict:
    """Un turno escrito por el WebSocket: respuesta, avisos, audio recibido y tiempo."""
    out = {"texto": "", "avisos": [], "audio": 0, "error": ""}
    t = time.perf_counter()
    async with connect(f"ws://127.0.0.1:{_prueba.PORT}/ws", max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "text", "text": texto}))
        async for msg in ws:
            if isinstance(msg, bytes):
                out["audio"] += len(msg)
                out.setdefault("primer_audio", time.perf_counter() - t)
                continue
            ev = json.loads(msg)
            if ev["type"] == "notice":
                out["avisos"].append(ev["message"])
            if ev["type"] in ("reply_end", "error"):
                out["texto" if ev["type"] == "reply_end" else "error"] = ev.get("text") or ev.get("message", "")
                await ws.send(json.dumps({"type": "playback_end"}))
                break
    out["segundos"] = time.perf_counter() - t
    return out


def cargados() -> dict:
    return {m["name"]: round(m.get("size_vram", 0) / 2**30, 1) for m in httpx.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])}


async def main():
    api = httpx.Client(base_url=_prueba.URL, timeout=120)
    s = api.get("/api/setup").json()
    r = s["resources"]
    print(f"1. recursos   : tarjeta {r['total_gb']} GB ({r['tier']}) · queda para el modelo: {r['room']} · voz recomendada: {r['recommended_engine']} "
          f"· modelo recomendado: {r['recommended_model']} · voz ligera instalada: {s['voice_engine']['light_installed']}")
    for m in s["local"]["models"] + s["local"]["others"]:
        print(f"   {m['id']:20} {m['vram_gb']:4} GB · cabe con {[k for k, v in m['fits'].items() if v] or 'ninguna'}"
              f"{'' if m.get('installed', True) else ' · sin descargar'}")
    for gb in (0, 4, 6, 8, 12, 16, 24):     # la misma cuenta en otras tarjetas (sin tocar nada)
        x = profile.resources({"total": gb * 1024, "used": 0} if gb else None, is_cloud=False, local_model=profile.LOCAL_MODELS[0]["id"], node_ok=True)
        y = profile.resources({"total": gb * 1024, "used": 0} if gb else None, is_cloud=True, local_model="", node_ok=True)
        print(f"   tarjeta de {gb:2} GB → local: voz {x['recommended_pair']:8} + {x['recommended_model']:18} · en la nube: voz {y['recommended_engine']}")

    antes = set(cargados())
    elegidos = sys.argv[1:] or [m["id"] for m in s["local"]["models"] if m["installed"]]
    print("2. modelos locales")
    for mid in elegidos:
        cfg = api.post("/api/setup", json={"local_model": mid, "provider": "local"})
        assert cfg.status_code == 200, cfg.text
        limite = time.monotonic() + 90
        while time.monotonic() < limite and mid not in cargados():
            await asyncio.sleep(1)
        await asyncio.sleep(1.5)
        ahora = cargados()
        guardado = json.loads((_prueba.TEST_DIR / "settings.json").read_text(encoding="utf-8"))
        cfg = api.get("/api/config").json()
        res = await turno("Hola, ¿cómo te llamas? Dime en una frase qué puedes hacer por mí.")
        nuestros = [m for m in ahora if m not in antes or m == mid]
        log = [x for x in (_prueba.TEST_DIR / "servidor.log").read_text(encoding="utf-8", errors="replace").splitlines() if f"Local {mid}:" in x]
        print(f"   {mid:20} guardado={guardado.get('local_model') == mid} · en uso={cfg['llm']['model']} · cargados por la prueba={nuestros} "
              f"· vídeo {ahora.get(mid)} GB · ve imágenes={cfg['llm'].get('vision')}\n"
              f"      {res['segundos']:.1f} s · {log[-1].split('· ')[-1] if log else '?'} · avisos={res['avisos']} · error={res['error']!r}\n"
              f"      → {res['texto'][:150]!r}")
        assert guardado.get("local_model") == mid and cfg["llm"]["model"] == mid and cfg["local_model"] == mid, "no quedó en uso el modelo elegido"
        assert mid in ahora and nuestros == [mid], f"cargados: {ahora}"
        assert res["texto"] and not res["error"], res

    print("3. voz ligera")
    assert api.post("/api/setup", json={"voice_engine": "ligera"}).status_code == 200
    for v in s["voices"]:
        t = time.perf_counter()
        w = api.post("/api/voices/preview", json={"id": v["id"], "engine": "ligera"})
        assert w.status_code == 200 and w.content[:4] == b"RIFF" and len(w.content) > 40000, (v["id"], w.status_code)
        (_prueba.TEST_DIR / f"ligera_{v['id']}.wav").write_bytes(w.content)
        print(f"   {v['name']:8} {(len(w.content) - 44) / 48000:4.1f} s de audio en {time.perf_counter() - t:4.2f} s")
    cfg = api.get("/api/config").json()
    res = await turno("Cuéntame en dos frases algo curioso sobre los zorros.")
    print(f"   turno con voz ligera: motor={cfg['voice_engine']} · voz disponible={cfg['tts']} · primer audio a los {res.get('primer_audio', 0):.2f} s "
          f"· {res['audio'] / 48000:.1f} s de audio · {res['texto'][:100]!r}")
    assert cfg["voice_engine"] == "ligera" and cfg["tts"] and res["audio"] > 48000
    api.post("/api/config", json={"provider": "gemini"})       # suelta el modelo local de la prueba
    await asyncio.sleep(3)
    print("   al volver a la nube quedan cargados:", cargados())
    print("OK: cada modelo elegido se guarda, se carga y responde; la voz ligera habla sin el nodo de voz.")


if __name__ == "__main__":
    with _prueba.Servidor():
        asyncio.run(main())
