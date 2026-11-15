"""Prueba las ventanas de instalar y desinstalar sin enseñarlas: se abren fuera de la pantalla, sin foco ni
barra de tareas (COMPANION_UI_PRUEBA), responden «sí» solas y guardan capturas PNG para revisarlas.

    .venv\\Scripts\\python.exe scripts\\prueba_instalador.py            ventana de instalar con un instalador falso
    .venv\\Scripts\\python.exe scripts\\prueba_instalador.py --real     instalar.ps1 de verdad en una copia aparte
    .venv\\Scripts\\python.exe scripts\\prueba_instalador.py --desinstalar

Nada toca la instalación real: el instalador falso no hace nada, y --real y --desinstalar trabajan en una copia
del proyecto en la carpeta temporal (accesos directos en esa copia, sin registro de Windows, sin parar el
companion ni tocar Ollama).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS = [os.path.expandvars(r"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe"), "-NoProfile", "-STA",
      "-ExecutionPolicy", "Bypass", "-File"]
fallos = []


def ventana(script: Path, fotos: Path, timeout: int = 120, **env) -> dict:
    shutil.rmtree(fotos, ignore_errors=True)
    entorno = {**os.environ, "COMPANION_UI_PRUEBA": str(fotos), "COMPANION_PRUEBA": "1", **env}
    entorno.pop("COMPANION_UI", None)
    t = time.monotonic()
    p = subprocess.run([*PS, str(script)], env=entorno, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    resumen = fotos / "resumen.json"
    r = json.loads(resumen.read_text(encoding="utf-8-sig")) if resumen.is_file() else {"estado": "SIN RESUMEN"}
    r["segundos"] = round(time.monotonic() - t, 1)
    r["fotos"] = len(list(fotos.glob("*.png")))
    if p.returncode or p.stderr.strip():
        r["stderr"] = p.stderr.strip()[-1500:]
    return r


def comprobar(nombre: str, condicion: bool, detalle):
    print(f"{'OK ' if condicion else 'MAL'} {nombre}: {detalle}")
    if not condicion:
        fallos.append(nombre)


def falso(base: Path):
    falso_ps = str(ROOT / "tests" / "instalador_falso.ps1")
    instalar = ROOT / "scripts" / "ventana_instalar.ps1"
    r = ventana(instalar, base / "bien", COMPANION_INSTALAR_SCRIPT=falso_ps)
    comprobar("instala", r.get("estado") == "listo" and r.get("total") == 100 and all(
        v in ("hecho", "omitido") for v in r.get("pasos", {}).values()), r)
    r = ventana(instalar, base / "ligera", COMPANION_INSTALAR_SCRIPT=falso_ps, COMPANION_UI_VOZ="ligera",
                COMPANION_UI_SIN_OLLAMA="1")
    p = r.get("pasos", {})
    comprobar("solo ligera y sin Ollama", r.get("estado") == "listo" and p.get("torch") == "omitido"
              and p.get("ollama") == "omitido" and p.get("ligera") == "hecho", r)
    r = ventana(instalar, base / "falla", COMPANION_INSTALAR_SCRIPT=falso_ps, FALSO_FALLA="torch")
    comprobar("un paso que falla", r.get("estado") == "fallo" and r.get("pasos", {}).get("torch") == "error"
              and "simulado" in r.get("error", ""), r)
    r = ventana(instalar, base / "cancela", COMPANION_INSTALAR_SCRIPT=falso_ps, FALSO_PAUSA_MS="1500",
                COMPANION_UI_CANCELAR_EN="4")
    comprobar("cancelar", r.get("estado") == "cancelado" and "listo" != r.get("estado"), r)


def copia(destino: Path, con: tuple[str, ...] = ()):
    """El código del proyecto (sin lo instalado ni los datos), más las carpetas de `con` copiadas tal cual."""
    ignorar = shutil.ignore_patterns(".git", ".venv", "runtime", "data", "models", "__pycache__", "electron",
                                     "vendor", "modelos", ".env")
    shutil.copytree(ROOT, destino, ignore=ignorar)
    (destino / "models").mkdir(exist_ok=True)
    for c in con:
        if (ROOT / c).exists():
            shutil.copytree(ROOT / c, destino / c, dirs_exist_ok=True)


def enlazar(origen: Path, destino: Path):
    """Copia hecha de enlaces duros (mismo disco): varios GB sin ocupar más ni tardar."""
    for f in origen.rglob("*"):
        d = destino / f.relative_to(origen)
        if f.is_dir():
            d.mkdir(parents=True, exist_ok=True)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(f, d)
            except OSError:
                shutil.copy2(f, d)


def real(base: Path):
    """instalar.ps1 de verdad en una copia: voz ligera, sin Ollama. Para no bajar varios GB se enlazan la caché de
    librerías, el oído, la app de escritorio y las librerías 3D; la voz ligera (380 MB) sí se descarga, para ver el
    progreso de una descarga real. La copia va en data/prueba_instalador_* (mismo disco: enlaces duros)."""
    raiz = base / "proyecto"
    copia(raiz)
    # runtime\python no: uv guarda dentro un enlace de directorio que una copia rompe. uv y Python se descargan
    # (unos 50 MB: así se prueban esas descargas y la suma de uv); su caché de librerías sí se enlaza.
    for c in ("runtime/cache", "models/whisper", "desktop/electron", "web/vendor"):
        enlazar(ROOT / c, raiz / c)
    r = ventana(raiz / "scripts" / "ventana_instalar.ps1", base / "real", timeout=1800, COMPANION_UI_VOZ="ligera",
                COMPANION_UI_SIN_OLLAMA="1", COMPANION_PRUEBA_ACCESOS=str(base / "accesos"))
    comprobar("instalación real", r.get("estado") == "listo", r)
    comprobar("accesos directos", (base / "accesos" / "Escritorio" / "Companion.lnk").is_file()
              and (base / "accesos" / "Menu" / "Desinstalar Companion.lnk").is_file(), list((base / "accesos").rglob("*.lnk")))
    comprobar("voz ligera descargada", (raiz / "models" / "piper" / "es_MX-claude-high.onnx").is_file(), "models/piper")
    py = raiz / ".venv" / "Scripts" / "python.exe"
    v = subprocess.run([str(py), "-c", "import faster_whisper, fastapi, piper; print('ok')"], capture_output=True, text=True)
    comprobar("entorno del companion", v.stdout.strip() == "ok", v.stdout.strip() or v.stderr[-300:])
    print("puerto en .env:", [l for l in (raiz / ".env").read_text(encoding="utf-8").splitlines() if l.startswith("PORT")])
    # Se borra la copia (las capturas se quedan). Antes, el enlace de directorio que uv deja en runtime\python: que
    # el borrado nunca lo siga hacia fuera de la copia.
    for e in [e for e in raiz.rglob("*") if e.is_junction() or e.is_symlink()]:
        if os.path.realpath(e).lower().startswith(str(raiz.resolve()).lower()):
            os.rmdir(e) if e.is_junction() else e.unlink()
    if not any(e.is_junction() or e.is_symlink() for e in raiz.rglob("*")):
        shutil.rmtree(raiz, ignore_errors=True)


def desinstalar(base: Path):
    raiz = base / "proyecto"
    copia(raiz)
    for c, n in ((".venv/Scripts", 3), ("runtime/python", 3), ("models/whisper/large-v3-turbo", 2), ("models/piper", 2),
                 ("voz/.venv/Lib", 4), ("voz/modelos/vocos", 2), ("desktop/electron", 2), ("web/vendor/three", 1),
                 ("data/voces", 2), ("models/custom", 1)):
        (raiz / c).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (raiz / c / f"archivo{i}.bin").write_bytes(os.urandom(200_000))
    (raiz / ".env").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    accesos = base / "accesos"
    for d, n in (("Escritorio", "Companion.lnk"), ("Menu", "Companion.lnk"), ("Menu", "Desinstalar Companion.lnk")):
        (accesos / d).mkdir(parents=True, exist_ok=True)
        (accesos / d / n).write_bytes(b"x")
    script = raiz / "scripts" / "ventana_desinstalar.ps1"
    # 1) lo de siempre: el programa sí, los datos no
    r = ventana(script, base / "des1", COMPANION_PRUEBA_ACCESOS=str(accesos))
    quedan = sorted(str(p.relative_to(raiz)) for p in raiz.iterdir())
    comprobar("desinstala el programa", r.get("estado") == "listo" and not (raiz / ".venv").exists()
              and not (raiz / "runtime").exists() and not (raiz / "voz" / ".venv").exists()
              and not (raiz / "models" / "whisper").exists() and not (accesos / "Escritorio" / "Companion.lnk").exists(), r)
    comprobar("conserva los datos", (raiz / "data" / "voces").is_dir() and (raiz / ".env").is_file()
              and (raiz / "models" / "custom").is_dir() and (raiz / "companion").is_dir(), quedan)
    # 2) también los datos y la carpeta entera (no es una copia con git)
    r = ventana(script, base / "des2", COMPANION_PRUEBA_ACCESOS=str(accesos), COMPANION_UI_DATOS="1",
                COMPANION_UI_CARPETA="1")
    time.sleep(6)                                    # la carpeta se borra unos segundos después de cerrar
    comprobar("borra datos y carpeta", r.get("estado") == "listo" and not raiz.exists(), r)


def incremental(base: Path):
    """copiar_programa.ps1 entre dos versiones sintéticas: copia lo cambiado y lo nuevo, borra lo que la nueva ya no
    trae y no toca lo que no es del paquete (datos del usuario)."""
    import hashlib

    def paquete(carpeta: Path, version: str, archivos: dict):
        (carpeta / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / "comun_instalacion.ps1", carpeta / "scripts" / "comun_instalacion.ps1")
        lista = []
        for rel, texto in archivos.items():
            f = carpeta / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(texto, encoding="utf-8")
            lista.append({"p": rel, "h": hashlib.sha256(f.read_bytes()).hexdigest().upper(), "s": f.stat().st_size})
        (carpeta / "manifest.json").write_text(json.dumps({"version": version, "files": lista}), encoding="utf-8")

    destino = base / "Program Files" / "Companion"
    v1, v2 = base / "v1", base / "v2"
    paquete(v1, "1.0.0", {"a.txt": "igual", "b.txt": "versión 1", "viejo.txt": "se quita en la 2", "sub/c.txt": "c"})
    paquete(v2, "1.1.0", {"a.txt": "igual", "b.txt": "versión 2", "sub/c.txt": "c", "sub/nuevo.txt": "nuevo"})

    def copiar(origen):
        r = subprocess.run([*PS, str(ROOT / "scripts" / "copiar_programa.ps1"), "-Origen", str(origen), "-Destino", str(destino)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    codigo, salida = copiar(v1)
    comprobar("primera copia", codigo == 0 and (destino / "viejo.txt").is_file(), salida)
    (destino / "data").mkdir(exist_ok=True)
    (destino / "data" / "mio.txt").write_text("datos del usuario", encoding="utf-8")
    a_antes = (destino / "a.txt").stat().st_mtime_ns
    time.sleep(0.05)
    codigo, salida = copiar(v2)
    ok = (codigo == 0 and (destino / "b.txt").read_text(encoding="utf-8") == "versión 2" and not (destino / "viejo.txt").exists()
          and (destino / "sub" / "nuevo.txt").is_file() and (destino / "data" / "mio.txt").is_file()
          and (destino / "a.txt").stat().st_mtime_ns == a_antes
          and json.loads((destino / "manifest.json").read_text(encoding="utf-8"))["version"] == "1.1.0")
    comprobar("actualización incremental", ok and "2 archivos nuevos o cambiados, 1 quitados, 2 iguales" in salida[0], salida)
    (destino / ".git").mkdir()
    codigo, salida = copiar(v2)
    comprobar("no toca una copia con git", codigo != 0, salida)


def paquete_real(base: Path):
    """El .exe de un Release, de verdad: instala en «Program Files/Companion» dentro de data (ruta con espacios),
    con la voz ligera y sin Ollama; luego se abre otra vez sobre la misma carpeta, que no debe copiar ni descargar nada."""
    r = subprocess.run([*PS, str(ROOT / "scripts" / "crear_instalador.ps1"), "-Salida", str(base / "dist")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    exe = next((base / "dist").glob("Companion-Setup-*.exe"), None)
    comprobar("crear el instalador", r.returncode == 0 and exe is not None, r.stdout.strip()[-200:] or r.stderr[-300:])
    if not exe:
        return
    destino = base / "Program Files" / "Companion"
    for c in ("runtime/cache", "models/whisper", "desktop/electron", "web/vendor"):     # lo grande, enlazado
        enlazar(ROOT / c, destino / c)

    def instalar(fotos: str) -> dict:
        entorno = {**os.environ, "COMPANION_UI_PRUEBA": str(base / fotos), "COMPANION_PRUEBA": "1", "COMPANION_UI_VOZ": "ligera",
                   "COMPANION_UI_SIN_OLLAMA": "1", "COMPANION_UI_DESTINO": str(destino), "COMPANION_PRUEBA_ACCESOS": str(base / "accesos")}
        entorno.pop("COMPANION_UI", None)
        t = time.monotonic()
        subprocess.run([str(exe)], env=entorno, timeout=1800)
        res = base / fotos / "resumen.json"
        out = json.loads(res.read_text(encoding="utf-8-sig")) if res.is_file() else {"estado": "SIN RESUMEN"}
        out["segundos"] = round(time.monotonic() - t, 1)
        return out
    r1 = instalar("paquete1")
    comprobar("instala desde el .exe", r1.get("estado") == "listo" and r1.get("pasos", {}).get("programa") == "hecho", r1)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    man = json.loads((destino / "manifest.json").read_text(encoding="utf-8")) if (destino / "manifest.json").is_file() else {}
    comprobar("versión y personajes", man.get("version") == version and (destino / "models" / "avatar1.vrm").is_file()
              and (destino / "models" / "avatar2.vrm").is_file(), {"version": man.get("version")})
    py = destino / ".venv" / "Scripts" / "python.exe"
    v = subprocess.run([str(py), "-c", "import fastapi, piper; print('ok')"], capture_output=True, text=True)
    comprobar("entorno del companion", v.stdout.strip() == "ok", v.stdout.strip() or v.stderr[-300:])
    venv_antes = (destino / ".venv" / "pyvenv.cfg").stat().st_mtime_ns
    r2 = instalar("paquete2")
    log = (destino / "data" / "instalacion.log").read_text(encoding="utf-8", errors="replace")
    comprobar("abrirlo otra vez no repite nada", r2.get("estado") == "listo" and "0 archivos nuevos o cambiados" in log
              and (destino / ".venv" / "pyvenv.cfg").stat().st_mtime_ns == venv_antes and r2["segundos"] < r1["segundos"],
              {"primera": r1["segundos"], "segunda": r2["segundos"]})
    for e in [e for e in destino.rglob("*") if e.is_junction() or e.is_symlink()]:
        if os.path.realpath(e).lower().startswith(str(destino.resolve()).lower()):
            os.rmdir(e) if e.is_junction() else e.unlink()
    if not any(e.is_junction() or e.is_symlink() for e in destino.rglob("*")):
        shutil.rmtree(destino, ignore_errors=True)


if __name__ == "__main__":
    if "--real" in sys.argv or "--paquete" in sys.argv:    # en el mismo disco que el proyecto, para los enlaces duros
        (ROOT / "data").mkdir(exist_ok=True)
        base = Path(tempfile.mkdtemp(prefix="prueba_instalador_", dir=ROOT / "data"))
    else:
        base = Path(tempfile.mkdtemp(prefix="companion_instalador_"))
    print("Capturas en", base)
    if "--real" in sys.argv:
        real(base)
    elif "--paquete" in sys.argv:
        incremental(base / "incremental")
        paquete_real(base)
    elif "--desinstalar" in sys.argv:
        desinstalar(base)
    else:
        falso(base)
    print("\nTodo bien." if not fallos else f"\nFALLOS: {fallos}")
    sys.exit(1 if fallos else 0)
