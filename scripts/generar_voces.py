"""Genera las muestras de voz con Piper (voces sintéticas de licencia abierta) y mide su tono.
Para las neutras se sube o baja el tono: se sintetiza más lento/rápido y se reproduce a otra velocidad.

    <entorno con piper-tts>/python.exe scripts/generar_voces.py <carpeta con piper-voices>
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

S = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("piper")      # carpeta con piper-voices/*.onnx (de huggingface.co/rhasspy/piper-voices)
OUT = Path(__file__).resolve().parent.parent / "voices"            # voz/servidor.py las lee de aquí directamente
OUT.mkdir(exist_ok=True)
TEXT = ("Hola, ¿cómo estás? Hoy quiero contarte algo curioso. Ayer, mientras llovía muchísimo, un pequeño zorro gris "
        "cruzó el jardín y se quedó mirando fijamente la ventana. ¡Qué sorpresa tan agradable!")

# nombre → (modelo de Piper, hablante, factor de tono, velocidad)
VOCES = {
    "kenji_es": ("es_ES-davefx-medium", None, 0.76, 1.03),        # la única sintética que queda en el catálogo
}   # las demás voces salen de grabaciones: scripts/importar_voces.py


def read(path):
    with wave.open(str(path)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return x, sr


def f0(x, sr):
    """Tono medio (Hz) por autocorrelación en los tramos con voz."""
    n, hop, out = int(sr * 0.04), int(sr * 0.02), []
    lo, hi = int(sr / 400), int(sr / 60)
    for i in range(0, len(x) - n, hop):
        f = x[i:i + n] * np.hanning(n)
        if np.sqrt(np.mean(f ** 2)) < 0.02:
            continue
        ac = np.correlate(f, f, "full")[n - 1:]
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.45 * ac[0]:
            out.append(sr / k)
    return float(np.median(out)) if out else 0.0


for name, (model, speaker, pitch, speed) in VOCES.items():
    raw = OUT / f"{name}.raw.wav"
    for _ in range(4):                    # la muestra entera tiene que caber en los 12 s que usa el nodo de voz
        cmd = [sys.executable, "-m", "piper", "-m", str(S / "piper-voices" / f"{model}.onnx"), "-f", str(raw),
               "--length-scale", f"{pitch / speed:.3f}", "--sentence-silence", "0.2"]
        if speaker is not None:
            cmd += ["--speaker", str(speaker)]
        r = subprocess.run(cmd, input=TEXT.encode("utf-8"), capture_output=True)
        if r.returncode:
            print(name, "ERROR", r.stderr.decode("utf-8", "replace")[-300:])
            break
        x, sr = read(raw)
        secs = len(x) / sr / pitch
        if secs <= 11.5:
            break
        speed *= secs / 10.9
    if r.returncode:
        continue
    # cambio de tono: se reproduce `pitch` veces más rápido (la duración vuelve a la normal) y se lleva a 24 kHz
    n = int(len(x) / pitch * 24000 / sr)
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    y = y / max(1e-6, np.abs(y).max()) * 0.89
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    raw.unlink()
    secs = len(y) / 24000
    (OUT / f"{name}.json").write_text(json.dumps({"engine": "f5", "ref_seconds": min(12, round(secs + 0.05, 1)), "nfe_step": 32,
                                                  "stream_nfe_step": 16, "ref_text": TEXT}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name:9} {model:22} hablante={speaker} tono×{pitch:.2f} → {secs:4.1f} s · tono medio {f0(y, 24000):5.0f} Hz")


