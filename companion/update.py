"""¿Hay una versión nueva? Mira los Releases públicos del proyecto en GitHub (como mucho cada 12 horas) y avisa
en la interfaz con el enlace (o descarga verificada por SHA-256 en 1 clic). No envía nada del usuario: es una
consulta anónima a la lista de Releases. Se apaga con UPDATE_CHECK=0 en .env."""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from .config import MAC, ROOT, settings

log = logging.getLogger("companion.update")
REPO = "dannymzyq/companion-ai"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
PAGE = f"https://github.com/{REPO}/releases/"
DL_PREFIX = f"https://github.com/{REPO}/releases/download/"
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


def _match_installer(name: str) -> bool:
    if MAC:
        return name.endswith("-mac.dmg")
    if sys.platform == "win32":
        return name.startswith("Companion-Setup-") and name.endswith(".exe")
    return False


def _asset_ok(names: list[str]) -> bool:
    if MAC or sys.platform == "win32":
        return any(_match_installer(n) for n in names)
    return True


def pick(releases: list[dict]) -> dict | None:
    """La versión más alta publicada para este sistema: {version, url, asset_url, asset_name, sums_url}."""
    best = None
    for r in releases if isinstance(releases, list) else []:
        tag = str(r.get("tag_name") or "")
        if r.get("draft") or r.get("prerelease") or not _TAG.match(tag):
            continue
        assets = [a for a in (r.get("assets") or []) if isinstance(a, dict)]
        names = [str(a.get("name") or "") for a in assets]
        if not _asset_ok(names):
            continue
        url = str(r.get("html_url") or "")
        if not url.startswith(PAGE):
            url = PAGE + "tag/" + tag
        inst = next((a for a in assets if _match_installer(str(a.get("name") or ""))), None)
        sums = next((a for a in assets if str(a.get("name") or "").upper() in ("SHA256SUMS.TXT", "SHA256SUMS")), None)
        if best is None or _key(tag) > _key(best["version"]):
            best = {
                "version": tag[1:],
                "url": url,
                "asset_name": str(inst.get("name") or "") if inst else None,
                "asset_url": str(inst.get("browser_download_url") or "") if inst else None,
                "sums_url": str(sums.get("browser_download_url") or "") if sums else None,
            }
    return best


def _read_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def check() -> dict:
    """{current, latest, url, newer, asset_url, asset_name}."""
    now = current()
    out = {"current": now, "latest": None, "url": None, "newer": False, "asset_url": None, "asset_name": None}
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
        out.update(
            latest=best["version"],
            url=best["url"],
            newer=_key(best["version"]) > _key(now),
            asset_url=best.get("asset_url"),
            asset_name=best.get("asset_name"),
            sums_url=best.get("sums_url"),
        )
    return out


async def download_and_verify(*, launch: bool = False) -> dict:
    """Descarga el instalador de la última versión oficial a %TEMP% y lo comprueba con SHA256SUMS.txt.

    Sin huella con la que comprobarlo no se descarga ni se abre (27 nov 2026: antes se abría igual, sin comprobar)."""
    info = await check()
    asset_url = str(info.get("asset_url") or "")
    asset_name = re.sub(r"[^\w.\-]+", "", str(info.get("asset_name") or ""))
    if not info.get("newer") or not asset_url.startswith(DL_PREFIX) or not asset_name:
        raise ValueError("No hay ningún instalador nuevo disponible para descargar.")
    dest_dir = Path(tempfile.gettempdir()) / "companion_update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / asset_name
    part = dest.with_suffix(dest.suffix + ".part")

    expected_sha = None
    sums_url = str(info.get("sums_url") or "")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), follow_redirects=True,
                                 headers={"User-Agent": "Companion-updater"}) as client:
        if sums_url.startswith(DL_PREFIX):
            rs = await client.get(sums_url)
            if rs.status_code == 200:
                for line in rs.text.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                        expected_sha = parts[0].lower()
                        break
        if not expected_sha:
            raise ValueError("No pude comprobar el instalador nuevo: la versión no trae su huella SHA-256 "
                             "(SHA256SUMS.txt). Por seguridad no lo descargo; bájalo desde la página de la versión.")
        h = hashlib.sha256()
        async with client.stream("GET", asset_url) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
        got_sha = h.hexdigest().lower()
        if got_sha != expected_sha:
            part.unlink(missing_ok=True)
            raise ValueError("La huella SHA-256 del instalador descargado no coincide. Se canceló por seguridad.")
        part.replace(dest)

    if launch and os.getenv("COMPANION_ACTIONS_DRY") != "1":
        if sys.platform == "win32":
            os.startfile(str(dest))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(dest)])
    return {"ok": True, "path": str(dest), "sha256": got_sha, "verified": True, "launched": bool(launch)}
