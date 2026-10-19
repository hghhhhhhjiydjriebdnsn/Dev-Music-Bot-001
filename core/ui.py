"""
Music Player, Telegram Voice Chat Bot
Copyright (c) 2021-present Asm Safone <https://github.com/AsmSafone>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>
"""

"""MAHI MUSIC's Telegram presentation, searches, and inline controls.

Callbacks deliberately use opaque short-lived tokens rather than accepting
queries or URLs supplied in callback data. Pyrogram/Telegram buttons use the
standard button API; their exact rendering is client-dependent.
"""

import html
import inspect
import os
import tempfile
import time
import secrets
import aiohttp
from collections import OrderedDict

from pyrogram import filters, enums
from core.premium import send_text, send_audio, edit_text, button_icon
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


_TOKEN_TTL = 15 * 60
_TOKEN_LIMIT = 500
_search_tokens = OrderedDict()


def _h(value):
    return html.escape(str(value or ""), quote=True)


def _cache_track(user_id, chat_id, track):
    now = time.monotonic()
    for key, item in list(_search_tokens.items()):
        if item["expires"] <= now:
            _search_tokens.pop(key, None)
    token = secrets.token_urlsafe(6)
    _search_tokens[token] = {
        "user": user_id,
        "chat": chat_id,
        "track": track,
        "expires": now + _TOKEN_TTL,
        "played": False,
    }
    while len(_search_tokens) > _TOKEN_LIMIT:
        _search_tokens.popitem(last=False)
    return token


def _keyboard_controls(chat_id):
    rows = [
        [InlineKeyboardButton("⏸ Pause", callback_data=f"ogc:p:{chat_id}"),
         InlineKeyboardButton("▶️ Resume", callback_data=f"ogc:r:{chat_id}")],
        [InlineKeyboardButton("⏭ Skip", callback_data=f"ogc:s:{chat_id}"),
         InlineKeyboardButton("⏹ Stop", callback_data=f"ogc:x:{chat_id}")],
        [InlineKeyboardButton("🔁 Loop", callback_data=f"ogc:l:{chat_id}"),
         InlineKeyboardButton("🔀 Shuffle", callback_data=f"ogc:h:{chat_id}")],
        [InlineKeyboardButton("📋 Queue", callback_data=f"ogc:q:{chat_id}")],
        [InlineKeyboardButton("⬇️ Download current track", callback_data=f"ogc:d:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def _track_keyboard(token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Play / Add", callback_data=f"ogs:p:{token}"),
         InlineKeyboardButton("⬇️ Download", callback_data=f"ogs:d:{token}")]
    ])


async def apply_button_style(message, markup):
    """Best-effort Bot API styling; ordinary Pyrogram buttons remain fallback.

    Telegram Bot API button colors and custom icons are eligibility/client
    dependent. If styling is unavailable, the original inline keyboard still
    works through Pyrogram callbacks.
    """
    from config import config
    token = getattr(config, "BOT_TOKEN", None)
    if not token or not message or not markup:
        return False
    custom_emoji_id = os.environ.get("CUSTOM_EMOJI_ID", "").strip()
    custom_emoji_id = custom_emoji_id if custom_emoji_id.isdigit() else None
    keyboard = []
    for row in markup.inline_keyboard:
        styled_row = []
        for button in row:
            text = str(getattr(button, "text", ""))
            data = str(getattr(button, "callback_data", "") or "")
            if data.startswith(("ogc:x:",)) or any(word in text for word in ("Stop", "Ban", "Kick", "Confirm")):
                style = "danger"
            elif data.startswith(("ogs:p:",)) or "Play" in text or "Resume" in text:
                style = "success"
            elif data.startswith(("ogc:p:", "ogc:r:", "ogc:s:", "ogc:l:", "ogc:h:")):
                style = "primary"
            else:
                style = "primary"
            serialized = {"text": text, "style": style}
            url = getattr(button, "url", None)
            if url:
                serialized["url"] = str(url)
            else:
                serialized["callback_data"] = data
            icon_id = custom_emoji_id or button_icon(text)
            if icon_id:
                serialized["icon_custom_emoji_id"] = icon_id
            styled_row.append(serialized)
        keyboard.append(styled_row)
    payload = {
        "chat_id": message.chat.id,
        "message_id": message.id,
        "reply_markup": {"inline_keyboard": keyboard},
    }
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
                json=payload,
            ) as response:
                if response.status == 200:
                    return True
                for row in keyboard:
                    for button in row:
                        button.pop("icon_custom_emoji_id", None)
                async with session.post(
                    f"https://api.telegram.org/bot{token}/editMessageReplyMarkup", json=payload
                ) as fallback:
                    return fallback.status == 200
    except Exception:
        # Never log Bot API URLs (which include the bot token); leave the
        # standard Pyrogram keyboard intact when Bot API edits fail.
        return False


async def _send_text(message, *args, **kwargs):
    # Telegram user accounts cannot attach bot inline keyboards.
    from config import config
    if not config.BOT_TOKEN:
        kwargs.pop("reply_markup", None)
    return await send_text(message, *args, **kwargs)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _provider_api():
    # Loaded lazily to avoid coupling core.ui import to the provider module or
    # creating a core -> ui -> core import cycle during bot startup.
    from ogmusic.providers import service
    return service


async def _is_admin_click(query):
    """Authorize the actual callback clicker, never the message sender."""
    from config import config
    uid = getattr(query.from_user, "id", None)
    if uid is None:
        return False
    if uid in getattr(config, "SUDOERS", set()):
        return True
    chat = query.message.chat
    try:
        member = await chat.get_member(uid)
        status = getattr(member, "status", None)
        return str(getattr(status, "value", status)).lower() in {
            "owner", "administrator", "creator", "chatmemberstatus.owner",
            "chatmemberstatus.administrator",
        }
    except Exception:
        return False


def _track_song(track, message, user):
    from core.song import Song
    song = Song(track.to_song_dict(), message)
    song.requested_by = user
    # Provider tracks are remote audio streams, even if this group's normal
    # stream mode is video.
    song.audio_only = True
    return song


async def _search_tracks(query, provider=None):
    service = _provider_api()
    return await _maybe_await(service.search(query, limit=5, provider=provider))


def register_ui(client):
    """Register public PIHU MUSIC commands and safe callback handlers."""
    from config import config

    @client.on_message(filters.command("start", config.PREFIXES) & ~filters.bot)
    async def start_ui(_, message):
        display = _h(message.from_user.first_name if message.from_user else "music fan")
        text = (
            f"🎵 <b>Welcome to PIHU MUSIC, {display}!</b>\n\n"
            "Stream music in your group's voice chat, search tracks, build a queue, "
            "and download supported audio. Add me to a group and use <code>/play</code> "
            "or <code>/search</code> to get started.\n\n"
            "Use /help for commands and playback controls."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Help & commands", callback_data="ogu:help"),
             InlineKeyboardButton("✨ Premium", callback_data="ogu:premium")],
            [InlineKeyboardButton("🔎 Search tips", callback_data="ogu:search")],
        ])
        sent = await _send_text(message, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        await apply_button_style(sent, keyboard)

    @client.on_message(filters.command("help", config.PREFIXES) & ~filters.bot)
    async def help_ui(_, message):
        sent = await _send_text(message, 
            _help_text(), reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Premium", callback_data="ogu:premium")],
                [InlineKeyboardButton("🎵 Start", callback_data="ogu:start")],
            ]), parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True,
        )
        await apply_button_style(sent, sent.reply_markup)

    @client.on_message(filters.command("premium", config.PREFIXES) & ~filters.bot)
    async def premium_ui(_, message):
        await _send_text(message, _premium_text(), parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)

    @client.on_message(filters.command("search", config.PREFIXES) & ~filters.bot)
    async def search_ui(_, message):
        query = _command_query(message.text)
        if not query:
            return await _send_text(message, "🔎 Send a query, for example: <code>/search Daft Punk One More Time</code>", parse_mode=enums.ParseMode.HTML)
        status = await _send_text(message, "🔎 <b>Searching tracks…</b>", parse_mode=enums.ParseMode.HTML)
        try:
            tracks = await _search_tracks(query)
        except Exception as exc:
            await edit_text(status, "⚠️ Search is temporarily unavailable. Try again shortly.", parse_mode=enums.ParseMode.HTML)
            return
        if not tracks:
            return await edit_text(status, "No tracks found. Try another search.")
        rows = []
        for index, track in enumerate(tracks[:5], 1):
            token = _cache_track(message.from_user.id if message.from_user else 0, message.chat.id, track)
            artists_value = getattr(track, "artists", "") or ""
            artists = ", ".join(artists_value) if isinstance(artists_value, (list, tuple)) else str(artists_value)
            title = _h(getattr(track, "title", "Untitled"))
            from ogmusic.models import format_duration
            duration = _h(format_duration(getattr(track, "duration", 0)))
            label = f"{index}. {title}"
            if artists:
                label += f" — {_h(artists)}"
            if duration:
                label += f" · {duration}"
            keyboard = _track_keyboard(token)
            sent = await send_text(status, label, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            await apply_button_style(sent, keyboard)
        await status.delete()

    @client.on_message(filters.command(["song", "download"], config.PREFIXES) & ~filters.bot)
    async def download_ui(_, message):
        query = _command_query(message.text)
        if not query:
            return await _send_text(message, "⬇️ Send a query, for example: <code>/song artist - title</code>", parse_mode=enums.ParseMode.HTML)
        status = await _send_text(message, "🔎 Finding an audio track…", parse_mode=enums.ParseMode.HTML)
        try:
            tracks = await _search_tracks(query)
            if not tracks:
                return await edit_text(status, "No track found for that query.")
            track = tracks[0]
            await edit_text(status, "⬇️ Preparing the audio file…", parse_mode=enums.ParseMode.HTML)
            from ogmusic.providers import download_audio
            with tempfile.TemporaryDirectory(prefix="ogmusic-") as directory:
                path = await _maybe_await(download_audio(track, directory, max_bytes=50 * 1024 * 1024))
                path = os.fspath(path)
                title = _h(getattr(track, "title", "Audio track"))
                await send_audio(message, path, caption=f"🎵 <b>{title}</b> · MAHI MUSIC", parse_mode=enums.ParseMode.HTML)
            await status.delete()
        except Exception as exc:
            await edit_text(status, "⚠️ This audio could not be downloaded. The provider may be unavailable or the file exceeds the limit.", parse_mode=enums.ParseMode.HTML)

    @client.on_callback_query(filters.regex(r"^ogu:"))
    async def menu_callback(_, query):
        await query.answer()
        action = query.data.split(":", 1)[1]
        if action == "premium":
            await send_text(query.message, _premium_text(), parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        elif action == "help":
            sent = await send_text(query.message, _help_text(), reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Premium", callback_data="ogu:premium")],
                [InlineKeyboardButton("🎵 Start", callback_data="ogu:start")],
            ]), parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            await apply_button_style(sent, sent.reply_markup)
        elif action == "start":
            await send_text(query.message, "🎵 Use /play or /search in a group to get started. See /help for commands.")
        elif action == "search":
            await send_text(query.message, "Try <code>/search artist - track</code>, then choose Play / Add or Download.", parse_mode=enums.ParseMode.HTML)

    @client.on_callback_query(filters.regex(r"^ogs:"))
    async def search_callback(_, query):
        # Acknowledge promptly before any API or playback work.
        await query.answer()
        try:
            _, action, token = query.data.split(":", 2)
        except ValueError:
            return
        item = _search_tokens.get(token)
        if (not item or item["expires"] <= time.monotonic()
                or item["user"] != query.from_user.id
                or item["chat"] != query.message.chat.id):
            if item and item["expires"] <= time.monotonic():
                _search_tokens.pop(token, None)
            return await send_text(query.message, "This result expired or belongs to another request. Run /search again.")
        if action == "p":
            if item["played"]:
                return await send_text(query.message, "This result button was already used. Search again to create a fresh result.")
            item["played"] = True  # replay invalidation before doing any async work
            try:
                await _enqueue_search_track(query, item)
            except Exception as exc:
                await send_text(query.message, "⚠️ Could not start this track. Check the voice chat and assistant permissions.", parse_mode=enums.ParseMode.HTML)
        elif action == "d":
            await _download_search_track(query, item)

    @client.on_callback_query(filters.regex(r"^ogc:"))
    async def playback_callback(_, query):
        # Ack first; permissions are evaluated against the callback clicker.
        await query.answer()
        try:
            _, action, raw_chat = query.data.split(":", 2)
            chat_id = int(raw_chat)
        except (ValueError, AttributeError):
            return
        if query.message.chat.id != chat_id or not await _is_admin_click(query):
            return await send_text(query.message, "Only a group admin or configured sudo user can use playback controls.")
        await _run_control(query, action, chat_id)


def _command_query(text):
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _help_text():
    return (
        "🎵 <b>PIHU MUSIC — Help</b>\n\n"
        "<b>Find and play</b>\n"
        "• <code>/play query</code> — play a track in the group's voice chat\n"
        "• <code>/search query</code> — show up to five track choices\n"
        "• <code>/song query</code> or <code>/download query</code> — send a supported audio file\n"
        "• Tap <b>Play / Add</b> to start or queue a search result.\n\n"
        "<b>Queue and controls</b>\n"
        "• <code>/queue</code>, <code>/skip</code>, <code>/pause</code>, <code>/resume</code>\n"
        "• <code>/stop</code>, <code>/loop</code>, <code>/shuffle</code>, <code>/join</code>\n"
        "• Playback buttons for pause, resume, skip, stop, loop, shuffle and queue\n\n"
        "<b>Group management</b>\n"
        "• <code>/admin</code> or <code>/panel</code> — group settings\n"
        "• <code>/manage</code> — reply to a member for moderation\n"
        "• <code>/welcome on|off</code>, <code>/setwelcome text</code>\n"
        "• <code>/ban</code>, <code>/unban</code>, <code>/kick</code>, <code>/muteuser</code>, <code>/unmuteuser</code>\n\n"
        "Existing radio, playlist, import/export and group configuration commands are also available. "
        "Group playback controls require an administrator or configured sudo user."
    )


def _premium_text():
    return (
        "✨ <b>PIHU MUSIC features</b>\n\n"
        "API music streaming, downloads, a violet/cyan player, colorful control buttons, your premium emoji catalog, admin panels, welcome management and member controls.\n\n"
        "There is no paid subscription or premium entitlement implemented in this bot. "
        "This page is an honest feature overview, not an offer to purchase access."
    )


async def _enqueue_search_track(query, item):
    from core.groups import get_group, get_queue, set_group
    from core.stream import start_stream
    from core.ui import _track_song
    chat = query.message.chat
    if str(getattr(chat.type, "value", chat.type)).lower() == "private":
        return await send_text(query.message, "Use Play / Add from a group chat so I can join its voice chat.")
    group = get_group(chat.id)
    if group["admins_only"] and not await _is_admin_click(query):
        return await send_text(query.message, "Only a group admin or configured sudo user may add tracks while admin-only mode is enabled.")
    song = _track_song(item["track"], query.message, query.from_user)
    if not group["is_playing"]:
        # Update state only after startup succeeds; start_stream also rolls back
        # its own state on initial playback errors.
        set_group(chat.id, is_playing=True, now_playing=song)
        try:
            from lang import load
            await start_stream(song, load(group.get("lang", "en")))
        except Exception:
            set_group(chat.id, is_playing=False, now_playing=None)
            raise
        await send_text(query.message, f"▶️ Started <b>{_h(song.title)}</b>.", parse_mode=enums.ParseMode.HTML)
    else:
        queue = get_queue(chat.id)
        await queue.put(song)
        await send_text(query.message, f"➕ Added <b>{_h(song.title)}</b> to the queue · position {len(queue)}.", parse_mode=enums.ParseMode.HTML)


async def _download_search_track(query, item):
    import tempfile
    from ogmusic.providers import download_audio
    track = item["track"]
    status = await send_text(query.message, "⬇️ Preparing audio…")
    try:
        with tempfile.TemporaryDirectory(prefix="ogmusic-") as directory:
            path = await _maybe_await(download_audio(track, directory, max_bytes=50 * 1024 * 1024))
            await send_audio(query.message, os.fspath(path), caption=f"🎵 <b>{_h(getattr(track, 'title', 'Audio track'))}</b> · MAHI MUSIC", parse_mode=enums.ParseMode.HTML)
        await status.delete()
    except Exception as exc:
        await edit_text(status, "⚠️ This audio could not be downloaded. The provider may be unavailable or the file exceeds the limit.", parse_mode=enums.ParseMode.HTML)


async def _run_control(query, action, chat_id):
    from core.stream import pytgcalls, start_stream, app
    from core.groups import get_group, get_queue, set_group, clear_queue, set_title
    from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError
    from lang import load
    group = get_group(chat_id)
    lang = load(group.get("lang", "en"))
    try:
        if action == "p":
            await pytgcalls.pause_stream(chat_id)
            note = "⏸ Playback paused."
        elif action == "r":
            await pytgcalls.resume_stream(chat_id)
            note = "▶️ Playback resumed."
        elif action == "s":
            if group.get("loop") and group.get("now_playing"):
                await start_stream(group["now_playing"], lang)
            else:
                queue = get_queue(chat_id)
                if not len(queue):
                    set_group(chat_id, is_playing=False, now_playing=None)
                    await set_title(chat_id, "", client=app)
                    await pytgcalls.leave_call(chat_id)
                    note = "⏭ Queue empty; left the voice chat."
                else:
                    song = await queue.get()
                    if not song.parsed:
                        ok, status = await song.parse()
                        if not ok:
                            raise RuntimeError(status)
                    set_group(chat_id, is_playing=True, now_playing=song)
                    await start_stream(song, lang)
                    note = f"⏭ Now playing <b>{_h(song.title)}</b>."
        elif action == "x":
            set_group(chat_id, is_playing=False, now_playing=None)
            clear_queue(chat_id)
            await pytgcalls.leave_call(chat_id)
            await set_title(chat_id, "", client=app)
            note = "⏹ Stopped playback and cleared the queue."
        elif action == "l":
            enabled = not bool(group.get("loop"))
            set_group(chat_id, loop=enabled)
            note = f"🔁 Loop {'enabled' if enabled else 'disabled'}."
        elif action == "h":
            queue = get_queue(chat_id)
            if len(queue):
                from core.groups import shuffle_queue
                shuffle_queue(chat_id)
                note = "🔀 Queue shuffled."
            else:
                note = "The queue is empty."
        elif action == "q":
            queue = get_queue(chat_id)
            text = _queue_html(queue) if len(queue) else "📋 The queue is empty."
            await send_text(query.message, text, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            return
        elif action == "d":
            current = group.get("now_playing")
            if current is None:
                return await send_text(query.message, "There is no current track to download.")
            if not getattr(current, "provider", None):
                return await send_text(query.message, "Use /song title to download an API track. This legacy stream has no downloadable provider track.")
            from ogmusic.providers import Track
            from ogmusic.models import duration_seconds
            track = Track(title=current.title, artists=getattr(current, "artists", ""),
                          duration=duration_seconds(current.duration), thumbnail=current.thumb,
                          stream_url=current.remote, source_url=current.source,
                          provider=current.provider)
            from ogmusic.providers import download_audio
            with tempfile.TemporaryDirectory(prefix="ogmusic-") as directory:
                path = await _maybe_await(download_audio(
                    track, directory, max_bytes=50 * 1024 * 1024
                ))
                await send_audio(query.message, 
                    os.fspath(path),
                    caption=f"🎵 <b>{_h(track.title)}</b> · PIHU MUSIC",
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        else:
            return
        await send_text(query.message, note, parse_mode=enums.ParseMode.HTML)
    except (NoActiveGroupCall, NotInCallError):
        if action == "x":
            await send_text(query.message, "⏹ Playback stopped; there was no active voice chat.")
        else:
            await send_text(query.message, "There is no active voice-chat playback.")
    except Exception as exc:
        await send_text(query.message, "⚠️ Control failed. Check the voice chat, assistant permissions, or try again.", parse_mode=enums.ParseMode.HTML)


def _queue_html(queue):
    lines = ["📋 <b>Up next</b>"]
    for index, song in enumerate(queue, 1):
        if index > 10:
            lines.append(f"… and {len(queue) - 10} more")
            break
        title = _h(getattr(song, "title", "Untitled"))
        source = _h(getattr(song, "source", ""))
        user = getattr(song, "requested_by", None)
        requester = _h(getattr(user, "first_name", "Unknown"))
        lines.append(f'{index}. <a href="{source}">{title}</a> · {requester}')
    return "\n".join(lines)
