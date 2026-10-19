"""MAHI MUSIC custom emoji helpers, with ordinary-emoji retry fallback.

The user-supplied catalog is data, never executable input. Pyrogram's HTML
parser uses <emoji id="...">; Bot API button icons use the same document IDs.
"""
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

PREMIUM_EMOJI = json.loads(Path(__file__).with_name("premium_emoji.json").read_text())
_PATTERN = re.compile("|".join(re.escape(key) for key in sorted(PREMIUM_EMOJI, key=len, reverse=True)))
_custom_supported = True


def enabled():
    return os.getenv("PREMIUM_EMOJIS", "true").lower() in {"1", "true", "yes", "on"}


def button_icon(text):
    """Pick the matching leading emoji, without changing callback data."""
    override = os.getenv("CUSTOM_EMOJI_ID", "").strip()
    if override.isdigit():
        return override
    if not enabled() or not _custom_supported:
        return None
    match = _PATTERN.match(str(text).lstrip())
    return PREMIUM_EMOJI[match.group()] if match else None


class _EmojiHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.skip = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())
        if tag in {"code", "pre", "emoji", "tg-emoji"}:
            self.skip.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")
        if self.skip and self.skip[-1] == tag:
            self.skip.pop()

    def handle_data(self, data):
        if not self.skip:
            data = _PATTERN.sub(lambda m: f'<emoji id="{PREMIUM_EMOJI[m.group()]}">{m.group()}</emoji>', data)
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")


def decorate_html(text):
    """Do not touch URLs, attributes, code blocks, or existing emoji entities."""
    if not enabled() or not _custom_supported:
        return str(text)
    parser = _EmojiHTML()
    parser.feed(str(text))
    parser.close()
    return "".join(parser.parts)


async def _send(method, text, *, field=None, **kwargs):
    global _custom_supported
    from pyrogram import enums
    from pyrogram.errors import BadRequest
    mode = kwargs.get("parse_mode")
    # Legacy Markdown messages remain untouched; native HTML UI uses the catalog.
    original = str(text or "")
    rich = decorate_html(original) if mode == enums.ParseMode.HTML else original
    async def invoke(content):
        if field:
            return await method(**{field: content}, **kwargs)
        return await method(content, **kwargs)
    try:
        return await invoke(rich)
    except BadRequest as exc:
        kind = (type(exc).__name__ + " " + str(getattr(exc, "ID", ""))).upper()
        if rich != original and any(marker in kind for marker in ("EMOJI", "PREMIUM", "ENTIT", "DOCUMENT")):
            _custom_supported = False
            return await invoke(original)
        raise


async def send_text(message, text, **kwargs):
    from config import config
    if not config.BOT_TOKEN:
        kwargs.pop("reply_markup", None)
    return await _send(message.reply_text, text, **kwargs)


async def edit_text(message, text, **kwargs):
    return await _send(message.edit_text, text, **kwargs)


async def send_photo(message, *, photo, caption="", **kwargs):
    from config import config
    if not config.BOT_TOKEN:
        kwargs.pop("reply_markup", None)
    return await _send(message.reply_photo, caption, field="caption", photo=photo, **kwargs)


async def send_audio(message, audio, *, caption="", **kwargs):
    return await _send(message.reply_audio, caption, field="caption", audio=audio, **kwargs)
