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

import os
import time
from config import config
from core.premium import send_text, send_photo
from core.song import Song
from pyrogram import Client, enums
from yt_dlp import YoutubeDL
from pytgcalls import PyTgCalls
from core.funcs import generate_cover
from core.groups import get_group, set_title
from pytgcalls.types.stream import MediaStream
from pyrogram.raw.types import InputPeerChannel
from pytgcalls.types import AudioQuality, VideoQuality
from pyrogram.raw.functions.phone import CreateGroupCall
from pytgcalls.exceptions import NoActiveGroupCall


safone = {}
ydl_opts = {
    "quiet": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
}
app = Client(
    "MusicPlayerUB",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.SESSION,
    in_memory=True,
)
ytdl = YoutubeDL(ydl_opts)
pytgcalls = PyTgCalls(app)

from core import assistants as _assistants
_assistants.set_primary(app, pytgcalls)


async def start_stream(song: Song, lang):
    chat = song.request_msg.chat
    _assistant = _assistants.for_chat(chat.id)
    _calls, _app = _assistant.calls, _assistant.app
    if safone.get(chat.id) is not None:
        try:
            await safone[chat.id].delete()
        except BaseException:
            pass
    infomsg = await send_text(song.request_msg, lang["downloading"])
    thumb = None
    started = None
    try:
        from core.assistant_join import ensure_assistant
        await ensure_assistant(chat, _assistant)
        if getattr(song, "provider", None):
            from ogmusic.providers import validate_public_url
            await validate_public_url(song.remote)
        try:
            await _calls.play(chat.id, get_quality(song))
        except NoActiveGroupCall:
            peer = await _app.resolve_peer(chat.id)
            await _app.invoke(
                CreateGroupCall(
                    peer=InputPeerChannel(
                        channel_id=peer.channel_id,
                        access_hash=peer.access_hash,
                    ),
                    random_id=_app.rnd_id() // 9000000000,
                )
            )
            # Retry once after creating the group call; the second failure is
            # surfaced and group state is reset below rather than recursing.
            await _calls.play(chat.id, get_quality(song))
        started = time.monotonic()
    except Exception:
        from core.groups import set_group
        set_group(chat.id, is_playing=False, now_playing=None)
        try:
            await infomsg.delete()
        except BaseException:
            pass
        raise

    try:
        await set_title(chat.id, song.title or "", client=_app)
    except Exception:
        # Voice playback is already active. A title update must not interrupt it.
        pass

    import html
    title = html.escape(str(song.title or "Untitled"), quote=True)
    source = html.escape(str(song.source or ""), quote=True)
    duration = html.escape(str(song.duration or "N/A"), quote=True)
    user = song.requested_by
    if user and getattr(user, "id", None):
        name = html.escape(str(getattr(user, "first_name", None) or "User"), quote=True)
        requester = f'<a href="tg://user?id={user.id}">{name}</a>'  # mention: taps open the profile
    else:
        title_only = getattr(getattr(song.request_msg, "sender_chat", None), "title", None)
        requester = html.escape(str(title_only or "Unknown"), quote=True)
    from core.fonts import sc, bold_italic
    from ogmusic.models import duration_seconds
    support_line = ""
    support_url = str(getattr(config, "SUPPORT_URL", "") or "").strip()
    if support_url.startswith(("https://", "http://")):
        support_name = os.getenv("SUPPORT_NAME", "").strip() or support_url.rstrip("/").rsplit("/", 1)[-1].lstrip("@+")
        support_line = (f"\n<b>💬 {sc('support')}</b> : "
                        f'<a href="{html.escape(support_url, quote=True)}">{html.escape(support_name or "Support", quote=True)}</a>')
    from core import progress
    total = duration_seconds(song.duration)

    def render(progress_line):
        return (
            f"🎵 <b>{bold_italic('Now Playing')}</b> ✨\n\n"
            f"<b>{title}</b>  {progress_line}\n"
            f"<blockquote><b>⏱ {sc('duration')}</b> : <code>{duration}</code>\n"
            f"<b>👤 {sc('requested by')}</b> : {requester}"
            f"{support_line}</blockquote>"
        )

    caption = render(progress.bar_line(0, total))
    try:
        # Cover creation is optional presentation: any failure falls back to a
        # visible text player card and never rolls back healthy audio.
        thumb = await generate_cover(song.title or "", chat.title or "", chat.id, song.thumb)
        from core.ui import _keyboard_controls, apply_button_style
        keyboard = _keyboard_controls(chat.id) if config.BOT_TOKEN else None
        player_msg = await send_photo(song.request_msg, 
            photo=thumb,
            caption=caption,
            quote=False,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
        await apply_button_style(player_msg, keyboard)
        safone[chat.id] = player_msg
        progress.begin(chat.id, song, player_msg, True, render, total, started)
    except Exception:
        from core.ui import _keyboard_controls, apply_button_style
        keyboard = _keyboard_controls(chat.id) if config.BOT_TOKEN else None
        player_msg = await send_text(song.request_msg, 
            caption + f"\n<i>🖼 {sc('cover unavailable · audio is playing normally')}</i>",
            quote=False,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        await apply_button_style(player_msg, keyboard)
        safone[chat.id] = player_msg
        progress.begin(chat.id, song, player_msg, False,
                       lambda line: render(line) + f"\n<i>🖼 {sc('cover unavailable · audio is playing normally')}</i>",
                       total, started)
    finally:
        try:
            await infomsg.delete()
        except BaseException:
            pass
        if thumb and os.path.exists(thumb):
            try:
                os.remove(thumb)
            except OSError:
                pass


def get_quality(song: Song) -> MediaStream:
    group = get_group(song.request_msg.chat.id)
    if group["stream_mode"] == "video" and not getattr(song, "audio_only", False):
        if config.QUALITY.lower() == "high":
            return MediaStream(
                song.remote,
                AudioQuality.HIGH,
                VideoQuality.FHD_1080p,
                headers=song.headers,
            )
        elif config.QUALITY.lower() == "medium":
            return MediaStream(
                song.remote,
                AudioQuality.MEDIUM,
                VideoQuality.HD_720p,
                headers=song.headers,
            )
        elif config.QUALITY.lower() == "low":
            return MediaStream(
                song.remote,
                AudioQuality.LOW,
                VideoQuality.SD_480p,
                headers=song.headers,
            )
        else:
            print("WARNING: Invalid Quality Specified. Defaulting to High!")
            return MediaStream(
                song.remote,
                AudioQuality.HIGH,
                VideoQuality.FHD_1080p,
                headers=song.headers,
            )
    else:
        if config.QUALITY.lower() == "high":
            return MediaStream(
                song.remote,
                AudioQuality.HIGH,
                video_flags=MediaStream.Flags.IGNORE,
                headers=song.headers,
            )
        elif config.QUALITY.lower() == "medium":
            return MediaStream(
                song.remote,
                AudioQuality.MEDIUM,
                video_flags=MediaStream.Flags.IGNORE,
                headers=song.headers,
            )
        elif config.QUALITY.lower() == "low":
            return MediaStream(
                song.remote,
                AudioQuality.LOW,
                video_flags=MediaStream.Flags.IGNORE,
                headers=song.headers,
            )
        else:
            print("WARNING: Invalid Quality Specified. Defaulting to High!")
            return MediaStream(
                song.remote,
                AudioQuality.HIGH,
                video_flags=MediaStream.Flags.IGNORE,
                headers=song.headers,
            )
