import asyncio
import ctypes.wintypes as wt
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from companion import actions, control, focus, gemini_live, prompt, realtime, server, session, state


class FakeWS:
    def __init__(self):
        self.sent_json = []
        self.sent_bytes = []

    async def send_text(self, text: str):
        import json
        self.sent_json.append(json.loads(text))

    async def send_bytes(self, data: bytes):
        self.sent_bytes.append(data)


class FakePersona:
    DATA = {
        "name": "Mika",
        "age": 22,
        "speaks": "f",
        "traits": {},
        "speech_style": {},
        "adult": {"enabled": False},
        "voice": {},
        "personality": {"name": "cercana", "base_mood": "neutral"},
    }


class TestUXFixes(unittest.IsolatedAsyncioTestCase):
    async def test_live_interrupt_discards_audio_and_cancels_realtime(self):
        ws = FakeWS()
        s = session.Session(ws, FakePersona.DATA, transcriber=mock.MagicMock())
        s._is_live = lambda: True

        cancelled = False

        class FakeClient:
            connected = True

            async def cancel_response(self):
                nonlocal cancelled
                cancelled = True

            async def receive(self):
                yield ("audio", b"\x01\x02" * 100)
                yield ("turn_complete", None)

            async def close(self):
                pass

        client = FakeClient()
        s.live = client
        s._live_turn_open = True
        s.client_playing = True

        await s.on_message({"type": "interrupt"})
        self.assertTrue(s._live_discard_audio)
        self.assertTrue(cancelled)
        self.assertFalse(s._live_turn_open)
        self.assertFalse(s.client_playing)

        # Now run _live_loop: the remaining audio packet must be discarded, and flag cleared on turn_complete
        await s._live_loop(client)
        self.assertEqual(ws.sent_bytes, [])
        self.assertFalse(s._live_discard_audio)
        self.assertEqual(s.state, "idle")

    async def test_later_lock_serializes_and_waits_for_live_turn(self):
        ws = FakeWS()
        s = session.Session(ws, FakePersona.DATA, transcriber=mock.MagicMock())
        s._is_live = lambda: True
        s._live_turn_open = True
        order = []

        async def fake_send_text(text, *, show_user):
            order.append(f"start:{text}")
            await asyncio.sleep(0.05)
            order.append(f"end:{text}")

        s._live_send_text = fake_send_text
        s._later("primero")
        s._later("segundo")
        await asyncio.sleep(0.05)
        self.assertEqual(order, [])  # still waiting because _live_turn_open is True

        s._live_turn_open = False
        await asyncio.sleep(0.5)
        self.assertEqual(order, ["start:primero", "end:primero", "start:segundo", "end:segundo"])

    def test_state_load_cache_and_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            sf = Path(td) / "settings.json"
            bf = Path(td) / "settings.json.bak"
            with mock.patch.object(state, "STATE_FILE", sf), mock.patch.object(state, "BACKUP_FILE", bf):
                state._cache = None
                state._cache_key = None
                state.save(foo="bar")
                with mock.patch.object(state, "_read", wraps=state._read) as m_read:
                    d1 = state.load()
                    d2 = state.load()
                    self.assertEqual(d1["foo"], "bar")
                    self.assertEqual(d2["foo"], "bar")
                    self.assertEqual(m_read.call_count, 1)
                state.save(foo="baz")
                self.assertEqual(state.load()["foo"], "baz")
                state.clear()
                self.assertEqual(state.load(), {})

    def test_ptt_capslock_uses_0x8000(self):
        src = inspect.getsource(session.Session._ptt_loop)
        self.assertIn("0x8000", src)
        self.assertNotIn("0x0001", src)

    def test_actions_guess_prefixes_negations_pomodoro_and_stopwords(self):
        # Chained prefixes + character name
        g = actions.guess("Oye Kenji por favor puedes poner un temporizador de 5 minutos")
        self.assertIsNotNone(g)
        self.assertEqual(g[0], "temporizador")

        # Stop pomodoro
        self.assertEqual(actions.guess("para el pomodoro"), ("enfoque", ["parar"]))
        self.assertEqual(actions.guess("detén el modo enfoque"), ("enfoque", ["parar"]))

        # Timer negations
        self.assertIsNone(actions.guess("no pongas un temporizador de 5 minutos"))
        self.assertIsNone(actions.guess("sin temporizador de 5 minutos"))

        # Conversational false positives for controlar
        self.assertIsNone(actions.guess("busca algo en internet"))
        self.assertIsNone(actions.guess("escribe una funcion en python"))

    def test_server_exit_gemini_live_preserves_explicit_provider(self):
        # Simulate exiting gemini_live while explicitly choosing provider='local'
        saved_state = {
            "gemini_live": True,
            "provider": "gemini",
            "before_gemini_live": {
                "provider": "gemini",
                "ear": "local",
                "voice_engine": "ligera",
                "cloud_only": False,
            },
        }
        with mock.patch.object(state, "load", return_value=saved_state):
            changes = {}
            changes.update(server._gemini_live_changes(False, changes))
            changes["provider"] = "local"
            self.assertEqual(changes["gemini_live"], False)
            self.assertEqual(changes["provider"], "local")
            self.assertEqual(changes["voice_engine"], "ligera")

    def test_control_gettickcount_restype_dword(self):
        if os.name == "nt":
            self.assertEqual(control.kernel32.GetTickCount.restype, wt.DWORD)
        src = inspect.getsource(control.user_idle_ms)
        self.assertIn("0xFFFFFFFF", src)

    def test_focus_prompt_has_no_raw_tags(self):
        src = inspect.getsource(focus._loop)
        self.assertNotIn("[emo:", src)
        self.assertNotIn("[gesto:", src)

    def test_mcp_action_wired(self):
        self.assertIn("mcp", actions.CATALOG)
        self.assertIn("mcp", gemini_live.ACTION_TOOLS[0]["parameters"]["properties"]["accion"]["enum"])
        blk = prompt.actions_block("Danny", mcp_tools=[{"server_id": "mcp_1", "name": "ping", "description": "test"}])
        self.assertIn("[accion: mcp", blk)
        self.assertIn("mcp_1:ping", blk)
        with mock.patch("companion.mcp_client.config", return_value={
            "enabled": True,
            "servers": [{"id": "mcp_1", "name": "Local", "url": "http://127.0.0.1:9000", "read_only": True}],
        }):
            req = actions.prepare("mcp", ["mcp_1:ping", '{"x": 1}'])
            self.assertEqual(req.name, "mcp")
            self.assertEqual(req.target["server_id"], "mcp_1")
            self.assertEqual(req.target["tool"], "ping")
            self.assertEqual(req.target["arguments"], {"x": 1})


if __name__ == "__main__":
    unittest.main()
