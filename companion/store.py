"""Historial y recuerdos en SQLite (data/companion.db). Todo queda en esta PC."""
import json
import re
import sqlite3
import threading
import time
import unicodedata

from .config import settings
from .text_utils import is_private_fact

_lock = threading.RLock()
_db = sqlite3.connect(settings.data_dir / "companion.db", check_same_thread=False)
with _lock:
    _db.execute("PRAGMA journal_mode=WAL")
    _db.execute("PRAGMA synchronous=NORMAL")
    _db.execute("PRAGMA busy_timeout=5000")
    _db.executescript("""
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, text TEXT NOT NULL,
                                         emotion TEXT, ts REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, fact TEXT NOT NULL UNIQUE, ts REAL NOT NULL,
                                         pinned INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY, text TEXT NOT NULL, first_id INTEGER NOT NULL,
                                          last_id INTEGER NOT NULL, ts REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, due_ts REAL NOT NULL, text TEXT NOT NULL,
                                          done INTEGER NOT NULL DEFAULT 0, created_ts REAL NOT NULL,
                                          kind TEXT NOT NULL DEFAULT 'reminder');
    CREATE TABLE IF NOT EXISTS memory_backups (id INTEGER PRIMARY KEY, facts TEXT NOT NULL, ts REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(done, due_ts);
    CREATE INDEX IF NOT EXISTS idx_summaries_last ON summaries(last_id);
    CREATE INDEX IF NOT EXISTS idx_memories_ts ON memories(ts);
    """)
    # Migraciones seguras para bases de datos ya existentes
    for _ddl in (
        "ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE reminders ADD COLUMN kind TEXT NOT NULL DEFAULT 'reminder'",
    ):
        try:
            _db.execute(_ddl)
            _db.commit()
        except sqlite3.OperationalError:
            pass

    _HAS_FTS5 = False
    try:
        _db.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(fact, tokenize='unicode61 remove_diacritics 2');
        CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(text, tokenize='unicode61 remove_diacritics 2');
        """)
        _HAS_FTS5 = True
    except sqlite3.OperationalError:
        _HAS_FTS5 = False


def _sync_fts():
    if not _HAS_FTS5:
        return
    with _lock:
        try:
            mc = _db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            mfc = _db.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
            if mc != mfc:
                _db.execute("DELETE FROM memories_fts")
                _db.execute("INSERT INTO memories_fts(rowid, fact) SELECT id, fact FROM memories")
            sc = _db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
            sfc = _db.execute("SELECT COUNT(*) FROM summaries_fts").fetchone()[0]
            if sc != sfc:
                _db.execute("DELETE FROM summaries_fts")
                _db.execute("INSERT INTO summaries_fts(rowid, text) SELECT id, text FROM summaries")
            _db.commit()
        except sqlite3.Error:
            pass


_sync_fts()


def add_message(role: str, text: str, emotion: str | None = None) -> int:
    with _lock:
        cur = _db.execute("INSERT INTO messages(role, text, emotion, ts) VALUES (?,?,?,?)", (role, text, emotion, time.time()))
        _db.commit()
        return cur.lastrowid


def delete_message(message_id: int):
    with _lock:
        _db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        _db.commit()


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        rows = _db.execute("SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r, "content": t} for r, t in reversed(rows)]


def anchor(keep: int) -> int:
    """Id del mensaje desde el que empieza la ventana de historial: deja dentro los `keep` más recientes."""
    with _lock:
        row = _db.execute("SELECT id FROM messages ORDER BY id DESC LIMIT 1 OFFSET ?", (max(0, keep - 1),)).fetchone()
    return row[0] if row else 0


def previous_ts(skip: int = 1) -> float | None:
    """Cuándo fue el mensaje anterior a los `skip` últimos (con 1: el anterior al que acaba de llegar)."""
    with _lock:
        row = _db.execute("SELECT ts FROM messages ORDER BY id DESC LIMIT 1 OFFSET ?", (skip,)).fetchone()
    return row[0] if row else None


def since(first_id: int) -> list[tuple[int, str, str]]:
    """Mensajes desde ese id, en orden: (id, rol, texto)."""
    with _lock:
        return _db.execute("SELECT id, role, text FROM messages WHERE id >= ? ORDER BY id", (first_id,)).fetchall()


def add_memory(fact: str, *, pinned: bool = False) -> bool:
    fact = (fact or "").strip().strip("«»\"' ").rstrip(".").strip()
    if not fact or len(fact) > 250 or is_private_fact(fact):
        return False
    with _lock:
        same = _db.execute("SELECT id, pinned FROM memories WHERE lower(rtrim(fact, '.')) = lower(?)", (fact,)).fetchone()
        if same:
            if pinned and not same[1]:
                _db.execute("UPDATE memories SET pinned = 1 WHERE id = ?", (same[0],))
                _db.commit()
            return False
        cur = _db.execute("INSERT OR IGNORE INTO memories(fact, ts, pinned) VALUES (?,?,?)",
                          (fact, time.time(), 1 if pinned else 0))
        if cur.rowcount and _HAS_FTS5:
            _db.execute("INSERT INTO memories_fts(rowid, fact) VALUES (?,?)", (cur.lastrowid, fact))
        _db.commit()
        return bool(cur.rowcount)


def memories(limit: int = 40) -> list[str]:
    """Los recuerdos activos: siempre incluye primero los fijados (📌) y completa con los más recientes."""
    with _lock:
        pinned_rows = _db.execute("SELECT id, fact FROM memories WHERE pinned = 1 ORDER BY id").fetchall()
        pinned_ids = {r[0] for r in pinned_rows}
        rem = max(0, limit - len(pinned_rows))
        recent_rows = _db.execute(
            "SELECT id, fact FROM memories WHERE pinned = 0 ORDER BY id DESC LIMIT ?", (rem,)
        ).fetchall() if rem else []
    ordered = [*pinned_rows, *reversed(recent_rows)]
    seen: set[int] = set()
    out: list[str] = []
    for mid, fact in ordered:
        if mid not in seen and (mid in pinned_ids or len(out) < limit):
            seen.add(mid)
            out.append(fact)
    return out


def memory_items(limit: int = 200) -> list[dict]:
    """Lista completa para la interfaz y diario: [{id, fact, ts, pinned}]."""
    with _lock:
        rows = _db.execute(
            "SELECT id, fact, ts, pinned FROM memories ORDER BY pinned DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"id": r[0], "fact": r[1], "ts": r[2], "pinned": bool(r[3])} for r in rows]


def update_memory(mid: int, *, fact: str | None = None, pinned: bool | None = None) -> dict | None:
    with _lock:
        row = _db.execute("SELECT id, fact, ts, pinned FROM memories WHERE id = ?", (int(mid),)).fetchone()
        if not row:
            return None
        new_fact = row[1]
        if fact is not None:
            cleaned = fact.strip().rstrip(".").strip()
            if not cleaned or len(cleaned) > 250 or is_private_fact(cleaned):
                raise ValueError("Ese recuerdo no es válido o contiene datos sensibles.")
            new_fact = cleaned
        new_pin = row[3] if pinned is None else (1 if pinned else 0)
        _db.execute("UPDATE memories SET fact = ?, pinned = ? WHERE id = ?", (new_fact, new_pin, int(mid)))
        if _HAS_FTS5 and new_fact != row[1]:
            _db.execute("DELETE FROM memories_fts WHERE rowid = ?", (int(mid),))
            _db.execute("INSERT INTO memories_fts(rowid, fact) VALUES (?,?)", (int(mid), new_fact))
        _db.commit()
        return {"id": int(mid), "fact": new_fact, "ts": row[2], "pinned": bool(new_pin)}


def unsummarized(before_id: int, limit: int = 40) -> list[tuple[int, str, str, float]]:
    """Mensajes anteriores a `before_id` que todavía no están en ningún resumen: (id, rol, texto, cuándo)."""
    with _lock:
        last = _db.execute("SELECT COALESCE(MAX(last_id), 0) FROM summaries").fetchone()[0]
        return _db.execute("SELECT id, role, text, ts FROM messages WHERE id > ? AND id < ? ORDER BY id LIMIT ?",
                           (last, before_id, limit)).fetchall()


def add_summary(text: str, first_id: int, last_id: int, ts: float):
    clean = text.strip()
    with _lock:
        cur = _db.execute("INSERT INTO summaries(text, first_id, last_id, ts) VALUES (?,?,?,?)",
                          (clean, first_id, last_id, ts))
        if _HAS_FTS5:
            _db.execute("INSERT INTO summaries_fts(rowid, text) VALUES (?,?)", (cur.lastrowid, clean))
        _db.commit()


def summaries(limit: int = 10) -> list[tuple[str, float]]:
    """Los últimos resúmenes, del más antiguo al más reciente: (texto, fecha de esa conversación)."""
    with _lock:
        rows = _db.execute("SELECT text, ts FROM summaries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return list(reversed(rows))


_STOP = set("""ahora algo algun alguna algunos antes aqui asi aunque bien cada casi como con contra cosa cosas cual
cuando de del desde donde dijo dice durante ella ellas ellos entre era eran esa ese eso esta estaba estado estar este
esto estos fue fueron gusta habia hablar hablaron hace hacer hasta hoy las los mas mia mio mis mismo mucho muy nada
nadie nos nosotros nunca otra otro para pero poco por porque puede pues que quien quiere sabe sido siempre sin sobre
solo sus suya suyo tambien tanto tener tiene todo todos tras tus tuyo una unas uno unos usted vamos vez yo""".split())


def _keys(text: str) -> set[str]:
    """Palabras con contenido (>=3 letras: incluye 'mac', 'gpu', 'mar', 'sol', 'gym'), sin tildes."""
    s = unicodedata.normalize("NFD", (text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    tokens: set[str] = set()
    for w in re.findall(r"[a-zñ0-9]{3,}", s):
        if w in _STOP:
            continue
        # Raíz suave para plurales castellanos sin colisionar 'libro'/'libre'
        stem = w[:-2] if len(w) > 5 and w.endswith("es") else (w[:-1] if len(w) > 4 and w.endswith("s") else w)
        tokens.add(stem)
    return tokens


def relevant_summaries(query: str, skip_recent: int = 8, limit: int = 2, ignore: str = "") -> list[tuple[str, float]]:
    """Resúmenes antiguos que tratan de lo mismo que `query` (al menos 2 palabras poco comunes)."""
    words = _keys(query or "") - _keys(ignore)
    if len(words) < 2:
        return []
    with _lock:
        every_rows = _db.execute("SELECT id, text, ts FROM summaries ORDER BY id DESC").fetchall()
    if len(every_rows) <= skip_recent:
        return []
    every = [(rid, _keys(t), t, ts) for rid, t, ts in every_rows]
    common = {w for w in words if sum(w in k for _, k, _, _ in every) > max(2, len(every) // 10)}
    words -= common
    if len(words) < 2:
        return []
    scored = sorted(((len(words & k), ts, t) for _, k, t, ts in every[skip_recent:]), reverse=True)
    return [(t, ts) for n, ts, t in scored if n >= 2][:limit]


def relevant_memories(query: str, skip_recent: int = 35, limit: int = 5, ignore: str = "") -> list[str]:
    """Recuerdos antiguos no fijados (fuera de los `skip_recent` recientes que ya van en el prompt) que coinciden con `query`."""
    words = _keys(query or "") - _keys(ignore)
    if not words:
        return []
    with _lock:
        older = _db.execute(
            "SELECT id, fact FROM memories WHERE pinned = 0 ORDER BY id DESC LIMIT -1 OFFSET ?",
            (max(0, skip_recent),),
        ).fetchall()
        if not older:
            return []
        if _HAS_FTS5:
            fts_q = " OR ".join(f'"{w}"*' for w in list(words)[:8])
            older_ids = {r[0] for r in older}
            try:
                hits = _db.execute(
                    "SELECT rowid, fact FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_q, limit * 4),
                ).fetchall()
                matched = [f for rid, f in hits if rid in older_ids]
                if matched:
                    return matched[:limit]
            except sqlite3.Error:
                pass
    scored = sorted(((len(words & _keys(f)), mid, f) for mid, f in older), reverse=True)
    return [f for n, _, f in scored if n >= 1][:limit]


def diary_search(query: str = "", limit: int = 100) -> dict:
    """Búsqueda instantánea en el Diario de recuerdos y resúmenes (con FTS5 cuando hay consulta)."""
    q = (query or "").strip()
    if not q:
        with _lock:
            srows = _db.execute("SELECT id, text, ts FROM summaries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {
            "items": memory_items(limit=limit),
            "summaries": [{"id": r[0], "text": r[1], "ts": r[2], "date": time.strftime("%d/%m/%Y", time.localtime(r[2]))}
                          for r in srows],
            "query": "",
        }
    terms = [re.sub(r'[^\wñáéíóúü]+', '', w.lower()) for w in q.split() if len(w.strip()) >= 2][:8]
    with _lock:
        if _HAS_FTS5 and terms:
            fts_q = " AND ".join(f'"{w}"*' for w in terms)
            try:
                m_ids = [r[0] for r in _db.execute(
                    "SELECT rowid FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?", (fts_q, limit)
                ).fetchall()]
                s_ids = [r[0] for r in _db.execute(
                    "SELECT rowid FROM summaries_fts WHERE summaries_fts MATCH ? ORDER BY rank LIMIT ?", (fts_q, limit)
                ).fetchall()]
                m_rows = (_db.execute(
                    f"SELECT id, fact, ts, pinned FROM memories WHERE id IN ({','.join('?' * len(m_ids))}) ORDER BY pinned DESC, id DESC",
                    m_ids,
                ).fetchall() if m_ids else [])
                s_rows = (_db.execute(
                    f"SELECT id, text, ts FROM summaries WHERE id IN ({','.join('?' * len(s_ids))}) ORDER BY id DESC",
                    s_ids,
                ).fetchall() if s_ids else [])
                return {
                    "items": [{"id": r[0], "fact": r[1], "ts": r[2], "pinned": bool(r[3])} for r in m_rows],
                    "summaries": [{"id": r[0], "text": r[1], "ts": r[2],
                                   "date": time.strftime("%d/%m/%Y", time.localtime(r[2]))} for r in s_rows],
                    "query": q,
                }
            except sqlite3.Error:
                pass
        like = f"%{q.lower()}%"
        m_rows = _db.execute(
            "SELECT id, fact, ts, pinned FROM memories WHERE lower(fact) LIKE ? ORDER BY pinned DESC, id DESC LIMIT ?",
            (like, limit),
        ).fetchall()
        s_rows = _db.execute(
            "SELECT id, text, ts FROM summaries WHERE lower(text) LIKE ? ORDER BY id DESC LIMIT ?",
            (like, limit),
        ).fetchall()
    return {
        "items": [{"id": r[0], "fact": r[1], "ts": r[2], "pinned": bool(r[3])} for r in m_rows],
        "summaries": [{"id": r[0], "text": r[1], "ts": r[2], "date": time.strftime("%d/%m/%Y", time.localtime(r[2]))}
                      for r in s_rows],
        "query": q,
    }


def add_reminder(due_ts: float, text: str, *, kind: str = "reminder") -> int:
    with _lock:
        cur = _db.execute("INSERT INTO reminders(due_ts, text, done, created_ts, kind) VALUES (?,?,0,?,?)",
                          (float(due_ts), text.strip()[:300], time.time(), kind if kind in ("reminder", "timer") else "reminder"))
        _db.commit()
        return cur.lastrowid


def due_reminders(now: float | None = None, *, kind: str | None = "reminder") -> list[tuple[int, float, str]]:
    """Recordatorios pendientes cuya hora ya llegó: [(id, due_ts, texto)]."""
    t = time.time() if now is None else float(now)
    with _lock:
        if kind is None:
            return _db.execute("SELECT id, due_ts, text FROM reminders WHERE done = 0 AND due_ts <= ? ORDER BY due_ts",
                               (t,)).fetchall()
        return _db.execute(
            "SELECT id, due_ts, text FROM reminders WHERE done = 0 AND kind = ? AND due_ts <= ? ORDER BY due_ts",
            (kind, t),
        ).fetchall()


def pending_reminders(limit: int = 30, *, include_timers: bool = False) -> list[tuple[int, float, str]]:
    with _lock:
        if include_timers:
            return _db.execute("SELECT id, due_ts, text FROM reminders WHERE done = 0 ORDER BY due_ts LIMIT ?",
                               (limit,)).fetchall()
        return _db.execute(
            "SELECT id, due_ts, text FROM reminders WHERE done = 0 AND kind = 'reminder' ORDER BY due_ts LIMIT ?",
            (limit,),
        ).fetchall()


def pending_reminder_items(limit: int = 50) -> list[dict]:
    with _lock:
        rows = _db.execute(
            "SELECT id, due_ts, text, kind, created_ts FROM reminders WHERE done = 0 ORDER BY due_ts LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r[0], "due_ts": r[1], "when": time.strftime("%d/%m %H:%M", time.localtime(r[1])),
             "text": r[2], "kind": r[3] or "reminder", "created_ts": r[4]} for r in rows]


def mark_reminder_done(rid: int):
    with _lock:
        _db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (int(rid),))
        _db.commit()


def delete_reminder(rid: int) -> bool:
    with _lock:
        cur = _db.execute("DELETE FROM reminders WHERE id = ?", (int(rid),))
        _db.commit()
        return bool(cur.rowcount)


def memory_count() -> int:
    with _lock:
        return _db.execute("SELECT COUNT(*) FROM memories WHERE pinned = 0").fetchone()[0]


def last_tidy_count() -> int:
    """Cuántos datos había justo después de la última vez que se ordenaron (0 si nunca)."""
    with _lock:
        row = _db.execute("SELECT facts FROM memory_backups ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row[0]).get("after", 0) if row else 0


def replace_memories(facts: list[str]):
    """Cambia los datos no fijados por la lista ordenada, conservando SIEMPRE los fijados (`pinned = 1`) y guardando
    copia exacta con `max_id` para poder deshacer sin perder lo añadido en el mismo segundo."""
    now = time.time()
    with _lock:
        old = _db.execute("SELECT fact, ts, pinned FROM memories ORDER BY id").fetchall()
        pinned_rows = [(f, ts) for f, ts, p in old if p]
        pinned_lower = {f.lower() for f, _ in pinned_rows}
        cleaned = [f for f in facts if f.strip() and not is_private_fact(f) and f.strip().lower() not in pinned_lower]
        with _db:
            _db.execute("DELETE FROM memory_backups")
            _db.execute("DELETE FROM memories")
            max_id = 0
            for f, ts in pinned_rows:
                cur = _db.execute("INSERT OR IGNORE INTO memories(fact, ts, pinned) VALUES (?,?,1)", (f, ts))
                max_id = max(max_id, cur.lastrowid or 0)
            for i, f in enumerate(cleaned):
                cur = _db.execute("INSERT OR IGNORE INTO memories(fact, ts, pinned) VALUES (?,?,0)", (f, now + i * 1e-3))
                max_id = max(max_id, cur.lastrowid or 0)
            _db.execute(
                "INSERT INTO memory_backups(facts, ts) VALUES (?,?)",
                (json.dumps({"before": old, "after": len(cleaned), "max_id": max_id}, ensure_ascii=False), now),
            )
            if _HAS_FTS5:
                _db.execute("DELETE FROM memories_fts")
                _db.execute("INSERT INTO memories_fts(rowid, fact) SELECT id, fact FROM memories")


def can_undo_tidy() -> bool:
    with _lock:
        return _db.execute("SELECT 1 FROM memory_backups").fetchone() is not None


def undo_tidy() -> bool:
    """Vuelve a los datos de antes del último orden, conservando todo lo que se recordó después (`id > max_id`)."""
    with _lock:
        row = _db.execute("SELECT facts, ts FROM memory_backups ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return False
        payload = json.loads(row[0])
        before = payload["before"]
        max_id = payload.get("max_id")
        if max_id is not None:
            later = _db.execute("SELECT fact, ts, pinned FROM memories WHERE id > ? ORDER BY id", (int(max_id),)).fetchall()
        else:
            later = _db.execute("SELECT fact, ts, pinned FROM memories WHERE ts > ? ORDER BY id", (row[1] + 1,)).fetchall()
        with _db:
            _db.execute("DELETE FROM memories")
            for item in [*before, *later]:
                fact, ts = item[0], item[1]
                pin = int(item[2]) if len(item) > 2 else 0
                _db.execute("INSERT OR IGNORE INTO memories(fact, ts, pinned) VALUES (?,?,?)", (fact, ts, pin))
            _db.execute("DELETE FROM memory_backups")
            if _HAS_FTS5:
                _db.execute("DELETE FROM memories_fts")
                _db.execute("INSERT INTO memories_fts(rowid, fact) SELECT id, fact FROM memories")
        return True


def delete_memory(fact: str):
    with _lock:
        row = _db.execute("SELECT id FROM memories WHERE fact = ?", (fact,)).fetchone()
        _db.execute("DELETE FROM memories WHERE fact = ?", (fact,))
        if row and _HAS_FTS5:
            _db.execute("DELETE FROM memories_fts WHERE rowid = ?", (row[0],))
        _db.commit()


def forget_all():
    with _lock:
        _db.executescript(
            "DELETE FROM messages; DELETE FROM memories; DELETE FROM summaries; "
            "DELETE FROM reminders; DELETE FROM memory_backups;"
        )
        if _HAS_FTS5:
            try:
                _db.executescript("DELETE FROM memories_fts; DELETE FROM summaries_fts;")
            except sqlite3.Error:
                pass
        _db.commit()
        try:
            _db.execute("VACUUM")
        except sqlite3.Error:
            pass
