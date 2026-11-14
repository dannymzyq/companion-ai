"""Comprobar que la voz dijo TODO el texto (el de los subtítulos) antes de que suene.

El modelo de voz (F5-TTS) es aleatorio: cada vez que dice una frase sale algo distinto y, a veces, se come una
palabra («retomarlo en media hora» → «remedia hora») o corta la última. Medido el 13 nov 2026: ~9 % de palabras
perdidas o cambiadas. Por eso cada frase se escucha con Whisper (el mismo del oído, ya cargado) y, si falta una
palabra con contenido, se vuelve a generar y se queda la mejor.
"""
import difflib
import re
import unicodedata

import numpy as np

# palabras que Whisper escribe distinto sin que falten: interjecciones, números en cifra
_IGNORE = {"ay", "uy", "eh", "ah", "oh", "mmm", "mm", "hmm", "ey", "oye", "bueno", "pues"}
_NUMBERS = {"cero", "uno", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once",
            "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte",
            "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa", "cien", "ciento", "mil",
            "media", "medio"}


def _words(s: str) -> list[str]:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zñ0-9 ]+", " ", s).split()


def heard(model, pcm24: bytes) -> str:
    """Lo que se oye en ese audio (PCM 16 bits, 24 kHz)."""
    x = np.frombuffer(pcm24, dtype=np.int16).astype(np.float32) / 32768
    if len(x) < 2400:
        return ""
    x16 = np.interp(np.arange(0, len(x), 1.5), np.arange(len(x)), x).astype(np.float32)
    segs, _ = model.transcribe(x16, language="es", beam_size=1, condition_on_previous_text=False,
                               without_timestamps=True, vad_filter=False)
    return " ".join(s.text.strip() for s in segs)


def _sound(w: str) -> str:
    """Cómo suena una palabra, para no confundir ortografía con pronunciación («Danny» = «Dani», «vale» = «bale»)."""
    w = re.sub(r"y$", "i", w)
    w = re.sub(r"(.)\1+", r"\1", w)                       # letras dobles
    for a, b in (("qu", "k"), ("c(?=[ei])", "s"), ("z", "s"), ("c", "k"), ("v", "b"), ("ll", "y"), ("h", ""), ("w", "u")):
        w = re.sub(a, b, w)
    return w


def _same(w: str, o: str) -> bool:
    return w == o or _sound(w) == _sound(o) or difflib.SequenceMatcher(None, _sound(w), _sound(o)).ratio() >= 0.75


def missing(expected: str, got: str) -> list[str]:
    """Palabras del texto que no se oyen (con tolerancia: «Danny»≈«Dani», «cinco»≈«5»)."""
    a, b = _words(expected), _words(got)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    lost: list[str] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or op == "insert":
            continue
        others = b[j1:j2]
        for w in a[i1:i2]:
            if w in _IGNORE:
                continue
            if w in _NUMBERS and any(o.isdigit() for o in others):
                continue
            if any(_same(w, o) for o in others):
                continue
            lost.append(w)
    return lost


def bad(lost: list[str]) -> bool:
    """¿Merece repetirse? Una palabra con contenido perdida, o dos cortas."""
    return any(len(w) >= 4 for w in lost) or len(lost) >= 2
