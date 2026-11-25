"""Modo Compañero de Enfoque / Pomodoro Interactivo (N-02).

Gestiona bloques de trabajo concentrado (`work`) y descanso (`break`), persiste la racha de sesiones completadas
en `state.py` y avisa a todas las conexiones abiertas para mostrar el anillo de progreso y que el personaje celebre
y se estire contigo al llegar el descanso.
"""
import asyncio
import logging
import time

from . import state
from .config import settings

log = logging.getLogger("companion.focus")

_state_data = {
    "phase": "idle",        # idle | work | break
    "end_ts": 0.0,
    "total_s": 0,
    "work_s": 25 * 60,
    "break_s": 5 * 60,
    "task": "",
}
_runner: asyncio.Task | None = None


def _today_key() -> str:
    return time.strftime("%Y-%m-%d")


def stats() -> dict:
    raw = state.load().get("focus_stats") or {}
    streak = int(raw.get("streak") or 0)
    today = int(raw.get("completed_today") or 0) if raw.get("date") == _today_key() else 0
    total = int(raw.get("total_sessions") or 0)
    return {"streak": streak, "completed_today": today, "total_sessions": total, "date": raw.get("date") or ""}


def _record_completed():
    cur = state.load().get("focus_stats") or {}
    today = _today_key()
    prev_date = str(cur.get("date") or "")
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    completed_today = (int(cur.get("completed_today") or 0) if prev_date == today else 0) + 1
    streak = int(cur.get("streak") or 0)
    if prev_date == today:
        streak = max(1, streak)
    elif prev_date == yesterday:
        streak += 1
    else:
        streak = 1
    total = int(cur.get("total_sessions") or 0) + 1
    state.save(focus_stats={"date": today, "completed_today": completed_today, "streak": streak, "total_sessions": total})


def status() -> dict:
    st = stats()
    phase = _state_data["phase"]
    rem = max(0, int(round(_state_data["end_ts"] - time.time()))) if phase != "idle" else 0
    return {
        "active": phase != "idle",
        "phase": phase,
        "remaining_s": rem,
        "total_s": _state_data["total_s"] if phase != "idle" else _state_data["work_s"],
        "work_min": max(1, _state_data["work_s"] // 60),
        "break_min": max(1, _state_data["break_s"] // 60),
        "task": _state_data["task"],
        **st,
    }


async def _broadcast(speak_prompt: str = ""):
    from .session import _open
    payload = {"type": "focus", **status()}
    for s in list(_open):
        if not s.closed:
            await s.send_json(payload)
    if speak_prompt:
        target = next((s for s in reversed(_open) if not s.closed), None)
        if target is not None:
            target._later(speak_prompt)


async def _loop():
    try:
        while _state_data["phase"] != "idle":
            left = _state_data["end_ts"] - time.time()
            if left > 0:
                await asyncio.sleep(min(1.0, left))
                continue
            if _state_data["phase"] == "work":
                await asyncio.to_thread(_record_completed)
                _state_data["phase"] = "break"
                _state_data["total_s"] = _state_data["break_s"]
                _state_data["end_ts"] = time.time() + _state_data["break_s"]
                task_note = f" («{_state_data['task']}»)" if _state_data["task"] else ""
                st = stats()
                prompt = (
                    f"(Acaba de terminar el bloque de enfoque de {settings.user_name}{task_note}. "
                    f"Lleva {st['completed_today']} bloques hoy y racha de {st['streak']} días. "
                    f"Felicítale con alegría y naturalidad en una o dos "
                    f"frases cortas, animándole a estirarse y descansar {_state_data['break_s'] // 60} minutos.)"
                )
                await _broadcast(prompt)
            else:
                _state_data["phase"] = "idle"
                _state_data["end_ts"] = 0.0
                prompt = (
                    f"(Terminó el descanso de enfoque de {settings.user_name}. "
                    "Avísale en una sola frase breve y amable por si quiere empezar otro bloque o seguir con otra cosa.)"
                )
                await _broadcast(prompt)
                return
    except asyncio.CancelledError:
        pass


def start_sync(work_min: int = 25, break_min: int = 5, task: str = "") -> dict:
    """Inicia un bloque desde un hilo o desde async; devuelve el estado actual."""
    work_s = max(60, min(180 * 60, int(work_min) * 60))
    break_s = max(60, min(60 * 60, int(break_min) * 60))
    _state_data.update(
        phase="work",
        work_s=work_s,
        break_s=break_s,
        total_s=work_s,
        end_ts=time.time() + work_s,
        task=(task or "").strip()[:120],
    )
    return status()


async def control(action: str, work_min: int = 25, break_min: int = 5, task: str = "") -> dict:
    global _runner
    if _runner and not _runner.done():
        _runner.cancel()
        await asyncio.gather(_runner, return_exceptions=True)
    _runner = None
    act = (action or "start").strip().lower()
    if act == "stop":
        _state_data.update(phase="idle", end_ts=0.0, total_s=0)
        await _broadcast()
        return status()
    if act == "skip" and _state_data["phase"] == "work":
        await asyncio.to_thread(_record_completed)
        _state_data.update(phase="break", total_s=_state_data["break_s"], end_ts=time.time() + _state_data["break_s"])
        _runner = asyncio.create_task(_loop())
        await _broadcast()
        return status()
    start_sync(work_min=work_min, break_min=break_min, task=task)
    _runner = asyncio.create_task(_loop())
    await _broadcast()
    return status()
