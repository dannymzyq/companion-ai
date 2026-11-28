"""Actualizar en un clic (27 nov 2026): solo se baja y se abre un instalador que se pudo comprobar con SHA-256.

Antes, si la versión no traía `SHA256SUMS.txt`, el instalador se bajaba y se abría igual, sin comprobar.
"""
import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from tests import TMP
from companion import update

NAME = "Companion-Setup-9.9.9.exe"
BASE = update.DL_PREFIX + "v9.9.9/"
INSTALLER = b"MZ instalador de prueba"


class Descarga(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=TMP))                     # cada prueba, su carpeta
        self.requests: list[str] = []
        self.sums: str | None = f"{hashlib.sha256(INSTALLER).hexdigest()}  {NAME}\n"
        for p in (mock.patch.object(update.tempfile, "gettempdir", return_value=str(self.dir)),
                  mock.patch.object(update, "check", mock.AsyncMock(side_effect=self.info))):
            p.start()
            self.addCleanup(p.stop)
        real = httpx.AsyncClient

        def client(**kw):
            kw["transport"] = httpx.MockTransport(self.serve)
            return real(**kw)

        p = mock.patch.object(update.httpx, "AsyncClient", side_effect=client)
        p.start()
        self.addCleanup(p.stop)

    async def info(self):
        return {"newer": True, "asset_url": BASE + NAME, "asset_name": NAME,
                "sums_url": BASE + "SHA256SUMS.txt" if self.sums is not None else None}

    def serve(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("SHA256SUMS.txt"):
            return httpx.Response(200, text=self.sums or "")
        return httpx.Response(200, content=INSTALLER)

    def installer(self) -> Path:
        return self.dir / "companion_update" / NAME

    def test_comprobado_se_descarga(self):
        out = asyncio.run(update.download_and_verify(launch=True))        # en las pruebas no se abre (DRY)
        self.assertTrue(out["verified"])
        self.assertEqual(self.installer().read_bytes(), INSTALLER)

    def test_sin_huella_no_se_descarga_ni_se_abre(self):
        self.sums = None
        with self.assertRaises(ValueError):
            asyncio.run(update.download_and_verify(launch=True))
        self.assertNotIn(NAME, self.requests)
        self.assertFalse(self.installer().exists())

    def test_huella_sin_ese_instalador_tampoco(self):
        self.sums = f"{'0' * 64}  Companion-0.0.0-mac.dmg\n"
        with self.assertRaises(ValueError):
            asyncio.run(update.download_and_verify(launch=True))
        self.assertNotIn(NAME, self.requests)

    def test_huella_distinta_se_borra(self):
        self.sums = f"{'0' * 64}  {NAME}\n"
        with self.assertRaises(ValueError):
            asyncio.run(update.download_and_verify(launch=True))
        self.assertFalse(self.installer().exists())
        self.assertFalse(self.installer().with_suffix(".exe.part").exists())


if __name__ == "__main__":
    unittest.main()
