"""Mocked admin flows: no Telegram login or real member action is performed."""
import importlib.util
import unittest
from test_runtime import execute


@unittest.skipUnless(importlib.util.find_spec("pyrogram"), "Install requirements.txt")
class AdminSafetyTests(unittest.TestCase):
    def check(self, code):
        result = execute(code)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_confirmation_is_requester_bound_and_consumed_once(self):
        self.check('''
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from config import config
import core.moderation as m
class Client:
    def __init__(self):
        self.handlers={};self.get_me=AsyncMock(return_value=N(id=99));self.ban_chat_member=AsyncMock()
    def add_handler(self,h,group=0): self.handlers[h.callback.__name__]=h.callback
    async def get_chat_member(self,chat,user):
        return N(status='administrator',privileges=N(can_restrict_members=True)) if user in (42,99) else N(status='member')
async def run():
    config.BOT_TOKEN='offline'; config.SUDOERS=[]
    c=Client();m.register_moderation(c)
    token=m._token({'chat':-1,'requester':42,'target':77,'action':'ban'})
    msg=N(chat=N(id=-1),reply_text=AsyncMock())
    q=N(data='ogm:c:'+token,from_user=N(id=55),message=msg,answer=AsyncMock())
    cb=c.handlers['moderation_callback']
    await cb(c,q)
    assert token in m._PENDING and c.ban_chat_member.await_count==0
    q.from_user=N(id=42)
    await cb(c,q)
    c.ban_chat_member.assert_awaited_once_with(-1,77)
    assert token not in m._PENDING
    await cb(c,q)
    assert c.ban_chat_member.await_count==1
asyncio.run(run())
''')

    def test_panel_cannot_change_another_chats_settings(self):
        self.check('''
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
import core.moderation as m
class Client:
    def __init__(self): self.handlers={};self.get_chat_member=AsyncMock(return_value=N(status='administrator'))
    def add_handler(self,h,group=0): self.handlers[h.callback.__name__]=h.callback
async def run():
    c=Client();m.register_moderation(c)
    q=N(data='ogm:t:welcome_enabled:-2',from_user=N(id=42),message=N(chat=N(id=-1)),answer=AsyncMock())
    with patch.object(m,'update_settings') as update:
        await c.handlers['moderation_callback'](c,q)
        update.assert_not_called()
asyncio.run(run())
''')

    def test_force_gate_applies_in_private_but_does_not_block_stop(self):
        self.check('''
import asyncio,os
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from pyrogram import StopPropagation
import core.moderation as m
class Client:
    def __init__(self): self.handlers={};self.get_chat_member=AsyncMock(return_value=N(status='left'))
    def add_handler(self,h,group=0): self.handlers[h.callback.__name__]=h.callback
async def run():
    os.environ['FORCE_CHANNEL']='@yourchannel'
    c=Client();m.register_moderation(c)
    msg=N(chat=N(id=42,type='private'),from_user=N(id=42),text='/download title',command=['download','title'],reply_text=AsyncMock())
    try: await c.handlers['force_gate'](c,msg)
    except StopPropagation: pass
    else: raise AssertionError('Private download gate was bypassed')
    stop=N(data='ogc:x:-1',from_user=N(id=42),message=N(chat=N(id=-1,type='supergroup')),answer=AsyncMock())
    await c.handlers['force_callback'](c,stop)
    stop.answer.assert_not_awaited()
    stop.data='ogc:d:-1'
    try: await c.handlers['force_callback'](c,stop)
    except StopPropagation: pass
    else: raise AssertionError('Current download gate was bypassed')
asyncio.run(run())
''')


if __name__ == '__main__':
    unittest.main()
