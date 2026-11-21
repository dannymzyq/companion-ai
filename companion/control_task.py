"""Usar una ventana con ratón y teclado, paso a paso (la acción «controlar»). Separado de session.py.

Cada paso: se lee la ventana (accesibilidad y, si compartes la pantalla, una imagen de esa ventana), el modelo
elige un paso, lo delicado se confirma (salvo que tu orden ya lo pidiera) y se hace en segundo plano, escalando
de forma cada vez más directa (control.py). Se para con Esc, diciendo «para» o si cambias a esa ventana.
"""
import asyncio
import logging
import re
import time

from . import actions, control, desktop_scene, llm
from .config import settings, shown
from .prompt import ACTION_RESULT, OPERATOR, OPERATOR_COORDS, OPERATOR_STEP

log = logging.getLogger("companion.session")


def _anim(verb: str) -> str:
    """Qué animación hace el personaje en ese paso (modo flotante): señalar, teclear o desplazar."""
    return {"pulsar": "click", "clic": "click", "doble_clic": "click", "escribir": "type", "teclear": "type",
            "tecla": "type", "atajo": "type", "rueda": "scroll"}.get(verb, "read")


async def _where(hwnd: int) -> dict | None:
    """Dónde está la ventana, para la animación. Nunca debe frenar ni romper la tarea."""
    try:
        return await asyncio.to_thread(desktop_scene.window, hwnd)
    except Exception:  # noqa: BLE001
        return None


def _point(item, xy, shot) -> list[int] | None:
    """Punto de la pantalla (píxeles reales) que toca ese paso, si se sabe."""
    try:
        if item is not None and item.box:
            return [(item.box[0] + item.box[2]) // 2, (item.box[1] + item.box[3]) // 2]
        if xy and shot:
            return list(shot.to_screen(*xy))
    except Exception:  # noqa: BLE001
        pass
    return None


async def run(sess, req: actions.Request):
    """La tarea entera. `sess` es la Session de la conversación (para avisar a la interfaz y contar el resultado)."""
    win, task = req.target["window"], req.target["task"]
    sess.controlling, sess.control_stop = {"title": win.title, "task": task}, False
    # Dónde está la ventana: en el modo flotante el personaje va a su lado y se le ve trabajando (desktop/pet.js).
    await sess.send_json({"type": "control_start", "title": win.title[:60], "task": task, "max": control.MAX_STEPS,
                          "window": await _where(win.hwnd)})
    steps: list[str] = []
    result, ok, bad, last_typed = "", False, 0, None
    # ¿cambió algo? · pasos seguidos sin efecto · cuántas veces se probó cada paso (cada vez, de forma más directa)
    last_sig, still, attempts, last_texts, written = None, 0, {}, [], set()
    limit = time.monotonic() + control.MAX_SECONDS
    sees = sess._sharing_screen() and llm.sees_images()
    system = OPERATOR.format(user=settings.user_name, task=task,
                             sees=", una imagen de la ventana" if sees else "",
                             coords=OPERATOR_COORDS if sees else "")
    try:
        # En segundo plano: la ventana NO se trae al frente. Solo un paso que necesite el teclado o el ratón de
        # verdad lo hace, y únicamente si no estás usando la PC (control.real_input).
        with control.EscWatch() as esc:
            for n in range(1, control.MAX_STEPS + 1):
                if esc.pressed or sess.control_stop or sess.closed:
                    result = f"{settings.user_name} lo paró" + (" con Esc" if esc.pressed else "")
                    break
                if time.monotonic() > limit:
                    result = "se acabó el tiempo máximo de la tarea"
                    break
                if not control.user32.IsWindow(win.hwnd):
                    result = "la ventana se cerró"
                    break
                if win.hwnd in control._fronted and control.user32.GetForegroundWindow() != win.hwnd:
                    result = f"{settings.user_name} cambió a otra ventana, así que me detuve"
                    break
                items, texts = await asyncio.to_thread(control.snapshot, win.hwnd)
                sig = control.signature(items, texts)
                if last_sig is not None and sig == last_sig and steps and "no se pudo" not in steps[-1]:
                    steps[-1] += " — no cambió nada en la ventana"
                    still += 1
                    if still >= 4:
                        result = "varios pasos seguidos sin cambiar nada en la ventana"
                        break
                elif last_sig is not None:
                    still = 0
                    # qué apareció de nuevo: así el modelo nota «sonando…» o «guardado» y sabe que ya está
                    new = [t for t in texts if t not in last_texts][:3]
                    if new and steps and "no se pudo" not in steps[-1]:
                        steps[-1] += " — ahora se ve: " + " | ".join(f"«{t[:70]}»" for t in new)
                last_sig, last_texts = sig, texts
                shot = None
                if sees:
                    try:
                        shot = await asyncio.to_thread(control.capture, win.hwnd)
                    except Exception as e:  # noqa: BLE001
                        log.warning("No pude capturar la ventana: %s", e)
                prompt = OPERATOR_STEP.format(window=control.describe(win.title, items, texts, shot),
                                              steps="\n".join(steps) or "(ninguno todavía)")
                images = [llm.Image("window", shot.jpeg, win.title[:60])] if shot else []
                messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
                # background: en la nube, cada paso va primero al modelo de más cuota (no gasta la de la charla)
                reply = "".join([p async for p in llm.stream_chat(messages, {"temperature": 0.2, "top_p": 0.9, "max_tokens": 450},
                                                                  images, background=True)])
                llm.pop_notices()
                step = control.parse(reply)
                log.info("Control %d%s: %s → %s", n, " (con imagen)" if shot else "", shown(reply[:120]),
                         step and (step[0], [a[:60] if settings.log_text else f"<{len(a)}>" for a in step[1]]))
                if esc.pressed or sess.control_stop:
                    result = f"{settings.user_name} lo paró" + (" con Esc" if esc.pressed else "")
                    break
                if step is None:
                    bad += 1
                    if bad >= 3:
                        result = "no supe qué paso dar"
                        break
                    continue
                verb, args = step
                if verb == "listo":
                    ok, result = True, args[0] if args else "tarea hecha"
                    break
                if verb == "no_puedo":
                    result = "no se pudo: " + (args[0] if args else "sin motivo")
                    break

                # ---- a qué se refiere y cómo describirlo
                item, xy, name, problem = None, None, "", ""
                coords = re.findall(r"-?\d+", args[0]) if args else []
                if verb in ("clic", "doble_clic") and len(coords) >= 2:
                    if not shot:
                        problem = "sin imagen de la ventana no hay clic por coordenadas: usa el número del control"
                    else:
                        xy = (int(coords[0]), int(coords[1]))
                        name = await asyncio.to_thread(control.name_at, shot, *xy)
                elif verb in ("pulsar", "escribir", "doble_clic", "clic"):
                    item = control.pick(items, args[0], "escribir" if verb == "escribir" else "pulsar") if args else None
                    if item is None:
                        problem = f"no hay ningún control «{args[0] if args else ''}»"
                    elif verb == "escribir" and len(args) < 2:
                        problem = "falta el texto: escribir N | texto"
                    name = item.name if item else ""
                if not problem and verb == "escribir" and item and (item.kind, item.name) in written and len(args[1]) > 60:
                    # un párrafo ya escrito no se repite (el modelo tendía a escribirlo otra vez)
                    problem = f"ya escribiste ese texto en «{item.name or item.kind}»: si está bien, responde listo"
                elif verb == "tecla" and (not args or control._plain(args[0]) not in control.KEYS):
                    problem = f"no conozco la tecla «{args[0] if args else ''}»"
                elif verb in ("atajo", "teclear", "rueda") and not args:
                    problem = "le falta el dato"
                if problem:
                    bad += 1
                    steps.append(f"{n}. (paso no válido: {problem})")
                    if bad >= 4:
                        result = "se equivocó varias veces"
                        break
                    continue
                key = control._plain(args[0]) if verb == "tecla" else ""
                target = f"«{item.name or item.kind}»" if item else (f"({xy[0]},{xy[1]})" + (f" «{name[:40]}»" if name else "")) if xy else ""
                desc = {"pulsar": f"Pulsar {target}", "clic": f"Clic en {target}", "doble_clic": f"Doble clic en {target}",
                        "escribir": f"Escribir «{args[1][:60]}» en {target}" if len(args) > 1 else "",
                        "teclear": f"Teclear «{args[0][:60]}»", "tecla": f"Tecla {key}", "atajo": f"Atajo {args[0][:20]}",
                        "rueda": f"Rueda {args[0][:10]}"}[verb]
                # el mismo paso puede repetirse dos veces (cada una de forma más directa); a la cuarta, se para
                if len(steps) >= 3 and all(s.split(" — ")[0].endswith(desc) for s in steps[-3:]):
                    result = "se quedó repitiendo el mismo paso"
                    break

                # ---- lo delicado se confirma, salvo que la orden del usuario ya lo pidiera
                kind = "enter" if key == "enter" or (verb == "atajo" and "enter" in control._plain(args[0])) else verb
                if control.needs_confirm(kind, name, last_typed, win.title) and not control.task_allows(task, name):
                    if not await sess._confirm(f"{desc} en «{win.title[:50]}»"):
                        steps.append(f"{n}. {desc} — {settings.user_name} NO lo aprobó")
                        result = f"{settings.user_name} no aprobó «{desc}»"
                        actions.log_entry("controlar", f"{desc} en «{win.title}»", "negada", "")
                        break
                await sess.send_json({"type": "control_step", "n": n, "max": control.MAX_STEPS, "text": desc,
                                      "kind": _anim(verb), "point": _point(item, xy, shot),
                                      "window": await _where(win.hwnd)})

                # ---- hacerlo: si este mismo paso ya se probó sin efecto, se prueba de forma más directa
                # (accesibilidad → mensajes a la ventana → teclado y ratón de verdad, solo si no usas la PC)
                k = (verb, item.kind if item else "", item.name if item else "", xy, key, args[0][:40] if args else "")
                attempt = attempts[k] = attempts.get(k, -1) + 1

                def do():
                    if verb == "pulsar":
                        return control.press(item, win.hwnd, attempt)
                    if verb == "escribir":
                        return control.type_text(item, args[1][:3000], win.hwnd, attempt)
                    if verb in ("clic", "doble_clic") and xy:
                        return control.click_at(shot, *xy, win.hwnd, double=verb == "doble_clic", attempt=attempt)
                    if verb in ("clic", "doble_clic"):
                        return control.click_item(item, win.hwnd, double=verb == "doble_clic", attempt=attempt)
                    if verb == "teclear":
                        return control.type_here(args[0][:3000], win.hwnd, attempt)
                    if verb == "tecla":
                        return control.key(key, win.hwnd, attempt)
                    if verb == "atajo":
                        return control.hotkey(args[0], win.hwnd, attempt)
                    return control.scroll(win.hwnd, "arriba" not in control._plain(args[0]), attempt)
                try:
                    esc.sending = verb in ("tecla", "atajo", "teclear", "escribir")
                    how = await asyncio.to_thread(do)
                except control.ControlError as e:
                    steps.append(f"{n}. {desc} — no se pudo: {e}")
                    actions.log_entry("controlar", f"{desc} en «{win.title}»", "paso", f"no se pudo: {e}")
                    if "Cambiaste a otra ventana" in str(e):          # tomaste el control: se detiene
                        result = str(e)
                        break
                    bad += 1
                    if bad >= 4:
                        result = str(e)
                        break
                    continue
                finally:
                    esc.sending = False
                if verb == "escribir":
                    last_typed = item
                    if len(args[1]) > 60:
                        written.add((item.kind, item.name))
                # Un texto ya escrito no se repite: sin esto, el modelo volvía a teclear el mismo párrafo.
                done_note = " — HECHO: ese texto ya está escrito ahí; no lo vuelvas a escribir" if verb in ("escribir", "teclear") else ""
                steps.append(f"{n}. {desc}{done_note}")
                actions.log_entry("controlar", f"{desc} en «{win.title}»", "paso", how)
                await asyncio.sleep(0.9)                 # que la ventana se actualice antes de mirarla otra vez
            else:
                result = f"llegó al límite de {control.MAX_STEPS} pasos"
    except Exception as e:  # noqa: BLE001
        log.exception("El control de la ventana falló")
        result = f"falló ({type(e).__name__})"
    finally:
        sess.controlling = None
        await asyncio.to_thread(control.release, win.hwnd)   # si la trajo al frente, te devuelve tu ventana
    actions.log_entry("controlar", req.detail, "terminada" if ok else "sin terminar", result)
    await sess.send_json({"type": "control_end", "ok": ok, "text": result})
    done = "; ".join(s.split(". ", 1)[-1] for s in steps) or "ninguno"
    summary = (f"la tarea se completó: {result}. Pasos: {done}" if ok else
               f"la tarea NO se completó ({result}). No digas que está hecha. Pasos que sí se dieron: {done}")
    sess._later(ACTION_RESULT.format(user=settings.user_name, title=req.detail, result=summary))
