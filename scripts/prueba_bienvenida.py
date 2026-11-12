"""Prueba la bienvenida (primer arranque) en la app de escritorio oculta, con un servidor de prueba recién
estrenado: perfil → clave de API (y la pantalla del modelo local) → voz → modelo 3D → tarjeta de micrófono y
cámara. Comprueba que todo queda guardado, que al recargar no se repite, que se puede cambiar desde Ajustes,
que el personaje toma el nombre de la voz y que «Empezar de nuevo» repite la bienvenida o restablece los datos.
No inicia ninguna conversación; solo gasta una consulta de «lista de modelos» al comprobar la clave.

    .venv\\Scripts\\python.exe scripts\\prueba_bienvenida.py
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _prueba  # noqa: E402  (antes que companion.*: aísla datos, modelos y puerto)
from prueba_escritorio import ELECTRON, PORT, ROOT, Pagina, pagina  # noqa: E402

VER = """(() => { const o = document.getElementById('onboard'); const s = [...o.querySelectorAll('section')].find(x => !x.hidden);
  return { abierta: !o.hidden, paso: s ? s.dataset.step : null, error: document.getElementById('ob-error').hidden ? null : document.getElementById('ob-error').textContent,
           puntos: [...document.querySelectorAll('#ob-dots i')].map(i => i.className ? 1 : 0).join('') }; })()"""
SIGUIENTE = "document.getElementById('ob-next').click()"


async def main():
    if not ELECTRON.exists():
        sys.exit("Falta Electron: ejecuta scripts\\instalar_escritorio.ps1")
    env = {**os.environ, "COMPANION_TEST": "1", "COMPANION_TEST_PORT": str(PORT), "COMPANION_URL": _prueba.URL}
    env.pop("ELECTRON_RUN_AS_NODE", None)
    proc = subprocess.Popen([str(ELECTRON), str(ROOT / "desktop")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    api = httpx.Client(base_url=_prueba.URL, timeout=30)
    try:
        url, _ = await pagina(_prueba.URL)
        async with connect(url, max_size=None) as ws:
            p = Pagina(ws)
            await p.cmd("Runtime.enable")
            await p.cmd("Page.enable")
            await asyncio.sleep(4)

            async def paso(accion: str, espera: float = 1.5):
                await p.js(accion + "; null")
                await asyncio.sleep(espera)
                return await p.js(VER)

            v = await p.js(VER)
            print("1. primer arranque  :", v)
            assert v["abierta"] and v["paso"] == "perfil", "la bienvenida no apareció en el primer arranque"

            v = await paso(SIGUIENTE)                                   # sin datos: no deja pasar
            assert v["paso"] == "perfil" and v["error"], "dejó pasar con el perfil vacío"
            sin_datos = v["error"]
            await p.js("""document.getElementById('ob-user').value = 'Ana'; document.getElementById('ob-year').value = '2000';
                          document.querySelector('#ob-gender [data-value=mujer]').click(); null""")
            v = await paso(SIGUIENTE)
            print(f"2. perfil           : vacío → {sin_datos!r} · con datos → paso «{v['paso']}»")
            assert v["paso"] == "cerebro", v

            proveedores = await p.js("[...document.getElementById('ob-preset').options].map(o => o.text)")
            guardada = await p.js("document.getElementById('ob-key').placeholder")
            await p.js("document.getElementById('ob-key').value = 'clave-falsa-123456'; document.getElementById('ob-key').dispatchEvent(new Event('input')); null")
            v = await paso(SIGUIENTE, 4)
            mala = v["error"]
            assert v["paso"] == "cerebro" and mala, "aceptó una clave falsa"
            # sin clave → pantalla del modelo local, con el recomendado para esta PC
            v = await paso("document.getElementById('ob-go-local').click()", 2.5)
            local = await p.js("""({ gpu: document.getElementById('ob-gpu').textContent,
                modelos: [...document.querySelectorAll('#ob-local-list .model-row')].map(r => r.querySelector('b').textContent + (r.classList.contains('off') ? ' [sin descargar]' : '') + (r.classList.contains('on') ? ' [elegido]' : '') + ' · ' + r.querySelector('small').textContent.split('.').slice(-2)[0].trim()) })""")
            assert "quedan unos" in local["gpu"] and any("Recomendado" in m for m in local["modelos"]) and any("Cabe" in m for m in local["modelos"]), local
            assert v["paso"] == "local" and local["modelos"], v
            v = await paso("document.getElementById('ob-back').click()")
            assert v["paso"] == "cerebro", v
            await p.js("document.getElementById('ob-key').value = ''; document.getElementById('ob-key').dispatchEvent(new Event('input')); null")
            v = await paso(SIGUIENTE, 5)                                # con la clave que ya estaba guardada
            print(f"3. cerebro          : proveedores={proveedores} · {guardada[:14]!r}… · clave falsa → {mala!r} · correcta → paso «{v['paso']}»")
            print(f"   modelo local     : {local}")
            assert v["paso"] == "modelo", v

            # personaje: antes que la voz, y con vista previa en vivo detrás de la tarjeta
            modelos = await p.js("[...document.querySelectorAll('#ob-models .model-row')].map(r => r.querySelector('b').textContent + (r.classList.contains('on') ? ' [elegido]' : ''))")
            subir = await p.js("!document.getElementById('ob-upload').hidden && document.getElementById('ob-upload').textContent")
            vista = {"a la vista": await p.js("document.getElementById('onboard').classList.contains('preview') && getComputedStyle(document.getElementById('start')).visibility === 'hidden'")}
            elegir = "[...document.querySelectorAll('#ob-models .pick')].find(b => b.querySelector('b').textContent === %s).click()"
            for nombre, clave in (("Esfera", "esfera"), ("Chico", "chico")):
                await paso(elegir % json.dumps(nombre), 4)
                a = await p.js("({esfera: !!window.companion.avatar.orb, vrm: !!window.companion.avatar.vrm, cargado: window.companion.avatar.loaded})")
                vista[nombre] = a
                assert a["cargado"] and a["esfera"] == (clave == "esfera"), a
            v = await paso(SIGUIENTE)
            print(f"4. personaje        : {modelos} · botón «{subir}» · vista previa={vista} → paso «{v['paso']}»")
            assert v["paso"] == "voz" and {"Chica", "Chico", "Esfera"} <= {m.split(" [")[0] for m in modelos}

            voces = await p.js("[...document.querySelectorAll('#ob-voices .model-row')].map(r => r.querySelector('b').textContent + (r.classList.contains('off') ? ' (próximamente)' : '') + (r.classList.contains('on') ? ' [elegida]' : ''))")
            grupos = await p.js("document.querySelectorAll('#ob-voices .voice-group').length")
            genero = await p.js("/femenin|masculin|neutr/i.test(document.getElementById('ob-voices').textContent + document.getElementById('ob-models').textContent)")
            botones = await p.js("document.querySelectorAll('#ob-voices button.side').length")
            muestra = api.post("/api/voices/preview", json={"id": "kenji"})
            await p.js("[...document.querySelectorAll('#ob-voices .model-row .pick')].find(b => b.querySelector('b').textContent === 'Kenji').click(); null")
            print(f"5. voz              : grupos de género={grupos}, etiquetas de género={genero} · {voces} · botones ▶ de muestra: {botones} · muestra de Kenji: {muestra.status_code}, {len(muestra.content) // 1024} KB de WAV")
            assert len(voces) == 9 and botones == 9 and not any("próximamente" in x for x in voces) and not grupos and not genero
            assert {v.split(" [")[0] for v in voces} == {"Mika", "Kenji", "Natsumi", "Ayaka", "Chiaki", "Akira", "Goro", "Ryo", "Satoshi"}
            for vid in ("natsumi", "ayaka", "chiaki", "akira", "goro", "ryo", "satoshi"):       # todas las nuevas suenan
                r = api.post("/api/voices/preview", json={"id": vid})
                assert r.status_code == 200 and len(r.content) > 20000, (vid, r.status_code)
            assert muestra.status_code == 200 and muestra.content[:4] == b"RIFF"
            # el motor de voz: completa o ligera, con la recomendada para esta PC marcada
            motor = await p.js("({botones: [...document.querySelectorAll('#ob-engine button')].map(b => b.querySelector('b').textContent + (b.classList.contains('on') ? ' [elegida]' : '')), nota: document.getElementById('ob-engine-note').textContent})")
            ligera = api.post("/api/voices/preview", json={"id": "kenji", "engine": "ligera"})
            await p.js("document.querySelector('#ob-engine [data-value=ligera]').click(); null")
            print(f"   motor de voz     : {motor} · muestra con la ligera: {ligera.status_code}, {len(ligera.content) // 1024} KB")
            assert len(motor["botones"]) == 2 and any("Recomendada" in b and "[elegida]" in b for b in motor["botones"]) and motor["nota"]
            assert ligera.status_code == 200 and ligera.content != muestra.content
            v = await paso(SIGUIENTE, 2.5)
            assert api.get("/api/config").json()["voice_engine"] == "ligera", "no se guardó la voz ligera"
            inicio = await p.js("({tarjeta: !document.getElementById('start').hidden, texto: document.getElementById('start-sub').textContent, "
                                "mic: !document.getElementById('mic-picker').hidden || !document.getElementById('mic-allow').hidden, camara: !!document.getElementById('cam-select')})")
            print(f"6. dispositivos     : bienvenida abierta={v['abierta']} · {inicio}")
            assert not v["abierta"] and inicio["tarjeta"] and inicio["mic"]

            cfg = api.get("/api/config").json()
            guardado = json.loads((_prueba.TEST_DIR / "settings.json").read_text(encoding="utf-8"))
            titulo = await p.js("document.getElementById('start-title').textContent")
            print(f"   nombre           : el personaje se llama {cfg['name']!r} (tarjeta de inicio: {titulo!r})")
            assert cfg["name"] == "Kenji" and titulo == "Kenji"
            print(f"7. guardado         : onboarded={cfg['onboarded']} · perfil={cfg['profile']} · voz={cfg['voice']} · nube={cfg['cloud']['name']} "
                  f"(clave oculta: {cfg['cloud']['key_hint'][:1]}····) · +18 posible en local={cfg['adult']}")
            assert cfg["onboarded"] and cfg["profile"] == {"name": "Ana", "birth_year": 2000, "gender": "mujer"} and cfg["voice"] == "Kenji"
            assert cfg["model_id"] == "chico" and guardado["voice"] == "kenji" and "key" not in json.dumps(cfg["cloud"]).replace("key_hint", "").replace("has_key", "")

            # al recargar no se repite, y desde Ajustes se cambia un paso suelto
            await p.cmd("Page.reload")
            await asyncio.sleep(4)
            v = await p.js(VER)
            assert not v["abierta"], "la bienvenida se repitió tras recargar"
            await p.js("document.getElementById('open-settings').click(); null")
            await asyncio.sleep(1)
            lineas = await p.js("['me-line', 'cloud-line', 'local-line', 'voice-line'].map(i => document.getElementById(i).textContent.replace(/…\\S+/, '…····'))")
            v = await paso("document.querySelector('[data-edit=perfil]').click()", 2)
            assert v["abierta"] and v["paso"] == "perfil" and await p.js("document.getElementById('ob-user').value") == "Ana"
            await p.js("document.getElementById('ob-user').value = 'Ana María'; null")
            v = await paso(SIGUIENTE, 2)
            nuevo = api.get("/api/config").json()["profile"]["name"]
            await paso("document.querySelector('[data-edit=voz]').click()", 2)      # la voz se cambia sola desde Ajustes
            await p.js("[...document.querySelectorAll('#ob-voices .model-row .pick')].find(b => b.querySelector('b').textContent === 'Satoshi').click(); null")
            await paso(SIGUIENTE, 2)
            voz = api.get("/api/config").json()
            print(f"8. tras recargar    : sin bienvenida · Ajustes muestra {lineas} · nombre cambiado → {nuevo!r} · voz cambiada → {voz['voice']!r}, personaje → {voz['name']!r}")
            assert voz["voice"] == "Satoshi" and voz["name"] == "Satoshi"
            assert not v["abierta"] and nuevo == "Ana María"

            # una persona menor de edad: los temas +18 quedan apagados también con el cerebro local
            api.post("/api/setup", json={"profile": {"name": "Leo", "birth_year": cfg_year() - 15, "gender": ""}, "provider": "local"})
            menor = api.get("/api/config").json()["adult"]
            api.post("/api/setup", json={"profile": {"name": "Ana", "birth_year": 1990, "gender": "mujer"}})
            adulta = api.get("/api/config").json()["adult"]
            api.post("/api/setup", json={"provider": "gemini"})
            nube = api.get("/api/config").json()["adult"]
            print(f"9. regla +18        : menor en local={menor} · adulta en local={adulta} · adulta en la nube={nube}")
            assert not menor["active"] and adulta["active"] and not nube["active"]

            # Ajustes › Empezar de nuevo: repetir la bienvenida conserva los datos; restablecer los borra
            await p.cmd("Page.reload")
            await asyncio.sleep(4)
            await p.js("document.getElementById('open-settings').click(); null")
            v = await paso("document.getElementById('redo-onboarding').click()", 5)
            conserva = await p.js("document.getElementById('ob-user').value")
            assert v["abierta"] and v["paso"] == "perfil" and conserva == "Ana", (v, conserva)
            api.post("/api/setup", json={"onboarded": True})
            store_antes = len(api.get("/api/memory").json()["facts"])
            await p.js("window.confirm = () => true; document.getElementById('reset-all').click(); null")
            await asyncio.sleep(5)
            v = await p.js(VER)
            vacio = api.get("/api/config").json()
            campo = await p.js("document.getElementById('ob-user').value")
            archivo = (_prueba.TEST_DIR / "settings.json").exists()
            print(f"10. empezar de nuevo: repetir → paso «perfil» con nombre {conserva!r} · restablecer → bienvenida abierta={v['abierta']}, "
                  f"perfil={vacio['profile']}, personaje={vacio['name']!r}, modelo={vacio['model_id']!r}, settings.json existe={archivo} (recuerdos antes: {store_antes})")
            assert v["abierta"] and v["paso"] == "perfil" and not vacio["onboarded"] and not vacio["profile"]["name"]
            assert vacio["name"] == "Mika" and vacio["model_id"] == "default" and campo in ("", vacio["user"])
        print("OK: la bienvenida guarda perfil, cerebro, voz y modelo; no se repite y se edita desde Ajustes.")
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


def cfg_year() -> int:
    import time
    return time.localtime().tm_year


if __name__ == "__main__":
    with _prueba.Servidor(nuevo=True):
        asyncio.run(main())
