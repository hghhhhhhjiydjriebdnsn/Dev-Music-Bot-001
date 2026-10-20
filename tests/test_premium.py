"""Premium emoji rendering without Telegram network calls."""
import importlib.util
import unittest
from test_runtime import execute


@unittest.skipUnless(importlib.util.find_spec("pyrogram"), "Install requirements.txt")
class PremiumTests(unittest.TestCase):
    def check(self, code):
        result = execute(code)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_catalog_and_safe_html_conversion(self):
        self.check('''
import os
os.environ['PREMIUM_EMOJIS']='true'
from core.premium import PREMIUM_EMOJI,decorate_html
assert len(PREMIUM_EMOJI)==363
assert PREMIUM_EMOJI['🎵']=='5891249688933305846'
assert PREMIUM_EMOJI['😭']=='5890794491119407059'
assert '??' not in PREMIUM_EMOJI
original='<b>🎵 PIHU MUSIC</b> <code>🎵</code> <a href="https://example.com/🎵">Music</a> &amp; ??'
rich=decorate_html(original)
assert '<emoji id="5891249688933305846">🎵</emoji>' in rich
assert '<code>🎵</code>' in rich
assert 'href="https://example.com/🎵"' in rich
assert '&amp; ??' in rich
assert decorate_html(rich)==rich
''')

    def test_native_parser_creates_custom_emoji_entities(self):
        self.check('''
import asyncio,os
os.environ['PREMIUM_EMOJIS']='true'
from pyrogram import enums
from pyrogram.parser import Parser
from core.premium import decorate_html
async def run():
    parsed=await Parser(None).parse(decorate_html('🎵 <b>PIHU MUSIC</b>'),enums.ParseMode.HTML)
    assert parsed['message']=='🎵 PIHU MUSIC'
    assert any(type(e).__name__=='MessageEntityCustomEmoji' for e in parsed['entities'])
asyncio.run(run())
''')

    def test_premium_rejection_retries_with_ordinary_emoji(self):
        self.check('''
import asyncio,os
os.environ['PREMIUM_EMOJIS']='true'
from unittest.mock import AsyncMock
from pyrogram import enums
from pyrogram.errors import PremiumAccountRequired
from core.premium import _send
async def run():
    method=AsyncMock(side_effect=[PremiumAccountRequired(), 'sent'])
    result=await _send(method,'🎵 PIHU MUSIC',parse_mode=enums.ParseMode.HTML)
    assert result=='sent' and method.await_count==2
    assert '<emoji' in method.call_args_list[0].args[0]
    assert method.call_args_list[1].args[0]=='🎵 PIHU MUSIC'
asyncio.run(run())
''')

    def test_toggle_and_per_button_mapping(self):
        self.check('''
import os
from core.premium import decorate_html,button_icon
os.environ['CUSTOM_EMOJI_ID']=''
os.environ['PREMIUM_EMOJIS']='true'
assert button_icon('⬇️ Download')=='5386367538735104399'
os.environ['PREMIUM_EMOJIS']='false'
assert decorate_html('🎵')=='🎵' and button_icon('⬇️ Download') is None
''')


if __name__ == '__main__':
    unittest.main()
