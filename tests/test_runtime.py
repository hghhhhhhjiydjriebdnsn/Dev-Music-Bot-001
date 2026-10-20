"""Offline regression checks: never log in or send a Telegram request."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def execute(code):
    env = dict(os.environ, API_ID="12345", API_HASH="0" * 32,
               SESSION="offline-test-placeholder", BOT_TOKEN="", SPOTIFY_CLIENT_ID="",
               SPOTIFY_CLIENT_SECRET="")
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


class SourceRegressionTests(unittest.TestCase):
    def test_original_command_handlers_preserved(self):
        tree = ast.parse((ROOT / "main.py").read_text())
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        expected = {"repo", "ping", "play_stream", "live_stream", "skip_track",
                    "mute_vc", "unmute_vc", "pause_vc", "resume_vc", "leave_vc", "queue_list",
                    "shuffle_list", "loop_stream", "switch_mode", "admins_only", "set_lang",
                    "export_queue", "import_queue", "import_playlist", "update_restart",
                    "stream_end", "closed_vc"}
        self.assertTrue(expected <= names, expected - names)
        ui = ast.parse((ROOT / "core/ui.py").read_text())
        ui_names = {n.name for n in ast.walk(ui) if isinstance(n, ast.AsyncFunctionDef)}
        self.assertTrue({"start_ui", "help_ui"} <= ui_names)

    def test_every_retained_translation_is_valid_json(self):
        paths = list((ROOT / "lang").glob("*.json"))
        self.assertGreaterEqual(len(paths), 13)
        for path in paths:
            with self.subTest(locale=path.name):
                self.assertIn("playing", json.loads(path.read_text()))

    def test_no_hidden_sudo_or_forced_channel_join(self):
        tree = ast.parse((ROOT / "core/decorators.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotEqual(node.func.attr, "join_chat")
                if node.func.attr == "append" and node.args and isinstance(node.args[0], ast.Constant):
                    self.assertNotIsInstance(node.args[0].value, int)

    def test_startup_runs_local_source(self):
        text = (ROOT / "startup.sh").read_text()
        self.assertNotIn("git clone", text)
        self.assertIn("main.py", text)
        self.assertNotIn("COPY .env", (ROOT / "Dockerfile").read_text())

    def test_environment_boolean_is_parsed(self):
        result = execute("from config import Config; import os; os.environ['ADMINS_ONLY']='false'; assert Config().ADMINS_ONLY is False; os.environ['ADMINS_ONLY']='true'; assert Config().ADMINS_ONLY is True")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validation_names_missing_values(self):
        result = execute("from config import Config; c=Config(); c.SESSION=''; c.validate()")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SESSION", result.stderr)
        self.assertNotIn("offline-test-placeholder", result.stderr)


@unittest.skipUnless(importlib.util.find_spec("pyrogram") and importlib.util.find_spec("pytgcalls"),
                     "Install requirements.txt for offline runtime checks")
class RuntimeTests(unittest.TestCase):
    def test_core_and_voicechat_dependencies_import(self):
        result = execute("import core; assert core.pytgcalls is not None; from ogmusic.providers import service, Track, download_audio")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_song_dict_ignores_method_override(self):
        result = execute("from core.song import Song; from types import SimpleNamespace; s=Song({'source':'x','remote':'file','parse':'bad'},SimpleNamespace(from_user=None)); assert callable(s.parse); assert s.parsed")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cover_works_without_remote_thumbnail(self):
        result = execute("import asyncio,pathlib; from core.funcs import generate_cover; from PIL import Image; p=pathlib.Path(asyncio.run(generate_cover('Test Track','OG Group',-1,None))); assert Image.open(p).size == (1280,720); p.unlink()")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_groups_and_queue_still_work(self):
        result = execute("import asyncio; from core.groups import get_group,get_queue,set_group,clear_queue; g=get_group(-1); q=get_queue(-1); q.put_nowait('a'); q.put_nowait('b'); assert len(q)==2; assert q.get_nowait()=='a'; set_group(-1,loop=True); assert g['loop']; clear_queue(-1); assert len(q)==0")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
