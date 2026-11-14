"""Convierte grabaciones propias (mp3/wav) en muestras para el servidor de voz. De las grabaciones de cada voz
elige el mejor tramo de frases completas de 5 a 8,5 s, lo transcribe con Whisper
(el servidor necesita el texto exacto de la muestra) y escribe voices/<voz>_es.wav + .json, que voz/servidor.py
lee directamente.

    .venv\\Scripts\\python.exe scripts\\importar_voces.py <carpeta con las grabaciones> [--voz=mika=Mika]
"""
import json
import sys
import wave
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "voices"
SR = 24000
# Muestras cortas: el servidor de voz guarda en la memoria de vídeo algo por cada voz que usa, más cuanto más larga es la
# muestra, y con muestras de 11 s y la tarjeta llena cada frase pasaba de 1 s a 14 s (12 nov 2026).
MAX_S, MIN_S = 8.5, 5.0

# voz del companion → prefijo de los archivos grabados (Natalia1.mp3, Natalia2.mp3…)
VOCES = {"natsumi": "Natalia", "chiaki": "Cristina", "ayaka": "AnaMaria",
         "goro": "Gork", "ryo": "Rocco", "satoshi": "Salvatore", "akira": "Antonio"}


def decode(path: Path) -> np.ndarray:
    """Audio en mono, 24 kHz, float32."""
    out = []
    with av.open(str(path)) as c:
        rs = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for frame in c.decode(audio=0):
            for f in rs.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) / 32768


def f0(x, sr=SR):
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


def windows(words):
    """Tramos de frases completas: (inicio, fin, texto, confianza media)."""
    starts = [0] + [i + 1 for i, w in enumerate(words[:-1]) if w.word.strip()[-1:] in ".?!…"]
    ends = [i for i, w in enumerate(words) if w.word.strip()[-1:] in ".?!…"] or [len(words) - 1]
    for a in starts:
        for b in ends:
            if b <= a:
                continue
            t0, t1 = max(0.0, words[a].start - 0.15), words[b].end + 0.3
            if MIN_S <= t1 - t0 <= MAX_S:
                text = "".join(w.word for w in words[a:b + 1]).strip()
                yield t0, t1, text, float(np.mean([w.probability for w in words[a:b + 1]]))


def main():
    src = Path(sys.argv[1])
    global VOCES
    for arg in sys.argv[2:]:                          # --voz mika=Mika: solo esa voz (archivos Mika*.wav|mp3)
        if arg.startswith("--voz="):
            nombre, prefijo = arg[6:].split("=", 1)
            VOCES = {nombre: prefijo}
    from faster_whisper import WhisperModel

    from companion.stt import _add_cuda_dlls
    _add_cuda_dlls()
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8_float16")
    OUT.mkdir(exist_ok=True)
    for voz, prefijo in VOCES.items():
        best = None
        for path in sorted(p for p in src.glob(f"{prefijo}*") if p.suffix.lower() in (".mp3", ".wav", ".flac", ".m4a")):
            x = decode(path)
            x16 = np.interp(np.arange(0, len(x), SR / 16000), np.arange(len(x)), x).astype(np.float32)
            segs, _ = model.transcribe(x16, language="es", word_timestamps=True, beam_size=5)
            words = [w for s in segs for w in s.words]
            for t0, t1, text, prob in windows(words):
                score = prob + 0.02 * (t1 - t0)              # claro y, a igualdad, largo
                if not best or score > best[0]:
                    best = (score, path.name, x[int(t0 * SR):int(t1 * SR)], text, len(x) / SR)
        if not best:
            print(f"{voz:8} SIN TRAMO VÁLIDO")
            continue
        _, origen, y, text, total = best
        fade = int(SR * 0.02)
        y = y.copy()
        y[:fade] *= np.linspace(0, 1, fade)
        y[-fade:] *= np.linspace(1, 0, fade)
        y = y / max(1e-6, np.abs(y).max()) * 0.89
        name = f"{voz}_es"
        with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((y * 32767).astype(np.int16).tobytes())
        secs = len(y) / SR
        (OUT / f"{name}.json").write_text(json.dumps(
            {"engine": "f5", "ref_seconds": min(12, round(secs + 0.05, 1)), "nfe_step": 32, "stream_nfe_step": 16,
             "ref_text": text}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{voz:8} ← {origen} ({total:.0f} s) · tramo de {secs:.1f} s · tono {f0(y):.0f} Hz · {text!r}")


if __name__ == "__main__":
    main()
