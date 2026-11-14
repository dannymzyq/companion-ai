"""Historial y recuerdos en SQLite (data/companion.db). Todo queda en esta PC."""
import re
import sqlite3
import time
import unicodedata

from .config import settings

_db = sqlite3.connect(settings.data_dir / "companion.db", check_same_thread=False)
_db.executescript("""
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, text TEXT NOT NULL,
                                     emotion TEXT, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, fact TEXT NOT NULL UNIQUE, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY, text TEXT NOT NULL, first_id INTEGER NOT NULL,
                                      last_id INTEGER NOT NULL, ts REAL NOT NULL);
""")
# Memoria en tres capas:
#   corto plazo  → messages: los últimos mensajes van tal cual al modelo
#   largo plazo  → memories: datos duraderos sobre el usuario ([recordar: ...])
#                → summaries: resumen de cada tramo de conversación que ya salió de la ventana de corto plazo


def add_message(role: str, text: str, emotion: str | None = None) -> int:
    cur = _db.execute("INSERT INTO messages(role, text, emotion, ts) VALUES (?,?,?,?)", (role, text, emotion, time.time()))
    _db.commit()
    return cur.lastrowid


def delete_message(message_id: int):
    _db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    _db.commit()


def recent(limit: int = 20) -> list[dict]:
    rows = _db.execute("SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r, "content": t} for r, t in reversed(rows)]


def anchor(keep: int) -> int:
    """Id del mensaje desde el que empieza la ventana de historial: deja dentro los `keep` más recientes."""
    row = _db.execute("SELECT id FROM messages ORDER BY id DESC LIMIT 1 OFFSET ?", (max(0, keep - 1),)).fetchone()
    return row[0] if row else 0


def since(first_id: int) -> list[tuple[int, str, str]]:
    """Mensajes desde ese id, en orden: (id, rol, texto)."""
    return _db.execute("SELECT id, role, text FROM messages WHERE id >= ? ORDER BY id", (first_id,)).fetchall()


def add_memory(fact: str):
    fact = fact.strip().rstrip(".").strip()
    same = _db.execute("SELECT 1 FROM memories WHERE lower(rtrim(fact, '.')) = lower(?)", (fact,)).fetchone()
    if not fact or same:                      # ya lo sabía (aunque lo escriba con otro punto final o mayúsculas)
        return
    _db.execute("INSERT OR IGNORE INTO memories(fact, ts) VALUES (?,?)", (fact, time.time()))
    _db.commit()


def memories(limit: int = 40) -> list[str]:
    rows = _db.execute("SELECT fact FROM memories ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [r[0] for r in reversed(rows)]


def unsummarized(before_id: int, limit: int = 40) -> list[tuple[int, str, str, float]]:
    """Mensajes anteriores a `before_id` que todavía no están en ningún resumen: (id, rol, texto, cuándo)."""
    last = _db.execute("SELECT COALESCE(MAX(last_id), 0) FROM summaries").fetchone()[0]
    return _db.execute("SELECT id, role, text, ts FROM messages WHERE id > ? AND id < ? ORDER BY id LIMIT ?",
                       (last, before_id, limit)).fetchall()


def add_summary(text: str, first_id: int, last_id: int, ts: float):
    _db.execute("INSERT INTO summaries(text, first_id, last_id, ts) VALUES (?,?,?,?)", (text.strip(), first_id, last_id, ts))
    _db.commit()


def summaries(limit: int = 10) -> list[tuple[str, float]]:
    """Los últimos resúmenes, del más antiguo al más reciente: (texto, fecha de esa conversación)."""
    rows = _db.execute("SELECT text, ts FROM summaries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return list(reversed(rows))


_STOP = set("""ahora algo algun alguna algunos antes aqui asi aunque bien cada casi como con contra cosa cosas cual
cuando de del desde donde dijo dice durante ella ellas ellos entre era eran esa ese eso esta estaba estado estar este
esto estos fue fueron gusta habia hablar hablaron hace hacer hasta hoy mas mismo mucho muy nada nadie nos nosotros nunca
otra otro para pero poco porque puede pues que quien quiere sabe sido siempre sobre solo tambien tanto tener tiene todo
todos tras tuvo una unas uno unos usted vamos vez yo""".split())


def _keys(text: str) -> set[str]:
    """Palabras con contenido, sin tildes y recortadas a 5 letras (así «viaje» encuentra «viajes»)."""
    s =unicodedata.normalize("NFD", text.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return {w[:5] for w in re.findall(r"[a-zñ0-9]{4,}", s) if w not in _STOP}


def relevant_summaries(query: str, skip_recent: int = 8, limit: int = 2, ignore: str = "") -> list[tuple[str, float]]:
    """Resúmenes antiguos (más allá de los `skip_recent` que ya van siempre en el prompt) que tratan de lo mismo que
    `query`: comparten al menos dos palabras poco comunes. No cuentan las de `ignore` (los nombres del usuario y del
    personaje, que salen en todos) ni las que aparecen en más del 10 % de los resúmenes (mínimo 2): con la
    historia real del 13 nov 2026 así sale en ~6 % de los mensajes; contando todas las palabras, en un tercio.
    Del más parecido al menos: (texto, fecha)."""
    words = _keys(query or "") - _keys(ignore)
    if len(words) < 2:
        return []
    every = [(_keys(t), t, ts) for t, ts in _db.execute("SELECT text, ts FROM summaries ORDER BY id DESC").fetchall()]
    common = {w for w in words if sum(w in k for k, _, _ in every) > max(2, len(every) // 10)}
    words -= common
    if len(words) < 2:
        return []
    scored = sorted(((len(words & k), ts, t) for k, t, ts in every[skip_recent:]), reverse=True)   # a igualdad, el más reciente
    return [(t, ts) for n, ts, t in scored if n >= 2][:limit]


def delete_memory(fact: str):
    _db.execute("DELETE FROM memories WHERE fact = ?", (fact,))
    _db.commit()


def forget_all():
    _db.executescript("DELETE FROM messages; DELETE FROM memories; DELETE FROM summaries;")
    _db.commit()
