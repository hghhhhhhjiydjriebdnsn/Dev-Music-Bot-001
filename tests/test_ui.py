"""Mocked Telegram UI tests. All network-facing methods are replaced."""
import importlib.util
import unittest
from test_runtime import execute


@unittest.skipUnless(importlib.util.find_spec("pyrogram") and importlib.util.find_spec("pytgcalls"),
                     "Install requirements.txt for UI checks")
class UITests(unittest.TestCase):
    def check(self, code):
        result = execute(code)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_home_ui_uses_valid_html_mode_and_userbot_fallback(self):
        self.check('''
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from pyrogram import enums
from pyrogram.parser import Parser
import core.ui as ui
class Client:
    def __init__(self): self.handlers={}
    def on_message(self,*a,**k):
        def dec(fn): self.handlers[fn.__name__]=fn; return fn
        return dec
    on_callback_query=on_message
async def run():
    client=Client(); ui.register_ui(client)
    sent=N(chat=N(id=1),id=1,reply_markup=None)
    message=N(from_user=N(id=42,first_name='<OG>'),reply_text=AsyncMock(return_value=sent))
    await client.handlers['start_ui'](None,message)
    args,kwargs=message.reply_text.call_args
    assert kwargs['parse_mode'] == enums.ParseMode.HTML
    assert 'reply_markup' not in kwargs
    parsed=await Parser(None).parse(args[0],kwargs['parse_mode'])
    assert '<OG>' in parsed['message'] and '<b>' not in parsed['message']
asyncio.run(run())
''')

    def test_callback_admin_check_uses_actual_clicker(self):
        self.check('''
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
from core.ui import _is_admin_click
from config import config
async def run():
    config.SUDOERS=[]
    getter=AsyncMock(return_value=N(status='member'))
    query=N(from_user=N(id=42),message=N(from_user=N(id=99),chat=N(get_member=getter)))
    assert not await _is_admin_click(query)
    getter.assert_awaited_once_with(42)
    getter.return_value=N(status='administrator')
    assert await _is_admin_click(query)
asyncio.run(run())
''')

    def test_search_tokens_are_bounded_and_bound_to_requester(self):
        self.check('''
from core.ui import _cache_track,_search_tokens,_TOKEN_LIMIT
_search_tokens.clear()
token=_cache_track(42,-1,object())
assert _search_tokens[token]['user']==42 and _search_tokens[token]['chat']==-1
for i in range(_TOKEN_LIMIT+3): _cache_track(i,-1,object())
assert len(_search_tokens)==_TOKEN_LIMIT and token not in _search_tokens
''')

    def test_unauthorized_callback_does_not_enqueue_or_destroy_result(self):
        self.check('''
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
import core.ui as ui
class Client:
    def __init__(self): self.handlers={}
    def on_message(self,*a,**k):
        def dec(fn): self.handlers[fn.__name__]=fn; return fn
        return dec
    on_callback_query=on_message
async def run():
    client=Client(); ui.register_ui(client)
    token=ui._cache_track(42,-1,object())
    query=N(data='ogs:p:'+token,from_user=N(id=77),answer=AsyncMock(),message=N(chat=N(id=-1),reply_text=AsyncMock()))
    await client.handlers['search_callback'](None,query)
    assert token in ui._search_tokens
    assert not ui._search_tokens[token]['played']
    query.answer.assert_awaited_once()
asyncio.run(run())
''')

    def test_initial_playback_failure_resets_group_state(self):
        self.check('''
import asyncio
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
import core.stream as stream
from core.groups import get_group,set_group
async def run():
    chat=N(id=-1,title='Test')
    song=N(request_msg=N(chat=chat,reply_text=AsyncMock(return_value=N(delete=AsyncMock()))),remote='file',headers=None)
    get_group(-1);set_group(-1,is_playing=True,now_playing=song)
    with patch.object(stream.pytgcalls,'play',AsyncMock(side_effect=RuntimeError('offline'))):
        try: await stream.start_stream(song,{'downloading':'Preparing'})
        except RuntimeError: pass
        else: raise AssertionError('Failure should propagate')
    assert not get_group(-1)['is_playing'] and get_group(-1)['now_playing'] is None
asyncio.run(run())
''')


if __name__ == '__main__':
    unittest.main()
