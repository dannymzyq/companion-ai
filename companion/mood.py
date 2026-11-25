"""Estado de ánimo del personaje (16 nov 2026). Las emociones que muestra ([emo:…]) no se olvidan al acabar la
frase: dejan un ánimo (agrado y energía, de -1 a 1) que dura entre turnos y vuelve poco a poco al habitual de su
personalidad. Cuánto le mueve cada emoción depende de su expresividad. Va en el contexto del turno (no en el prompt
de sistema, que no debe cambiar entre turnos) y se guarda en data/mood.json para seguir igual tras reiniciar.

No guarda nada de lo que se dijo: solo dos números, la última emoción fuerte y cuándo."""
import json
import math
import threading
import time

from .config import settings

FILE = settings.data_dir / "mood.json"
HALF_LIFE = 25 * 60          # en 25 minutos sin emociones nuevas, el ánimo recorre la mitad del camino al habitual
STRONG = 0.45                # una emoción así de lejos del ánimo habitual se recuerda («hace un rato…»)
REMEMBER = 40 * 60

# (agrado, energía) de cada emoción. Neutral está en el centro.
VA = {
    "neutral": (0.0, 0.0), "feliz": (0.6, 0.35), "emocionada": (0.75, 0.85), "timida": (0.1, -0.2),
    "sonrojada": (0.35, 0.3), "triste": (-0.65, -0.45), "molesta": (-0.55, 0.45), "sorprendida": (0.15, 0.7),
    "pensativa": (0.0, -0.25), "carinosa": (0.7, -0.05), "enamorada": (0.8, 0.3), "nerviosa": (-0.25, 0.6),
    "asustada": (-0.6, 0.75), "confundida": (-0.15, 0.15),
}
_lock = threading.Lock()


def _load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


_state = _load()


def _save():
    try:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state), encoding="utf-8")
        tmp.replace(FILE)
    except OSError:
        pass


def _now_va(base: str, now: float) -> tuple[float, float]:
    """El ánimo de ahora: el guardado, acercándose al habitual con el tiempo."""
    bv, ba = VA.get(base, (0.0, 0.0))
    if "v" not in _state:
        return bv, ba
    k = 0.5 ** (max(0.0, now - _state.get("t", now)) / HALF_LIFE)
    return bv + (_state["v"] - bv) * k, ba + (_state["a"] - ba) * k


def feel(emotion: str | None, personality: dict, now: float | None = None):
    """El personaje acaba de mostrar esta emoción: el ánimo se mueve hacia ella."""
    if emotion not in VA:
        return
    now = time.time() if now is None else now
    base = personality.get("base_mood", "neutral")
    ex = float(personality.get("traits", {}).get("expressiveness", 0.6))
    with _lock:
        v, a = _now_va(base, now)
        ev, ea = VA[emotion]
        step = 0.18 + 0.32 * ex                       # contenida: se le nota poco · muy emotiva: le cambia el día
        v, a = v + (ev - v) * step, a + (ea - a) * step
        _state.update(v=round(v, 3), a=round(a, 3), t=now, base=base)
        bv, ba = VA.get(base, (0.0, 0.0))
        if math.hypot(ev - bv, ea - ba) >= STRONG + 0.25 * (1 - ex) and emotion != base:
            _state.update(last=emotion, last_t=now)
        _save()


def describe(personality: dict, now: float | None = None, *, speaks: str = "f") -> str:
    """El ánimo de ahora en palabras, para el contexto del turno ('' si está en su ánimo de siempre)."""
    now = time.time() if now is None else now
    base = personality.get("base_mood", "neutral")
    m = speaks == "m"
    with _lock:
        if "v" not in _state:
            return ""
        v, a = _now_va(base, now)
        last, last_t = _state.get("last"), _state.get("last_t", 0)
    bv, ba = VA.get(base, (0.0, 0.0))
    parts = []
    if math.hypot(v - bv, a - ba) >= 0.12:
        mood_str = (
            "de muy buen humor" if v > 0.5 else
            "de buen humor" if v > 0.2 else
            ("algo decaído" if m else "algo decaída") if v < -0.4 and a < 0 else
            ("molesto o tenso" if m else "molesta o tensa") if v < -0.3 else
            ("un poco bajo de ánimo" if m else "un poco baja de ánimo") if v < -0.15 else
            ("tranquilo" if m else "tranquila")
        )
        energy = " y con mucha energía" if a > 0.5 else " y con energía" if a > 0.25 else " y sin mucha energía" if a < -0.25 else ""
        parts.append(f"Ahora mismo estás {mood_str}{energy}")
    if last and now - last_t < REMEMBER:
        mins = max(1, round((now - last_t) / 60))
        words_map = _WORD_M if m else _WORD
        parts.append(f"hace {mins} min te sentiste {words_map.get(last, last)}")
    if not parts:
        return ""
    return "(Tu ánimo: " + "; ".join(parts) + ". Que se note un poco en cómo respondes, sin decirlo salvo que venga al caso.)"


_WORD = {"timida": "tímida", "carinosa": "cariñosa"}
_WORD_M = {
    "feliz": "feliz", "emocionada": "emocionado", "timida": "tímido", "sonrojada": "sonrojado",
    "triste": "triste", "molesta": "molesto", "sorprendida": "sorprendido", "pensativa": "pensativo",
    "carinosa": "cariñoso", "enamorada": "enamorado", "nerviosa": "nervioso", "asustada": "asustado",
    "confundida": "confundido",
}


def public(personality: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with _lock:
        v, a = _now_va(personality.get("base_mood", "neutral"), now)
    return {"valence": round(v, 2), "energy": round(a, 2), "emotion": closest(v, a)}


def closest(v: float, a: float) -> str:
    return min(VA, key=lambda e: math.hypot(VA[e][0] - v, VA[e][1] - a))


def reset():
    with _lock:
        _state.clear()
        FILE.unlink(missing_ok=True)


def since_last_talk(last_ts: float | None, now: float | None = None) -> str:
    """Cuánto hace que no hablaban, si es más de unas horas: así puede saludar distinto tras unos días."""
    if last_ts is None:
        return ""
    gap = (time.time() if now is None else now) - last_ts
    if gap < 6 * 3600:
        return ""
    if gap < 36 * 3600:
        return "(La última vez que hablaron fue hace unas horas, ayer o anoche.)"
    days = round(gap / 86400)
    return f"(La última vez que hablaron fue hace {days} días.)"
