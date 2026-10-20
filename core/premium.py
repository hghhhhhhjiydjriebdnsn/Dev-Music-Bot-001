"""PIHU MUSIC custom emoji helpers, with ordinary-emoji retry fallback.

The user-supplied catalog is data, never executable input. Pyrogram's HTML
parser uses <emoji id="...">; Bot API button icons use the same document IDs.
"""
import html as _html
import inspect
import json
import logging
import os
import re
from html.parser import HTMLParser
from pathlib import Path

log = logging.getLogger(__name__)
PREMIUM_EMOJI = json.loads(Path(__file__).with_name("premium_emoji.json").read_text())
_PATTERN = re.compile("|".join(re.escape(key) for key in sorted(PREMIUM_EMOJI, key=len, reverse=True)))
_custom_supported = True
# Any emoji glyph (including modifiers/joiners) that has no catalog ID is dropped
# from plain text, so the only emoji users see are the premium catalog ones.
_LOOSE_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\u2300-\u23FF"
    "\u2934\u2935\u3030\u303D\u3297\u3299\u00A9\u00AE\u203C\u2049\u2122\u2139"
    "\uFE0F\u200D\U0001F3FB-\U0001F3FF]+"
)
_LEADING_EMOJI = re.compile(
    "^[\\s\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\u2300-\u23FF"
    "\uFE0F\u200D\U0001F3FB-\U0001F3FF]+"
)


def enabled():
    return os.getenv("PREMIUM_EMOJIS", "true").lower() in {"1", "true", "yes", "on"}


def strip_leading_emoji(text):
    """Remove a leading glyph so the premium button icon replaces it (no doubles)."""
    stripped = _LEADING_EMOJI.sub("", str(text), count=1).strip()
    return stripped or str(text)


def button_icon(text):
    """Pick the matching leading emoji, without changing callback data."""
    override = os.getenv("CUSTOM_EMOJI_ID", "").strip()
    if override.isdigit():
        return override
    if not enabled() or not _custom_supported:
        return None
    match = _PATTERN.match(str(text).lstrip())
    return PREMIUM_EMOJI[match.group()] if match else None


def button_style(text, data):
    """Bot API button colour: success = green, danger = red, primary = blue."""
    lowered = str(text).lower()
    if data.startswith(("ogc:x:",)) or any(w in lowered for w in ("stop", "ban", "kick", "confirm", "ꜱᴛᴏᴘ", "sᴛᴏᴘ")):
        return "danger"
    if data.startswith(("ogs:p:", "ogc:r:", "ogu:start")) or any(
            w in lowered for w in ("play", "resume", "ᴘʟᴀʏ", "ʀᴇsᴜᴍᴇ", "add me", "ᴀᴅᴅ ᴍᴇ")):
        return "success"
    return "primary"


def build_keyboard(markup, icons=True):
    """Pyrogram InlineKeyboardMarkup -> Bot API reply_markup with colours + premium icons."""
    rows = []
    for row in markup.inline_keyboard:
        out = []
        for button in row:
            text = str(getattr(button, "text", ""))
            data = str(getattr(button, "callback_data", "") or "")
            item = {"text": text, "style": button_style(text, data)}
            url = getattr(button, "url", None)
            if url:
                item["url"] = str(url)
            else:
                item["callback_data"] = data
            if icons:
                icon = button_icon(text)
                if icon:
                    # The premium icon replaces the glyph: one emoji per button.
                    item["text"] = strip_leading_emoji(text)
                    item["icon_custom_emoji_id"] = icon
            out.append(item)
        rows.append(out)
    return {"inline_keyboard": rows}


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
        if self.skip:
            self.parts.append(data)
            return
        out, pos = [], 0
        for m in _PATTERN.finditer(data):
            out.append(_LOOSE_EMOJI.sub("", data[pos:m.start()]))
            out.append(f'<emoji id="{PREMIUM_EMOJI[m.group()]}">{m.group()}</emoji>')
            pos = m.end()
        out.append(_LOOSE_EMOJI.sub("", data[pos:]))
        self.parts.append("".join(out))

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


def md_to_html(text):
    """Small Markdown -> Telegram HTML converter for the legacy lang strings."""
    s = _html.escape(str(text), quote=False)
    s = re.sub(r"```(.+?)```", r"<pre>\1</pre>", s, flags=re.S)
    s = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)
    s = re.sub(r"__(.+?)__", r"<i>\1</i>", s, flags=re.S)
    s = re.sub(r"(?m)((?:^&gt; ?.*(?:\n|$))+)",
               lambda m: "<blockquote>" + re.sub(r"(?m)^&gt; ?", "", m.group(1)).rstrip("\n") + "</blockquote>\n", s)
    return s


# ------------------------------------------------------------------ Bot API
# Coloured buttons / button icons only exist in the Bot API, so any message that
# carries an inline keyboard is sent (or edited) through it in ONE request. The
# user therefore never sees a plain keyboard first and a coloured one later.
_EMOJI_TAG = re.compile(r'<emoji id="(\d+)">(.*?)</emoji>', re.S)
_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_TEXT_KEYS = {"parse_mode", "reply_markup", "quote", "disable_web_page_preview",
              "disable_notification", "reply_to_message_id"}
_PHOTO_KEYS = _TEXT_KEYS | {"photo", "caption"}
_EDIT_KEYS = {"parse_mode", "reply_markup", "disable_web_page_preview"}


def _bot_html(text):
    text = _BARE_AMP.sub("&amp;", str(text))
    return _EMOJI_TAG.sub(r'<tg-emoji emoji-id="\1">\2</tg-emoji>', text)


def _plain_html(text):
    return _EMOJI_TAG.sub(r"\2", str(text))


def _chat_kind(message):
    chat_type = getattr(getattr(message, "chat", None), "type", None)
    return str(getattr(chat_type, "value", chat_type)).lower()


def _can_style(message, markup, kwargs, allowed):
    try:
        from pyrogram.types import InlineKeyboardMarkup
        from config import config
    except Exception:
        return False
    client = getattr(message, "_client", None)
    is_bot = bool(getattr(client, "bot_token", None)) or bool(getattr(getattr(client, "me", None), "is_bot", False))
    return (isinstance(markup, InlineKeyboardMarkup) and bool(config.BOT_TOKEN) and is_bot
            and set(kwargs) <= allowed)


async def _api(method, payload, upload=None):
    """Call the Bot API. Returns the result, {} for 'not modified', or None on failure."""
    import aiohttp
    from config import config
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            if upload:
                field, filename, data = upload
                form = aiohttp.FormData()
                for key, value in payload.items():
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, ensure_ascii=False)
                    elif isinstance(value, bool):
                        value = "true" if value else "false"
                    form.add_field(key, str(value))
                form.add_field(field, data, filename=filename)
                request = session.post(url, data=form)
            else:
                request = session.post(url, json=payload)
            async with request as response:
                body = await response.json(content_type=None)
    except Exception as exc:
        log.warning("bot api %s failed: %s", method, type(exc).__name__)
        return None
    if body.get("ok"):
        return body.get("result") or {}
    description = str(body.get("description", ""))
    if "not modified" in description:
        return {}
    log.warning("bot api %s rejected: %s", method, description)
    return None


class _SentStub:
    """Minimal stand-in if the freshly sent message cannot be re-fetched."""

    def __init__(self, client, chat_id, message_id):
        from types import SimpleNamespace
        self._client = client
        self.id = message_id
        self.chat = SimpleNamespace(id=chat_id, type=None, title=None)
        self._pihu_keyboard_styled = True

    async def delete(self, *args, **kwargs):
        return await self._client.delete_messages(self.chat.id, self.id)

    async def edit_text(self, text, **kwargs):
        return await self._client.edit_message_text(self.chat.id, self.id, text, **kwargs)

    async def edit_caption(self, caption, **kwargs):
        return await self._client.edit_message_caption(self.chat.id, self.id, caption, **kwargs)


async def _as_message(message, result):
    client = message._client
    chat_id, message_id = result["chat"]["id"], result["message_id"]
    try:
        sent = await client.get_messages(chat_id, message_id)
        sent._pihu_keyboard_styled = True
        return sent
    except Exception:
        return _SentStub(client, chat_id, message_id)


def _send_params(message, kwargs, text_mode):
    params = {"chat_id": message.chat.id}
    reply_to = kwargs.get("reply_to_message_id")
    if reply_to is None:
        quote = kwargs.get("quote")
        if quote is None:
            quote = _chat_kind(message) != "private"
        if quote:
            reply_to = message.id
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    thread = getattr(message, "message_thread_id", None)
    if isinstance(thread, int) and thread:
        params["message_thread_id"] = thread
    if kwargs.get("disable_notification"):
        params["disable_notification"] = True
    if text_mode and kwargs.get("disable_web_page_preview"):
        params["link_preview_options"] = {"is_disabled": True}
    return params


async def _styled_send_text(message, html_text, markup, kwargs):
    for body, icons in ((html_text, True), (_plain_html(html_text), False)):
        payload = _send_params(message, kwargs, True)
        payload.update(text=_bot_html(body), parse_mode="HTML", reply_markup=build_keyboard(markup, icons))
        result = await _api("sendMessage", payload)
        if result:
            return await _as_message(message, result)
    return None


async def _styled_send_photo(message, photo, caption_html, markup, kwargs):
    upload = None
    if isinstance(photo, str) and os.path.isfile(photo):
        import asyncio
        data = await asyncio.to_thread(Path(photo).read_bytes)
        upload = ("photo", os.path.basename(photo), data)
    elif not (isinstance(photo, str) and photo.startswith(("http://", "https://"))):
        return None
    for body, icons in ((caption_html, True), (_plain_html(caption_html), False)):
        payload = _send_params(message, kwargs, False)
        payload.update(caption=_bot_html(body), parse_mode="HTML", reply_markup=build_keyboard(markup, icons))
        if upload is None:
            payload["photo"] = photo
        result = await _api("sendPhoto", payload, upload)
        if result:
            return await _as_message(message, result)
    return None


async def _styled_edit(message, html_text, markup, kwargs):
    media = any(getattr(message, attr, None) for attr in ("photo", "video", "audio", "document", "animation"))
    method, key = ("editMessageCaption", "caption") if media else ("editMessageText", "text")
    for body, icons in ((html_text, True), (_plain_html(html_text), False)):
        payload = {"chat_id": message.chat.id, "message_id": message.id, key: _bot_html(body),
                   "parse_mode": "HTML", "reply_markup": build_keyboard(markup, icons)}
        if not media and kwargs.get("disable_web_page_preview"):
            payload["link_preview_options"] = {"is_disabled": True}
        result = await _api(method, payload)
        if result is not None:
            try:
                message._pihu_keyboard_styled = True
            except Exception:
                pass
            return message
    return None


def install_parser_patch():
    """Decorate EVERY HTML message/caption at parse time, whichever helper sent it."""
    try:
        from pyrogram.parser.html import HTML as _HTML
    except Exception:
        return
    if getattr(_HTML, "_pihu_decorated", False):
        return
    original = _HTML.parse
    if inspect.iscoroutinefunction(original):
        async def parse(self, text, *args, **kwargs):
            try:
                text = decorate_html(text)
            except Exception:
                pass
            return await original(self, text, *args, **kwargs)
    else:
        def parse(self, text, *args, **kwargs):
            try:
                text = decorate_html(text)
            except Exception:
                pass
            return original(self, text, *args, **kwargs)
    _HTML.parse = parse
    _HTML._pihu_decorated = True


def install_message_patch():
    """Render every reply as styled HTML with premium emoji; keyboards go out already coloured.

    Falls back to the untouched original call on any failure, so replies never
    get lost because of styling.
    """
    from pyrogram import enums
    from pyrogram.types import Message
    if getattr(Message, "_pihu_styled", False):
        return
    install_parser_patch()
    orig_reply, orig_edit = Message.reply_text, Message.edit_text
    orig_photo = getattr(Message, "reply_photo", None)
    orig_markup = getattr(Message, "edit_reply_markup", None)

    def _html_for(text, kwargs):
        mode = kwargs.get("parse_mode")
        if mode is None:
            return decorate_html(md_to_html(text))
        if mode == enums.ParseMode.HTML or str(mode).lower().endswith("html"):
            return decorate_html(text)
        return None

    async def reply_text(self, text, *args, **kwargs):
        markup = kwargs.get("reply_markup")
        if not args and isinstance(text, str) and _can_style(self, markup, kwargs, _TEXT_KEYS):
            try:
                html_text = _html_for(text, kwargs)
                if html_text is not None:
                    sent = await _styled_send_text(self, html_text, markup, kwargs)
                    if sent is not None:
                        return sent
            except Exception as exc:
                log.warning("styled send failed: %s", type(exc).__name__)
        if "parse_mode" not in kwargs and isinstance(text, str):
            try:
                return await orig_reply(self, decorate_html(md_to_html(text)), *args,
                                        **{**kwargs, "parse_mode": enums.ParseMode.HTML})
            except Exception:
                pass
        return await orig_reply(self, text, *args, **kwargs)

    async def edit_text(self, text, *args, **kwargs):
        markup = kwargs.get("reply_markup")
        if not args and isinstance(text, str) and _can_style(self, markup, kwargs, _EDIT_KEYS):
            try:
                html_text = _html_for(text, kwargs)
                if html_text is not None:
                    done = await _styled_edit(self, html_text, markup, kwargs)
                    if done is not None:
                        return done
            except Exception as exc:
                log.warning("styled edit failed: %s", type(exc).__name__)
        if "parse_mode" not in kwargs and isinstance(text, str):
            try:
                return await orig_edit(self, decorate_html(md_to_html(text)), *args,
                                       **{**kwargs, "parse_mode": enums.ParseMode.HTML})
            except Exception:
                pass
        return await orig_edit(self, text, *args, **kwargs)

    Message.reply_text = reply_text
    Message.edit_text = edit_text

    if orig_photo is not None:
        async def reply_photo(self, *args, **kwargs):
            markup = kwargs.get("reply_markup")
            if not args and "photo" in kwargs and _can_style(self, markup, kwargs, _PHOTO_KEYS):
                try:
                    html_text = _html_for(str(kwargs.get("caption") or ""), kwargs)
                    if html_text is not None:
                        sent = await _styled_send_photo(self, kwargs["photo"], html_text, markup, kwargs)
                        if sent is not None:
                            return sent
                except Exception as exc:
                    log.warning("styled photo failed: %s", type(exc).__name__)
            return await orig_photo(self, *args, **kwargs)
        Message.reply_photo = reply_photo

    if orig_markup is not None:
        async def edit_reply_markup(self, reply_markup=None, *args, **kwargs):
            if not args and not kwargs and _can_style(self, reply_markup, {}, set()):
                payload = {"chat_id": self.chat.id, "message_id": self.id,
                           "reply_markup": build_keyboard(reply_markup, True)}
                result = await _api("editMessageReplyMarkup", payload)
                if result is None:
                    payload["reply_markup"] = build_keyboard(reply_markup, False)
                    result = await _api("editMessageReplyMarkup", payload)
                if result is not None:
                    try:
                        self._pihu_keyboard_styled = True
                    except Exception:
                        pass
                    return self
            return await orig_markup(self, reply_markup, *args, **kwargs)
        Message.edit_reply_markup = edit_reply_markup

    Message._pihu_styled = True
