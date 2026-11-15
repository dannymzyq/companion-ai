"""La voz espera al servidor de voz si está cargando, los temporizadores sobreviven a una reconexión y el bucle
del control de ventanas (control_task) termina bien. Todo con piezas simuladas: nada suena ni se toca."""
import asyncio
import types
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (fija el entorno de prueba)

from companion import actions, control, control_task, llm, session, tts, tts_light, voz_proc
from companion.config import settings


class VozCargando(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine, settings.voice_engine = settings.voice_engine, "completa"

    async def asyncTearDown(self):
        settings.voice_engine = self.engine

    async def test_espera_y_repite(self):
        calls = []

        async def full(body):
            calls.append(body["input"])
            if len(calls) == 1:
                raise tts._NotReady("el servidor de voz respondió 503: La voz todavía está cargando")
            yield b"\x01\x00" * 10

        with mock.patch.object(tts, "_full", full), mock.patch.object(voz_proc, "recover", mock.AsyncMock(return_value=True)) as rec:
            pcm = b"".join([c async for c in tts.stream_speech("Hola de nuevo, Ana.", "mika_es")])
        self.assertEqual(len(calls), 2)
        rec.assert_awaited_once()
        self.assertEqual(len(pcm), 20)

    async def test_si_no_carga_sigue_en_texto(self):
        async def full(body):
            raise tts._NotReady("no hay conexión con el servidor de voz")
            yield b""                                   # noqa: unreachable (es un generador)

        with mock.patch.object(tts, "_full", full), mock.patch.object(voz_proc, "recover", mock.AsyncMock(return_value=False)),                 mock.patch.object(tts_light, "installed", return_value=False):
            with self.assertRaises(tts.TTSError):
                _ = [c async for c in tts.stream_speech("Hola.", "mika_es")]

    async def test_si_no_carga_suena_la_ligera(self):
        # PyTorch sin la tarjeta (driver antiguo): el servidor de voz da error y la frase va con Piper.
        async def full(body):
            raise tts._NotReady("no hay conexión con el servidor de voz")
            yield b""                                   # noqa: unreachable (es un generador)

        async def ligera(text, voice, speed=1.0):
            yield b"\x02\x00" * 4

        with mock.patch.object(tts, "_full", full), mock.patch.object(voz_proc, "recover", mock.AsyncMock(return_value=False)),                 mock.patch.object(tts_light, "installed", return_value=True), mock.patch.object(tts_light, "stream_speech", ligera):
            pcm = b"".join([c async for c in tts.stream_speech("Hola de nuevo, Ana.", "mika_es")])
        self.assertEqual(pcm, b"\x02\x00" * 4)

    async def test_relanza_si_se_cayo(self):
        muerto = types.SimpleNamespace(poll=lambda: 1, returncode=1)
        with mock.patch.object(voz_proc, "_proc", muerto), mock.patch.object(voz_proc, "installed", return_value=True), \
                mock.patch.object(voz_proc, "start") as start:
            voz_proc.ensure()
        start.assert_called_once()


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)

    async def send_bytes(self, data):
        pass


class Temporizadores(unittest.IsolatedAsyncioTestCase):
    async def test_avisa_en_la_conexion_nueva(self):
        req = actions.prepare("temporizador", ["1 segundo", "té"])
        req.target["seconds"] = 0.05
        a = session.Session(FakeWS(), {"name": "Mika", "voice": {}}, transcriber=None)
        a.start()
        session._start_timer(req)
        await a.close()                                 # la ventana se recarga mientras corre
        await asyncio.sleep(0.15)
        self.assertEqual(len(session._missed), 1)       # acabó sin ninguna conexión: queda guardado
        b = session.Session(FakeWS(), {"name": "Mika", "voice": {}}, transcriber=None)
        with mock.patch.object(session.Session, "_later") as later:
            b.start()
            await asyncio.sleep(1.7)
        self.assertEqual(session._missed, [])
        self.assertTrue(any("temporizador" in m and "té" in m for m in b.ws.sent))
        later.assert_called_once()
        await b.close()


class BucleDeControl(unittest.IsolatedAsyncioTestCase):
    async def test_termina_y_cuenta_el_resultado(self):
        win = types.SimpleNamespace(hwnd=123, title="Reproductor de prueba")
        req = actions.Request("controlar", ["Reproductor", "pon la canción"], "Usar una aplicación por ti",
                              "Usar «Reproductor de prueba» para: pon la canción", {"window": win, "task": "pon la canción"})
        sent, later = [], []
        sess = types.SimpleNamespace(controlling=None, control_stop=False, closed=False, _sharing_screen=lambda: False,
                                     _later=later.append, _confirm=mock.AsyncMock(return_value=False))

        async def send_json(data):
            sent.append(data)
        sess.send_json = send_json

        class Esc:
            pressed, sending = False, False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        replies = iter(["pulsar 1", "listo | ya suena"])

        async def stream_chat(messages, sampling, images=None, background=False):
            self.assertTrue(background)                 # cada paso va al modelo de fondo (no gasta la cuota de la charla)
            yield next(replies)

        item = control.Item(n=1, kind="botón", name="Reproducir")
        press = mock.Mock(return_value="accesibilidad")
        with mock.patch.multiple(control, EscWatch=Esc, user32=types.SimpleNamespace(IsWindow=lambda h: True),
                                 snapshot=lambda h: ([item], ["Reproducir"]), release=lambda h: None, press=press), \
                mock.patch.object(llm, "stream_chat", stream_chat), mock.patch.object(actions, "log_entry"), \
                mock.patch.object(control_task.asyncio, "sleep", mock.AsyncMock()):
            await control_task.run(sess, req)
        press.assert_called_once()
        end = next(d for d in sent if d["type"] == "control_end")
        self.assertTrue(end["ok"])
        self.assertEqual(end["text"], "ya suena")
        self.assertIsNone(sess.controlling)
        self.assertIn("se completó", later[0])
        sess._confirm.assert_not_awaited()              # «Reproducir» no es delicado


if __name__ == "__main__":
    unittest.main()
