"""Arranque y cierre del companion (15 nov 2026).

· loading(): qué se está cargando todavía (el oído, la voz, el cerebro local), para la pantalla de carga de la
  interfaz, al abrir y después de cambiar un ajuste.
· shutdown(): apagado ordenado (para el servidor de voz, saca el modelo local de Ollama y cierra el proceso). Lo
  piden detener.ps1/detener.sh al cerrar la ventana.
· watch_owner(pid): la ventana (Electron) se registra al abrir; si su proceso desaparece sin cerrar bien (se colgó,
  se cerró desde el Administrador de tareas), el servidor se apaga solo y no se queda ocupando memoria."""
import asyncio
import logging
import os
import sys

log = logging.getLogger("companion")
_owner_task: asyncio.Task | None = None
_stopping = False


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x1000 | 0x00100000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not h:
            return ctypes.get_last_error() == 5                      # sin permiso: existe
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102   # WAIT_TIMEOUT: sigue vivo
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def loading(transcriber) -> dict:
    """[{id, label, state: cargando|listo|error, detail}] y si queda algo cargando."""
    from . import llm, tts, tts_light, voz_proc
    from .config import settings
    from . import profile
    from .realtime import LIVE_PROVIDERS
    if profile.live_ready():
        # En vivo el proveedor oye, piensa y habla: no se carga Whisper ni la voz completa (21 nov 2026).
        lv = profile.live()
        return {"items": [{"id": "vivo", "label": f"La conversación en vivo ({LIVE_PROVIDERS[lv['provider']]['name']})",
                           "state": "listo", "detail": "sin modelos en tu PC"}], "busy": False}
    items = []
    if transcriber.engine == "nube":
        items.append({"id": "oido", "label": "El oído", "state": "listo", "detail": "en la nube"})
    elif transcriber.error:
        items.append({"id": "oido", "label": "El oído (Whisper)", "state": "error", "detail": "no pudo cargar: puedes escribirle"})
    else:
        items.append({"id": "oido", "label": f"El oído (Whisper {transcriber.model_name})",
                      "state": "listo" if transcriber.ready else "cargando",
                      "detail": {"cuda": "en la tarjeta gráfica", "mps": "en la GPU del Mac", "cpu": "en el procesador"}.get(transcriber.device or "", "")})
    engine = settings.voice_engine
    if engine == "completa":
        h = await asyncio.to_thread(voz_proc._health)
        if h.get("tts", "none") != "none":
            items.append({"id": "voz", "label": "La voz completa", "state": "listo", "detail": h.get("device", "")})
        elif h.get("error"):
            items.append({"id": "voz", "label": "La voz completa", "state": "error",
                          "detail": "no pudo cargar: suena la voz ligera"})
        elif not voz_proc.installed():
            items.append({"id": "voz", "label": "La voz completa", "state": "error", "detail": "no está instalada"})
        else:
            items.append({"id": "voz", "label": "La voz completa (F5-TTS)", "state": "cargando", "detail": "unos segundos"})
    elif engine == "ligera":
        ok = tts_light.installed()
        items.append({"id": "voz", "label": "La voz ligera", "state": "listo" if ok else "error",
                      "detail": "" if ok else "no está descargada"})
    else:
        ok = await tts.available()
        items.append({"id": "voz", "label": "La voz en la nube", "state": "listo" if ok else "error"})
    st = llm.status()
    if settings.is_cloud:
        items.append({"id": "cerebro", "label": "El cerebro en la nube", "state": "listo" if st["ready"] else "error",
                      "detail": st.get("detail", "")})
    else:
        w = llm.warming
        state = "cargando" if w.get("state") == "cargando" else "error" if w.get("state") == "error" else "listo"
        items.append({"id": "cerebro", "label": f"El cerebro local ({w.get('model') or st['model']})", "state": state,
                      "detail": "Ollama no responde" if state == "error" else ""})
    return {"items": items, "busy": any(i["state"] == "cargando" for i in items)}


async def shutdown(reason: str = ""):
    """Apaga todo lo que arrancó el companion y cierra el proceso."""
    global _stopping
    if _stopping:
        return
    _stopping = True
    await asyncio.sleep(0.2)                     # que salga antes la respuesta a quien lo pidió
    from . import llm, voz_proc
    log.info("Apagando el companion%s", f" ({reason})" if reason else "")
    try:
        await asyncio.to_thread(voz_proc.stop)
    except Exception:  # noqa: BLE001
        pass
    if llm._ours or llm._fallback_loaded:        # solo lo que cargó este proceso (no los modelos de otro companion)
        try:
            await asyncio.wait_for(llm.unload_local(sorted(llm._ours | ({llm.local_model()} if llm._fallback_loaded else set()))),
                                   timeout=8)
        except Exception:  # noqa: BLE001
            pass
    logging.shutdown()
    os._exit(0)


def watch_owner(pid: int):
    """Vigila el proceso de la ventana: si muere, el servidor se apaga (una sola vigilancia: la última manda)."""
    global _owner_task

    async def run():
        while True:
            await asyncio.sleep(3)
            if not pid_alive(pid):
                await asyncio.sleep(5)                   # por si es un cambio de ventana: otra puede registrarse
                if _owner_task is task:
                    await shutdown(f"la ventana (proceso {pid}) se cerró")
                return
    if _owner_task and not _owner_task.done():
        _owner_task.cancel()
    task = asyncio.get_running_loop().create_task(run())
    _owner_task = task
    log.info("La ventana (proceso %s) es la dueña del servidor: si se cierra, se apaga", pid)
