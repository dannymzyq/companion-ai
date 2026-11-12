"""Convierte el texto que va llegando del LLM en frases listas para la voz.

Las etiquetas [emo:...], [gesto:...] y [recordar: ...] nunca se leen en voz alta: se separan del texto y
viajan junto a la frase para que el avatar cambie de expresión y se mueva en el momento justo.
(Misma idea que el filtro de etiquetas de waifuv3: mac-backend/voice_agent/agent.py.)
"""
import re
import unicodedata
from dataclasses import dataclass, field

from .prompt import EMOTIONS, GESTURES

BRACKET = re.compile(r"\[[^\]]*\]")
TAG = re.compile(r"\[\s*([^\W\d]+)\s*:\s*([^\]]*)\]")
SENTENCE_END = re.compile(r"[.!?…]+[\"»)']*\s+|\n+")
CLAUSE_END = re.compile(r"[,;:]\s+")
MARKDOWN = re.compile("[*_`#~\U0001F000-\U0001FAFF☀-➿️‍]+")     # y emojis: los modelos pequeños los ponen igual
HAS_WORD = re.compile(r"\w")

FIRST_MIN, NEXT_MIN, CLAUSE_AT = 12, 28, 90
HOLD_TAG = 300          # una etiqueta sin cerrar se espera hasta este largo


def _plain(s: str) -> str:
    """'Tímida' → 'timida', 'cariñosa' → 'carinosa'."""
    s = unicodedata.normalize("NFD", s.strip().lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace(" ", "_")


@dataclass
class Sentence:
    text: str
    emotion: str | None = None
    gestures: list[str] = field(default_factory=list)


class TagStream:
    def __init__(self):
        self.raw = ""                 # texto recibido con una posible etiqueta a medias
        self.cur = ""                 # texto limpio de la frase en curso
        self.emotion: str | None = None
        self.gestures: list[str] = []
        self.memories: list[str] = []
        self.count = 0
        self.spoken: list[str] = []   # frases emitidas (texto limpio)

    # ------------------------------------------------------------ entrada
    def feed(self, chunk: str) -> list[Sentence]:
        self.raw += chunk
        cut = self.raw.rfind("[")
        if cut != -1 and "]" not in self.raw[cut:] and len(self.raw) - cut < HOLD_TAG:
            ready, self.raw = self.raw[:cut], self.raw[cut:]
        else:
            ready, self.raw = self.raw, ""
        return self._consume(ready, final=False)

    def flush(self) -> list[Sentence]:
        rest, self.raw = self.raw, ""
        cut = rest.rfind("[")
        if cut != -1 and "]" not in rest[cut:]:
            rest = rest[:cut]             # etiqueta que nunca se cerró: no se lee
        return self._consume(rest, final=True)

    # ------------------------------------------------------------ interno
    def _consume(self, ready: str, final: bool) -> list[Sentence]:
        out: list[Sentence] = []
        pos = 0
        for m in BRACKET.finditer(ready):
            self._text(ready[pos:m.start()], out)
            self._tag(m.group(0), out)
            pos = m.end()
        self._text(ready[pos:], out)
        if final and self.cur.strip():
            self._emit(self.cur, out)
            self.cur = ""
        return out

    def _tag(self, raw: str, out: list[Sentence]):
        m = TAG.fullmatch(raw)
        if not m:
            return                        # cualquier otra cosa entre corchetes se descarta
        kind, value = _plain(m.group(1)), m.group(2).strip()
        is_emo = kind == "emo" and _plain(value) in EMOTIONS
        is_gesture = kind == "gesto" and _plain(value) in GESTURES
        if (is_emo or is_gesture) and HAS_WORD.search(self.cur):
            self._emit(self.cur, out)     # la etiqueta abre frase nueva: lo anterior se dice con su propia emoción
            self.cur = ""
        if is_emo:
            self.emotion = _plain(value)
        elif is_gesture:
            self.gestures.append(_plain(value))
        elif kind == "recordar" and value:
            self.memories.append(value[:300])

    def _text(self, text: str, out: list[Sentence]):
        self.cur += text
        while True:
            idx = self._boundary()
            if idx is None:
                return
            sentence, self.cur = self.cur[:idx], self.cur[idx:]
            self._emit(sentence, out)

    def _boundary(self) -> int | None:
        minimum = FIRST_MIN if self.count == 0 else NEXT_MIN
        for m in SENTENCE_END.finditer(self.cur):
            if len(self.cur[:m.end()].strip()) >= minimum:
                return m.end()
        if len(self.cur) > CLAUSE_AT:     # frase muy larga: se corta en una coma para no esperar
            last = None
            for m in CLAUSE_END.finditer(self.cur):
                if m.end() >= 40:
                    last = m.end()
            return last
        return None

    def _emit(self, text: str, out: list[Sentence]):
        clean = re.sub(r"\s+", " ", MARKDOWN.sub("", text)).strip()
        if not HAS_WORD.search(clean):
            return                        # solo signos: las etiquetas pendientes pasan a la frase siguiente
        out.append(Sentence(clean, self.emotion, self.gestures))
        self.spoken.append(clean)
        self.emotion, self.gestures = None, []
        self.count += 1
