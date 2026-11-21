"""¿Hay una versión nueva? Mira los Releases públicos del proyecto en GitHub (como mucho cada 12 horas) y avisa
en la interfaz con el enlace para descargarla. No envía nada del usuario: es una consulta anónima a la lista de
Releases. Se apaga con UPDATE_CHECK=0 en .env.
Solo cuentan las etiquetas vX.Y.Z publicadas (no las de prueba ni las de iOS) que traen el instalador de este
sistema: una versión «(solo Windows)» no trae .dmg y no se le anuncia al Mac."""
import json
import logging
import os
import re
import sys
import time

import httpx

from .config import MAC, ROOT, settings

log = logging.getLogger("companion.update")
REPO = "dannymzyq/companion-ai"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
PAGE = f"https://github.com/{REPO}/releases/"
CACHE = settings.data_dir / "actualizacion.json"
EVERY_S = 12 * 3600
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def current() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def _key(version: str) -> tuple[int, ...]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _asset_ok(names: list[str]) -> bool:
    if MAC:
        return any(n.endswith("-mac.dmg") for n in names)
    if sys.platform == "win32":
        return any(n.startswith("Companion-Setup-") and n.endswith(".exe") for n in names)
    return True


def pick(releases: list[dict]) -> dict | None:
    """La versión más alta publicada para este sistema: {version, url}."""
    best = None
    for r in releases if isinstance(releases, list) else []:
        tag = str(r.get("tag_name") or "")
        if r.get("draft") or r.get("prerelease") or not _TAG.match(tag):
            continue
        if not _asset_ok([str(a.get("name") or "") for a in r.get("assets") or []]):
            continue
        url = str(r.get("html_url") or "")
        if not url.startswith(PAGE):
            url = PAGE + "tag/" + tag
        if best is None or _key(tag) > _key(best["version"]):
            best = {"version": tag[1:], "url": url}
    return best


def _read_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def check() -> dict:
    """{current, latest, url, newer}. Sin red, o si GitHub no responde, simplemente no hay aviso."""
    now = current()
    out = {"current": now, "latest": None, "url": None, "newer": False}
    if os.getenv("UPDATE_CHECK", "1").strip() == "0":
        return out
    cache = _read_cache()
    if time.time() - float(cache.get("at", 0)) > EVERY_S:
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Companion-update-check",
                                                              "Accept": "application/vnd.github+json"}) as c:
                r = await c.get(API)
            if r.status_code == 200:
                cache = {"at": time.time(), "best": pick(r.json())}
                try:
                    CACHE.write_text(json.dumps(cache), encoding="utf-8")
                except OSError:
                    pass
            else:
                log.info("No pude mirar si hay versión nueva (GitHub respondió %s)", r.status_code)
        except (httpx.HTTPError, ValueError) as e:
            log.info("No pude mirar si hay versión nueva (%s)", type(e).__name__)
    best = cache.get("best") or None
    if best:
        out.update(latest=best["version"], url=best["url"], newer=_key(best["version"]) > _key(now))
    return out
