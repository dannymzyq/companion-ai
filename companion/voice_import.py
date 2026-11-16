"""Voces propias: el usuario sube una grabación (mp3, wav, m4a…) y se convierte en una voz más del catálogo.

De la grabación se elige el mejor tramo de 5 a 8,5 s, mejor si son frases completas, y se transcribe con Whisper,
porque el servidor de voz necesita el texto exacto de la muestra. Todo se guarda en data/voces (fuera de git, como
el resto de lo del usuario):

    data/voces/voces.json            catálogo: id, nombre, cómo habla de sí, voz ligera parecida
    data/voces/<id>_es.wav + .json   la muestra y su texto (voz/servidor.py las lee de aquí)
    data/voces/previews/<id>.wav     la muestra ▶, que se graba la primera vez que se pide

scripts/importar_voces.py usa las mismas piezas para las voces incluidas (voices/).
"""
import io
import json
import re
import shutil
import threading
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .config import settings

SR = 24000
# Muestras cortas: el servidor de voz guarda en la memoria de vídeo algo por cada voz que usa, más cuanto más larga
# es la muestra, y con muestras de 11 s y la tarjeta llena cada frase pasaba de 1 s a 14 s (12 nov 2026).
MAX_S, MIN_S, SHORTEST_S = 8.5, 5.0, 3.0
MAX_MB = 40                    # unos 40 minutos de mp3: de sobra para una muestra
ANALYZE_S = 180                # de una grabación larga basta con mirar los primeros minutos
NAME_RE = re.compile(r"^[^\W\d_](?:[\w' -]{0,28}[^\W_])?$")
_lock = threading.Lock()

# Voz ligera (Piper) parecida: el modelo de tono más cercano y cuánto subirlo o bajarlo. Tono propio de cada
# modelo medido igual que el de las muestras (f0 abajo, 14 nov 2026).
LIGHT_BASES = [("es_MX-claude-high", 180.0, 1.15), ("es_ES-davefx-medium", 125.0, 1.03)]


class VoiceError(ValueError):
    pass


def folder() -> Path:
    return settings.data_dir / "voces"


def previews() -> Path:
    return folder() / "previews"


# ---------------------------------------------------------------- audio
def decode(src: bytes | str | Path, limit_s: float | None = None) -> np.ndarray:
    """Audio en mono, 24 kHz, float32 (los primeros `limit_s` segundos, si se da)."""
    import av
    out, n = [], 0
    try:
        with av.open(io.BytesIO(src) if isinstance(src, bytes) else str(src)) as c:
            if not c.streams.audio:
                raise VoiceError("Ese archivo no tiene audio.")
            rs = av.AudioResampler(format="s16", layout="mono", rate=SR)
            for frame in c.decode(audio=0):
                for f in rs.resample(frame):
                    out.append(f.to_ndarray().reshape(-1))
                    n += out[-1].size
                if limit_s and n >= limit_s * SR:
                    break
            for f in rs.resample(None):
                out.append(f.to_ndarray().reshape(-1))
    except VoiceError:
        raise
    except Exception as e:  # noqa: BLE001  (av lanza muchos tipos distintos según el formato)
        raise VoiceError("No reconozco ese archivo como audio (prueba con mp3, wav, m4a, ogg o flac).") from e
    if not out:
        raise VoiceError("El archivo de audio está vacío.")
    return np.concatenate(out).astype(np.float32) / 32768


def f0(x: np.ndarray, sr: int = SR) -> float:
    """Tono medio de la voz, en Hz (0 si no se encuentra)."""
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


def _ends(w) -> bool:
    return w.word.strip()[-1:] in ".?!…"


def windows(words, min_s: float = MIN_S, max_s: float = MAX_S, cuts: str = "sentence"):
    """Tramos para la muestra: (inicio, fin, texto, puntuación). Se corta solo tras un punto (`cuts`="sentence"),
    también en las pausas de al menos 0,25 s ("pause") o entre dos palabras cualesquiera ("word"). El tramo nunca
    se mete en la palabra de al lado: el texto tiene que ser exactamente lo que suena."""
    def cut_after(i):                 # ¿se puede cortar después de la palabra i?
        if i == len(words) - 1 or _ends(words[i]) or cuts == "word":
            return True
        return cuts == "pause" and words[i + 1].start - words[i].end >= 0.25
    ends = [i for i in range(len(words)) if cut_after(i)]
    starts = [0] + [i + 1 for i in ends if i + 1 < len(words)]
    for a in starts:
        for b in ends:
            if b < a:
                continue
            t0 = max(0.0, words[a].start - 0.15, words[a - 1].end if a else 0.0)
            t1 = min(words[b].end + 0.3, words[b + 1].start if b + 1 < len(words) else words[b].end + 0.3)
            if min_s <= t1 - t0 <= max_s:
                text = "".join(w.word for w in words[a:b + 1]).strip()
                prob = float(np.mean([w.probability for w in words[a:b + 1]]))
                yield t0, t1, text, prob + 0.02 * (t1 - t0) + (0.05 if _ends(words[b]) else 0)


def best_window(words):
    """El mejor tramo: frases completas si las hay; si no, cortes en pausas o entre palabras; si la grabación es
    corta, lo que haya desde 3 s."""
    for kw in ({}, {"cuts": "pause"}, {"cuts": "word"}, {"cuts": "word", "min_s": SHORTEST_S}):
        best = max(windows(words, **kw), key=lambda w: w[3], default=None)
        if best:
            return best
    return None


def transcribe_words(model, x: np.ndarray, language: str | None = "es") -> list:
    """Palabras con sus tiempos. `model` es un WhisperModel de faster-whisper."""
    x16 = np.interp(np.arange(0, len(x), SR / 16000), np.arange(len(x)), x).astype(np.float32)
    segs, _ = model.transcribe(x16, language=language, word_timestamps=True, beam_size=5,
                               condition_on_previous_text=False)
    return [w for s in segs for w in (s.words or []) if w.word.strip()]


def write_sample(out_dir: Path, name: str, y: np.ndarray, text: str) -> float:
    """Guarda <name>.wav (24 kHz, con fundido y normalizada) y <name>.json con su texto. Devuelve los segundos."""
    y = y.copy()
    fade = int(SR * 0.02)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    y = y / max(1e-6, np.abs(y).max()) * 0.89
    out_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_dir / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    secs = len(y) / SR
    (out_dir / f"{name}.json").write_text(json.dumps(
        {"engine": "f5", "ref_seconds": min(12, round(secs + 0.05, 1)), "nfe_step": 32, "stream_nfe_step": 16,
         "ref_text": text}, ensure_ascii=False, indent=1), encoding="utf-8")
    return secs


SHORT_MIN_S, SHORT_MAX_S = 3.5, 5.2      # muestra corta (voz/servidor.py con VOZ_REF_CORTA, el Mac)


def short_window(model, wav: Path, ref_text: str) -> dict | None:
    """El tramo de 3,5 a 5,2 s de una muestra para la voz rápida, cortado en un final de frase (si no hay, en una
    pausa). `speed` es lo que hay que ajustar la velocidad para que hable al ritmo de la muestra entera: F5 calcula la
    duración de lo que dice por letras por segundo de la muestra, y en un tramo más rápido hablaba un 15 % más deprisa."""
    x = decode(wav)
    words = transcribe_words(model, x)
    for cuts, top in (("sentence", SHORT_MAX_S), ("pause", SHORT_MAX_S), ("sentence", 6.0), ("pause", 6.0)):
        best = max(windows(words, SHORT_MIN_S, top, cuts), key=lambda w: w[3], default=None)
        if best:
            break
    else:
        return None
    t0, t1, text, _ = best
    # El texto, del ref_text de la muestra si las palabras cuadran una a una: Whisper escribe «10» donde suena
    # «diez», y F5 necesita lo que suena tal cual
    mine = ref_text.split()
    if len(mine) == len(words):
        a = next((i for i, w in enumerate(words) if w.start >= t0 - 0.01), 0)
        text = " ".join(mine[a:a + len(text.split())])
    full_rate = len(x) / SR / max(1, len(ref_text.encode("utf-8")))
    short_rate = (t1 - t0) / max(1, len(text.encode("utf-8")))
    return {"start": round(t0, 2), "end": round(t1, 2), "text": text,
            "speed": round(float(np.clip(short_rate / full_rate, 0.8, 1.25)), 3)}


def add_short(model, base: Path) -> bool:
    """Añade `short` al .json de la muestra `base` (sin extensión) si no lo tiene. True si lo añadió."""
    cfg_path = base.with_suffix(".json")
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if "short" in cfg or not cfg.get("ref_text") or not base.with_suffix(".wav").is_file():
        return False
    cfg["short"] = short_window(model, base.with_suffix(".wav"), cfg["ref_text"]) or False   # False: no tiene tramo
    tmp = cfg_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(cfg_path)
    return bool(cfg["short"])


def backfill_short(model) -> int:
    """Las voces propias creadas antes de la muestra corta: se les añade una vez (unos segundos por voz)."""
    n = 0
    for v in custom():
        try:
            n += add_short(model, folder() / f"{v['id']}_es")
        except Exception:  # noqa: BLE001  (una muestra rara no frena el resto)
            pass
    return n


def light_for(pitch: float) -> dict:
    """La voz ligera más parecida en tono (no es la misma voz: Piper no clona)."""
    if pitch <= 0:
        return {"model": LIGHT_BASES[0][0], "pitch": 1.0, "speed": LIGHT_BASES[0][2]}
    model, base, speed = min(LIGHT_BASES, key=lambda b: abs(np.log(pitch / b[1])))
    return {"model": model, "pitch": round(float(np.clip(pitch / base, 0.75, 1.25)), 2), "speed": speed}


# ---------------------------------------------------------------- catálogo
def _catalog_path() -> Path:
    return folder() / "voces.json"


def custom() -> list[dict]:
    """Las voces propias, con el mismo formato que voices.json."""
    try:
        data = json.loads(_catalog_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for v in data if isinstance(data, list) else []:
        if (isinstance(v, dict) and re.fullmatch(r"p_[a-z0-9_]{1,30}", str(v.get("id", "")))
                and (folder() / f"{v['id']}_es.wav").is_file()):
            out.append({**v, "tts_voice": f"{v['id']}_es", "custom": True})
    return out


def _save(items: list[dict]):
    folder().mkdir(parents=True, exist_ok=True)
    keep = [{k: v[k] for k in ("id", "name", "speaks", "note", "light", "pitch_hz") if k in v} for v in items]
    tmp = _catalog_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_catalog_path())


def clean_name(name: str) -> str:
    name = " ".join(unicodedata.normalize("NFC", str(name or "")).split())
    if not NAME_RE.match(name):
        raise VoiceError("Ponle un nombre de 1 a 30 letras (puede llevar espacios).")
    return name


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:24] or "voz"


def create(data: bytes, name: str, speaks: str = "", model=None, taken: set[str] = frozenset()) -> dict:
    """Convierte la grabación en una voz propia y la añade al catálogo. `model` es el WhisperModel del oído;
    `taken`, los nombres de las voces que ya existen (no se repiten)."""
    name = clean_name(name)
    if name.lower() in {t.lower() for t in taken} | {v["name"].lower() for v in custom()}:
        raise VoiceError(f"Ya hay una voz que se llama {name}: ponle otro nombre.")
    if model is None:
        raise VoiceError("El oído todavía está cargando: inténtalo en unos segundos.")
    x = decode(data, ANALYZE_S)
    if len(x) < SR * SHORTEST_S:
        raise VoiceError("La grabación es muy corta: hacen falta al menos 5 segundos de alguien hablando.")
    words = transcribe_words(model, x, language=None)
    best = best_window(words)
    if not best:
        raise VoiceError("No encontré un tramo claro de habla de al menos 3 segundos. Prueba con una grabación "
                         "de una sola persona hablando, sin música de fondo.")
    t0, t1, text, _ = best
    y = x[int(t0 * SR):int(t1 * SR)]
    pitch = f0(y)
    with _lock:
        items = custom()
        base, n = f"p_{_slug(name)}", 2
        vid = base
        while any(v["id"] == vid for v in items):
            vid, n = f"{base}_{n}", n + 1
        secs = write_sample(folder(), f"{vid}_es", y, text)
        try:
            add_short(model, folder() / f"{vid}_es")
        except Exception:  # noqa: BLE001  (sin tramo corto la voz funciona igual, con la muestra entera)
            pass
        entry = {"id": vid, "name": name, "speaks": speaks if speaks in ("f", "m") else ("m" if 0 < pitch < 160 else "f"),
                 "note": "Tu voz", "light": light_for(pitch), "pitch_hz": round(pitch)}
        _save([*items, entry])
    return {**entry, "tts_voice": f"{vid}_es", "custom": True, "seconds": round(secs, 1)}


def remove(voice_id: str):
    with _lock:
        items = custom()
        if not any(v["id"] == voice_id for v in items):
            raise VoiceError("Esa voz no es una de las tuyas.")
        _save([v for v in items if v["id"] != voice_id])
        for p in (folder() / f"{voice_id}_es.wav", folder() / f"{voice_id}_es.json", previews() / f"{voice_id}.wav"):
            p.unlink(missing_ok=True)


def is_custom(tts_voice: str) -> bool:
    return tts_voice.startswith("p_")


def copy_to(tts_voice: str, dst_dir: Path):
    """Copia la muestra a otra carpeta de voces (cuando VOICES_DIR apunta fuera del companion)."""
    for ext in (".wav", ".json"):
        src = folder() / f"{tts_voice}{ext}"
        if src.is_file():
            shutil.copy2(src, dst_dir / src.name)
