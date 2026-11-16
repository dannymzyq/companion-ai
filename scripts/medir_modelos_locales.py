"""Mide los modelos locales de Ollama: memoria que ocupan cargados, velocidad, si ven imágenes y con qué motor
corren (en el Mac, MLX o llama.cpp). Solo habla con Ollama: no arranca el companion ni gasta cuota.

    python scripts/medir_modelos_locales.py gemma4:12b-mlx gemma4:e4b-mlx gemma4:e4b-it-qat
    python scripts/medir_modelos_locales.py --descargar gemma4:e4b-mlx      (lo descarga si falta)

No lo corras mientras el usuario conversa con el modelo local: Ollama tiene una sola cola.
Cada modelo se descarga de la memoria al terminar (keep_alive 0)."""
import base64
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
import zlib

URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PREGUNTA = ("Eres una compañera amable que charla en español. En dos o tres frases, cuéntame qué harías en una "
            "tarde de lluvia.")


def pedir(path: str, body: dict | None = None, timeout: float = 600) -> dict:
    req = urllib.request.Request(f"{URL}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def imagen_roja() -> str:
    """PNG de 64×64 todo rojo (para ver si el modelo mira la imagen de verdad)."""
    fila = b"\x00" + b"\xff\x00\x00" * 64
    raw = zlib.compress(fila * 64)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def descargar(modelo: str):
    req = urllib.request.Request(f"{URL}/api/pull", data=json.dumps({"model": modelo, "stream": True}).encode())
    with urllib.request.urlopen(req, timeout=None) as r:
        ultimo = 0.0
        for linea in r:
            d = json.loads(linea or b"{}")
            if d.get("error"):
                raise SystemExit(f"{modelo}: {d['error']}")
            if d.get("total") and time.monotonic() - ultimo > 10:
                ultimo = time.monotonic()
                print(f"  {modelo}: {d.get('completed', 0) / 2**30:.1f} de {d['total'] / 2**30:.1f} GB", flush=True)


def motor() -> str:
    """Columna de `ollama ps` (en el Mac dice si corre en MLX)."""
    try:
        return subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"(sin ollama ps: {type(e).__name__})"


def medir(modelo: str) -> dict:
    info = pedir("/api/show", {"model": modelo})
    out = {"modelo": modelo, "capacidades": info.get("capabilities"),
           "cuantizacion": (info.get("details") or {}).get("quantization_level"),
           "formato": (info.get("details") or {}).get("format")}
    t = time.perf_counter()
    pedir("/api/generate", {"model": modelo, "keep_alive": "5m", "options": {"num_ctx": 8192}})
    out["carga_s"] = round(time.perf_counter() - t, 1)
    vel = []
    for _ in range(3):
        r = pedir("/api/chat", {"model": modelo, "stream": False, "keep_alive": "5m", "options": {"num_ctx": 8192},
                                "messages": [{"role": "user", "content": PREGUNTA}]})
        vel.append(r["eval_count"] / (r["eval_duration"] / 1e9))
        out["primer_token_s"] = round((r.get("prompt_eval_duration", 0) + r.get("load_duration", 0)) / 1e9, 2)
    out["tokens_s"] = [round(v, 1) for v in vel]
    out["respuesta"] = r["message"]["content"][:160]
    if "vision" in (out["capacidades"] or []):
        t = time.perf_counter()
        r = pedir("/api/chat", {"model": modelo, "stream": False, "keep_alive": "5m", "options": {"num_ctx": 8192},
                                "messages": [{"role": "user", "content": "¿De qué color es esta imagen? Una palabra.",
                                              "images": [imagen_roja()]}]})
        out["imagen"] = {"respuesta": r["message"]["content"].strip()[:60], "s": round(time.perf_counter() - t, 1)}
    ps = {m["name"]: m for m in pedir("/api/ps").get("models", [])}
    m = ps.get(modelo) or ps.get(f"{modelo}:latest") or {}
    out["memoria_gb"] = round(m.get("size", 0) / 2**30, 2)
    out["memoria_gpu_gb"] = round(m.get("size_vram", 0) / 2**30, 2)
    out["ollama_ps"] = motor()
    pedir("/api/generate", {"model": modelo, "keep_alive": 0})
    return out


def main():
    args = sys.argv[1:]
    bajar = "--descargar" in args
    modelos = [a for a in args if not a.startswith("--")]
    if not modelos:
        raise SystemExit(__doc__)
    print("Ollama", pedir("/api/version").get("version"))
    instalados = {m["name"] for m in pedir("/api/tags").get("models", [])}
    resultados = []
    for modelo in modelos:
        if modelo not in instalados and f"{modelo}:latest" not in instalados:
            if not bajar:
                print(f"{modelo}: no está descargado (usa --descargar)")
                continue
            descargar(modelo)
        r = medir(modelo)
        resultados.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=1), flush=True)
    print("\nResumen:")
    for r in resultados:
        img = r.get("imagen", {}).get("respuesta", "no ve imágenes")
        print(f"  {r['modelo']:22} {r['memoria_gb']:5.1f} GB  {max(r['tokens_s']):6.1f} tok/s  carga {r['carga_s']} s"
              f"  formato {r['formato']}/{r['cuantizacion']}  imagen: {img}")


if __name__ == "__main__":
    main()
