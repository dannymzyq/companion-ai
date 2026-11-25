"""Pronunciación: el texto que va a la VOZ se reescribe como suena (lo que se ve en pantalla no cambia).

· Las palabras en inglés (Apple Music, YouTube, WhatsApp…) la voz las leía como en español («aple músic»): se
  cambian por cómo se pronuncian, escrito a la española («Ápel Miúsik»). La lista está en voices/pronunciacion.json:
  se puede editar (y añadir palabras) sin reiniciar nada.
· «qu» delante de e/i: el modelo de voz a veces dice «cue» («Qué suerte» sonaba «Cuál suerte»); escrito «k» lo
  dice bien siempre (medido con Whisper el 13 nov 2026).
"""
import json
import re

from .config import ROOT

FILE = ROOT / "voices" / "pronunciacion.json"
_cache: tuple[float, list[tuple[re.Pattern, str]], bool] = (0.0, [], True)


def _load() -> tuple[list[tuple[re.Pattern, str]], bool]:
    global _cache
    try:
        stamp = FILE.stat().st_mtime
    except OSError:
        return [], True
    if stamp != _cache[0]:
        try:
            data = json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _cache[1], _cache[2]
        words = {k: v for k, v in (data.get("palabras") or {}).items() if k and isinstance(v, str) and v}
        # las más largas primero: «Apple Music» antes que «Apple»
        rules = [(re.compile(r"(?<![\w])" + re.escape(k) + r"(?![\w])", re.I), v)
                 for k, v in sorted(words.items(), key=lambda kv: -len(kv[0]))]
        _cache = (stamp, rules, bool(data.get("qu_como_k", True)))
    return _cache[1], _cache[2]


_QU = re.compile(r"qu(?=[eéiíEÉIÍ])")
_QU_UP = re.compile(r"Qu(?=[eéiíEÉIÍ])|QU(?=[EÉIÍ])")
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_UNITS = [
    (re.compile(r"(?<=\d)\s*GB\b"), " gigas"),
    (re.compile(r"(?<=\d)\s*MB\b"), " megas"),
    (re.compile(r"(?<=\d)\s*kHz\b", re.I), " kilohercios"),
    (re.compile(r"(?<=\d)\s*fps\b", re.I), " fotogramas por segundo"),
]
_ACRONYMS = [
    (re.compile(r"\bPC\b"), "pecé"),
    (re.compile(r"\bPDF\b"), "pe de efe"),
    (re.compile(r"\bUSB\b"), "u ese be"),
    (re.compile(r"\bGPU\b"), "ge pe u"),
    (re.compile(r"\bCPU\b"), "ce pe u"),
]


def _say_hour(m: re.Match) -> str:
    hh, mm = int(m.group(1)), int(m.group(2))
    if mm == 0:
        return f"{hh} en punto"
    if mm == 30:
        return f"{hh} y media"
    return f"{hh} {mm:02d}" if mm >= 10 else f"{hh} cero {mm}"


def for_voice(text: str) -> str:
    """El texto tal como debe sonar."""
    text = _TIME_RE.sub(_say_hour, text)
    text = _PCT_RE.sub(r"\1 por ciento", text)
    for rx, rep in _UNITS:
        text = rx.sub(rep, text)
    for rx, rep in _ACRONYMS:
        text = rx.sub(rep, text)
    rules, qu = _load()
    for rx, said in rules:
        text = rx.sub(said, text)
    if qu:
        text = _QU_UP.sub("K", _QU.sub("k", text))
    return text
