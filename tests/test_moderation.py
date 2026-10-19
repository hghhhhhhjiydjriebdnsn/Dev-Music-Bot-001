"""Offline tests for moderation primitives; none create a Telegram session."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def run_python(code, data_dir):
    env = dict(os.environ, API_ID="12345", API_HASH="0" * 32,
               SESSION="offline-test-placeholder", BOT_TOKEN="",
               DATA_DIR=str(data_dir), FORCE_CHANNEL="")
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


class ModerationOfflineTests(unittest.TestCase):
    def test_settings_are_sqlite_persistent_and_group_toggles_reflect(self):
        with tempfile.TemporaryDirectory() as directory:
            first = run_python("""
from core.moderation import get_settings, update_settings
from core.groups import get_group
assert get_settings(-100123)['welcome_enabled'] is False
update_settings(-100123, admins_only=True, loop=True, welcome_enabled=True, welcome_text='Hi {name}')
g = get_group(-100123)
assert g['admins_only'] is True and g['loop'] is True
""", directory)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_python("""
from core.moderation import get_settings
s = get_settings(-100123)
assert s == {'admins_only': True, 'loop': True, 'welcome_enabled': True, 'welcome_text': 'Hi {name}'}, s
""", directory)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue((Path(directory) / "moderation.sqlite3").exists())

    def test_membership_gate_denies_left_and_api_errors_but_allows_active(self):
        code = """
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
import core.moderation as m
async def run():
    m.os.environ['FORCE_CHANNEL'] = '@public'
    client=N(get_chat_member=AsyncMock(return_value=N(status='left')))
    assert await m._force_member(client, 45) is False
    client.get_chat_member.return_value=N(status='member')
    assert await m._force_member(client, 45) is True
    client.get_chat_member.return_value=N(status='restricted', is_member=False)
    assert await m._force_member(client, 45) is False
    client.get_chat_member.return_value=N(status='restricted', is_member=True)
    assert await m._force_member(client, 45) is True
    client.get_chat_member.return_value=N(status='unknown')
    assert await m._force_member(client, 45) is False
    client.get_chat_member.side_effect=RuntimeError('no access')
    assert await m._force_member(client, 45) is False
    m.os.environ['FORCE_CHANNEL']=''
    assert await m._force_member(client, 45) is True
asyncio.run(run())
"""
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(code, directory)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_target_resolution_and_callback_expiration(self):
        code = """
from types import SimpleNamespace as N
import core.moderation as m
u=N(id=77, first_name='Member')
msg=N(reply_to_message=N(from_user=u))
assert m._target_from(msg, '') == (77, 'Member')
assert m._target_from(N(reply_to_message=None), ' 12345 ') == (12345, '12345')
assert m._target_from(N(reply_to_message=None), '@user') == (None, None)
t=m._token({'chat':-10, 'requester':5, 'target':77})
assert m._PENDING[t]['target']==77 and m._PENDING[t]['expires'] > 0
"""
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(code, directory)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_registration_prioritizes_gates_and_callbacks_are_registered(self):
        code = """
from core.moderation import register_moderation
class Client:
    def __init__(self): self.handlers=[]
    def add_handler(self, handler, group=0): self.handlers.append((group, handler))
c=Client()
assert register_moderation(c)
assert min(group for group, _ in c.handlers) == -20
assert any(group == -10 for group, _ in c.handlers)
assert len(c.handlers) >= 10
"""
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(code, directory)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unban_call_matches_installed_pyrogram_signature(self):
        code = """
import inspect
from pyrogram import Client
params = inspect.signature(Client.unban_chat_member).parameters
assert 'chat_id' in params and 'user_id' in params
assert 'only_if_banned' not in params
"""
        with tempfile.TemporaryDirectory() as directory:
            result = run_python(code, directory)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
