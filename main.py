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
import json
import shutil
from config import config
from core.song import Song
from pyrogram.types import Message
from pytgcalls import filters as fl
from pyrogram import Client, filters
from pytgcalls.types import Update, ChatUpdate
from pytgcalls.types.stream import StreamEnded
from core.decorators import language, register, only_admins, handle_error
from pytgcalls.exceptions import (
    NotInCallError, NoActiveGroupCall)
from core import (
    app, ytdl, safone, search, is_sudo, is_admin, get_group, get_queue,
    pytgcalls, set_group, set_title, all_groups, clear_queue, check_yt_url,
    extract_args, start_stream, shuffle_queue, delete_messages,
    get_spotify_playlist, get_youtube_playlist)


REPO = """
🎵 **𝗠𝗔𝗛𝗜 𝗠𝗨𝗦𝗜𝗖**

> 📦 ʙᴀsᴇᴅ ᴏɴ [MusicPlayer](https://github.com/AsmSafone/MusicPlayer)
> 📜 ʟɪᴄᴇɴsᴇ : AGPL-3.0-or-later
"""

if config.BOT_TOKEN:
    bot = Client(
        "MusicPlayer",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        in_memory=True,
    )
    client = bot
else:
    client = app

from core import assistants as _assistants_mod
_assistants_mod.BOT = client if config.BOT_TOKEN else None


from core.moderation import register_moderation
from core.ui import register_ui, _track_song

from core.owner import register_owner
from core.premium import install_message_patch
from core.assistants import calls_for, app_for, add_update_handler

install_message_patch()
register_moderation(client)
register_ui(client)
register_owner(client)


@client.on_message(filters.command("repo", config.PREFIXES) & ~filters.bot)
@handle_error
async def repo(_, message: Message):
    await message.reply_text(REPO, disable_web_page_preview=True)


@client.on_message(filters.command("ping", config.PREFIXES) & ~filters.bot)
@handle_error
async def ping(_, message: Message):
    await message.reply_text(f"🏓 **𝗣𝗼𝗻𝗴!**\n> ⚡ ʟᴀᴛᴇɴᴄʏ : `{pytgcalls.ping} ms`")


@client.on_message(filters.command("join", config.PREFIXES) & ~filters.private)
@register
@language
@handle_error
async def join_vc(_, message: Message, lang):
    # Join is explicit and permission-gated; ordinary /play keeps its existing
    # automatic create/join behavior. Use only a join API exposed by this
    # installed PyTgCalls build, never fabricate a stream source.
    if not (await is_admin(message) or await is_sudo(message)):
        k = await message.reply_text(lang["notAllowed"])
        return await delete_messages([message, k])
    _pc = calls_for(message.chat.id)
    join_method = getattr(_pc, "join_call", None) or getattr(_pc, "join_group_call", None)
    if join_method is None:
        k = await message.reply_text("This PyTgCalls version has no standalone join method. Use /play to join and start audio.")
        return await delete_messages([message, k])
    try:
        result = join_method(message.chat.id)
        if hasattr(result, "__await__"):
            await result
        k = await message.reply_text("Joined the voice chat.")
    except Exception as exc:
        k = await message.reply_text("Could not join the voice chat. Check assistant permissions and try /play.")
    await delete_messages([message, k])


@client.on_message(filters.command(["p", "play"], config.PREFIXES) & ~filters.private)
@register
@language
@handle_error
async def play_stream(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"])
            return await delete_messages([message, k])

    import asyncio
    from pyrogram import enums
    from core.fonts import sc
    from core.premium import send_text, edit_text
    _frames = ["🔎 " + sc("searching"), "🎵 " + sc("searching"), "🔎 " + sc("searching"), "🎶 " + sc("searching")]
    anim_msg = await send_text(message, _frames[0], parse_mode=enums.ParseMode.HTML, quote=False)

    async def _animate():
        i = 0
        try:
            while True:
                await asyncio.sleep(1.2)  # stays well under Telegram's edit rate limit
                i = (i + 1) % len(_frames)
                try:
                    await edit_text(anim_msg, _frames[i], parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    anim_task = asyncio.create_task(_animate())
    try:
        song = await search(message)
        if song is None:
            anim_task.cancel()
            k = await message.reply_text(lang["notFound"])
            return await delete_messages([message, k, anim_msg])
        ok, status = await song.parse()
        if not ok:
            anim_task.cancel()
            try:
                await anim_msg.delete()
            except Exception:
                pass
            raise Exception(status)
    finally:
        anim_task.cancel()
    # delete_messages() sleeps 10s; awaiting it here delayed playback start.
    try:
        await anim_msg.delete()
    except Exception:
        pass

    if not group["is_playing"]:
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        await delete_messages([message])
    else:
        queue = get_queue(chat_id)
        await queue.put(song)
        k = await message.reply_text(
            lang["addedToQueue"] % (song.title, song.source, len(queue)),
            disable_web_page_preview=True,
        )
        await delete_messages([message, k])


@client.on_message(
    filters.command(["radio", "stream"], config.PREFIXES) & ~filters.private
)
@register
@language
@handle_error
async def live_stream(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"])
            return await delete_messages([message, k])
    args = extract_args(message.text)
    if args is None:
        k = await message.reply_text(lang["notFound"])
        return await delete_messages([message, k])
    if " " in args and args.count(" ") == 1 and args[-5:] == "parse":
        song = Song({"source": args.split(" ")[0], "parsed": False}, message)
    else:
        is_yt_url, url = check_yt_url(args)
        if is_yt_url:
            meta = ytdl.extract_info(url, download=False)
            formats = meta.get("formats", [meta])
            for f in formats:
                ytstreamlink = f["url"]
            link = ytstreamlink
            song = Song(
                {"title": "YouTube Stream", "source": link, "remote": link}, message
            )
        else:
            song = Song(
                {"title": "Live Stream", "source": args, "remote": args}, message
            )
    ok, status = await song.parse()
    if not ok:
        raise Exception(status)
    if not group["is_playing"]:
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        await delete_messages([message])
    else:
        queue = get_queue(chat_id)
        await queue.put(song)
        k = await message.reply_text(
            lang["addedToQueue"] % (song.title, song.source, len(queue)),
            disable_web_page_preview=True,
        )
        await delete_messages([message, k])


@client.on_message(
    filters.command(["skip", "next"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def skip_track(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["loop"]:
        await start_stream(group["now_playing"], lang)
    else:
        queue = get_queue(chat_id)
        if len(queue) > 0:
            next_song = await queue.get()
            if not next_song.parsed:
                ok, status = await next_song.parse()
                if not ok:
                    raise Exception(status)
            set_group(chat_id, now_playing=next_song)
            await start_stream(next_song, lang)
            await delete_messages([message])
        else:
            set_group(chat_id, is_playing=False, now_playing=None)
            await set_title(message, "")
            try:
                await calls_for(chat_id).leave_call(chat_id)
                k = await message.reply_text(lang["queueEmpty"])
            except (NoActiveGroupCall, NotInCallError):
                k = await message.reply_text(lang["notActive"])
            await delete_messages([message, k])


@client.on_message(filters.command(["m", "mute"], config.PREFIXES) & ~filters.private)
@register
@language
@only_admins
@handle_error
async def mute_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await calls_for(chat_id).mute_stream(chat_id)
        k = await message.reply_text(lang["muted"])
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["um", "unmute"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def unmute_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await calls_for(chat_id).unmute_stream(chat_id)
        k = await message.reply_text(lang["unmuted"])
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(filters.command(["ps", "pause"], config.PREFIXES) & ~filters.private)
@register
@language
@only_admins
@handle_error
async def pause_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await calls_for(chat_id).pause_stream(chat_id)
        from core import progress
        progress.pause(chat_id)
        k = await message.reply_text(lang["paused"])
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["rs", "resume"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def resume_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await calls_for(chat_id).resume_stream(chat_id)
        from core import progress
        progress.resume(chat_id)
        k = await message.reply_text(lang["resumed"])
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["stop", "leave"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def leave_vc(_, message: Message, lang):
    chat_id = message.chat.id
    set_group(chat_id, is_playing=False, now_playing=None)
    await set_title(message, "")
    clear_queue(chat_id)
    try:
        await calls_for(chat_id).leave_call(chat_id)
        k = await message.reply_text(lang["leaveVC"])
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["list", "queue"], config.PREFIXES) & ~filters.private
)
@register
@language
@handle_error
async def queue_list(_, message: Message, lang):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if len(queue) > 0:
        k = await message.reply_text(str(queue), disable_web_page_preview=True)
    else:
        k = await message.reply_text(lang["queueEmpty"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["mix", "shuffle"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def shuffle_list(_, message: Message, lang):
    chat_id = message.chat.id
    if len(get_queue(chat_id)) > 0:
        shuffled = shuffle_queue(chat_id)
        k = await message.reply_text(str(shuffled), disable_web_page_preview=True)
    else:
        k = await message.reply_text(lang["queueEmpty"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["loop", "repeat"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def loop_stream(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["loop"]:
        set_group(chat_id, loop=False)
        k = await message.reply_text(lang["loopMode"] % "Disabled")
    elif group["loop"] == False:
        set_group(chat_id, loop=True)
        k = await message.reply_text(lang["loopMode"] % "Enabled")
    await delete_messages([message, k])


@client.on_message(
    filters.command(["mode", "switch"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def switch_mode(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["stream_mode"] == "audio":
        set_group(chat_id, stream_mode="video")
        k = await message.reply_text(lang["videoMode"])
    else:
        set_group(chat_id, stream_mode="audio")
        k = await message.reply_text(lang["audioMode"])
    await delete_messages([message, k])


@client.on_message(
    filters.command(["admins", "adminsonly"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def admins_only(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        set_group(chat_id, admins_only=False)
        k = await message.reply_text(lang["adminsOnly"] % "Disabled")
    else:
        set_group(chat_id, admins_only=True)
        k = await message.reply_text(lang["adminsOnly"] % "Enabled")
    await delete_messages([message, k])


@client.on_message(
    filters.command(["lang", "language"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def set_lang(_, message: Message, lang):
    chat_id = message.chat.id
    lng = extract_args(message.text)
    if lng != "":
        langs = [
            file.replace(".json", "")
            for file in os.listdir(f"{os.getcwd()}/lang/")
            if file.endswith(".json")
        ]
        if lng == "list":
            k = await message.reply_text("\n".join(langs))
        elif lng in langs:
            set_group(chat_id, lang=lng)
            k = await message.reply_text(lang["langSet"] % lng)
        else:
            k = await message.reply_text(lang["notFound"])
        await delete_messages([message, k])


@client.on_message(
    filters.command(["ep", "export"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def export_queue(_, message: Message, lang):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if len(queue) > 0:
        data = json.dumps([song.to_dict() for song in queue], indent=2)
        filename = f"{message.chat.username or message.chat.id}.json"
        with open(filename, "w") as file:
            file.write(data)
        await message.reply_document(
            filename, caption=lang["queueExported"] % len(queue)
        )
        os.remove(filename)
        await delete_messages([message])
    else:
        k = await message.reply_text(lang["queueEmpty"])
        await delete_messages([message, k])


@client.on_message(
    filters.command(["ip", "import"], config.PREFIXES) & ~filters.private
)
@register
@language
@only_admins
@handle_error
async def import_queue(_, message: Message, lang):
    if not message.reply_to_message or not message.reply_to_message.document:
        k = await message.reply_text(lang["replyToAFile"])
        return await delete_messages([message, k])
    chat_id = message.chat.id
    filename = await message.reply_to_message.download()
    data_str = None
    with open(filename, "r") as file:
        data_str = file.read()
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        k = await message.reply_text(lang["invalidFile"])
        return await delete_messages([message, k])
    try:
        temp_queue = []
        for song_dict in data:
            song = Song(song_dict["source"], message)
            song.title = song_dict["title"]
            temp_queue.append(song)
    except BaseException:
        k = await message.reply_text(lang["invalidFile"])
        return await delete_messages([message, k])
    if not temp_queue:
        k = await message.reply_text(lang["queueEmpty"])
        return await delete_messages([message, k])
    group = get_group(chat_id)
    queue = get_queue(chat_id)
    if group["is_playing"]:
        for _song in temp_queue:
            await queue.put(_song)
    else:
        song = temp_queue[0]
        ok, status = await song.parse()
        if not ok:
            raise Exception(status)
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        for _song in temp_queue[1:]:
            await queue.put(_song)
    k = await message.reply_text(lang["queueImported"] % len(temp_queue))
    await delete_messages([message, k])


@client.on_message(
    filters.command(["pl", "playlist"], config.PREFIXES) & ~filters.private
)
@register
@language
@handle_error
async def import_playlist(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"])
            return await delete_messages([message, k])
    if message.reply_to_message:
        text = message.reply_to_message.text
    else:
        text = extract_args(message.text)
    if text == "":
        k = await message.reply_text(lang["notFound"])
        return await delete_messages([message, k])
    if "youtube.com/playlist?list=" in text:
        try:
            temp_queue = get_youtube_playlist(text, message)
        except BaseException:
            k = await message.reply_text(lang["notFound"])
            return await delete_messages([message, k])
    elif "open.spotify.com/playlist/" in text:
        if not config.SPOTIFY:
            k = await message.reply_text(lang["spotifyNotEnabled"])
            return await delete_messages([message, k])
        try:
            temp_queue = get_spotify_playlist(text, message)
        except BaseException:
            k = await message.reply_text(lang["notFound"])
            return await delete_messages([message, k])
    else:
        k = await message.reply_text(lang["invalidFile"])
        return await delete_messages([message, k])
    queue = get_queue(chat_id)
    if not group["is_playing"]:
        try:
            song = await temp_queue.__anext__()
        except StopAsyncIteration:
            k = await message.reply_text(lang["queueEmpty"])
            return await delete_messages([message, k])
        ok, status = await song.parse()
        if not ok:
            raise Exception(status)
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        async for _song in temp_queue:
            await queue.put(_song)
    else:
        async for _song in temp_queue:
            await queue.put(_song)
    k = await message.reply_text(lang["queueImported"] % len(group["queue"]))
    await delete_messages([message, k])


@client.on_message(
    filters.command(["update", "restart"], config.PREFIXES) & ~filters.private
)
@language
@handle_error
async def update_restart(_, message: Message, lang):
    check = await is_sudo(message)
    if not check:
        k = await message.reply_text(lang["notAllowed"])
        return await delete_messages([message, k])
    chats = all_groups()
    stats = await message.reply_text(lang["update"])
    for chat in chats:
        try:
            await calls_for(chat).leave_call(chat)
        except (NoActiveGroupCall, NotInCallError):
            pass
    await stats.edit_text(lang["restart"])
    shutil.rmtree("downloads", ignore_errors=True)
    os.execv("/bin/bash", ["bash", "startup.sh"])


_autoplay_busy = set()  # chat ids with an autoplay lookup in flight


def _song_key(value):
    return str(value or "").strip().casefold()


def _first_artist(artists):
    for part in str(artists or "").replace("&", ",").split(","):
        if part.strip():
            return part.strip()
    return ""


async def _autoplay_candidates(current, history):
    """Related tracks that were not played recently, best matches first."""
    from ogmusic.providers import service
    artists = str(getattr(current, "artists", "") or "").strip()
    title = str(current.title or "").strip()
    first = _first_artist(artists)
    queries = [q for q in (artists, first, title, f"{first} songs" if first else "") if q]
    found, seen = [], set()
    for query in dict.fromkeys(queries):
        try:
            tracks = await service.search(query, limit=10)
        except Exception:
            continue
        for track in tracks:
            keys = {_song_key(track.title), _song_key(track.source_url)} - {""}
            if keys & history or keys & seen:
                continue
            seen |= keys
            found.append(track)
        if len(found) >= 6:
            break
    return found


async def _autoplay_next(chat_id, current, lang):
    """Keep playing related tracks for as long as autoplay is ON.

    True  = handled (do not run end-of-stream cleanup).
    False = nothing could be started at all; caller falls back to the normal ending.
    Autoplay itself is never switched off here: only the user's button does that.
    """
    group = get_group(chat_id)
    history = group.setdefault("autoplay_history", [])
    for key in (_song_key(current.title), _song_key(current.source)):
        if key and key not in history:
            history.append(key)

    def still_wanted():
        g = get_group(chat_id)
        return bool(g.get("autoplay")) and g.get("now_playing") is current and bool(g.get("is_playing"))

    candidates = await _autoplay_candidates(current, set(history))
    if not candidates:
        # Everything related was already played: forget the old history (keep only
        # the song that just ended) so the loop never dries up.
        current_keys = [k for k in (_song_key(current.title), _song_key(current.source)) if k]
        history[:] = current_keys
        candidates = await _autoplay_candidates(current, set(history))
    if not still_wanted():  # stop/skip/autoplay-off/new song while we were searching
        return True

    queue = get_queue(chat_id)
    if len(queue) > 0:  # something was queued meanwhile: queue always wins
        song = await queue.get()
        if not song.parsed:
            ok, status = await song.parse()
            if not ok:
                raise Exception(status)
        set_group(chat_id, now_playing=song)
        await start_stream(song, lang)
        return True

    attempts = [_track_song(t, current.request_msg, current.requested_by) for t in candidates[:3]]
    attempts.append(current)  # last resort: replay the song so playback never just dies
    for song in attempts:
        if not get_group(chat_id).get("autoplay"):
            return True
        set_group(chat_id, now_playing=song, is_playing=True)
        try:
            await start_stream(song, lang)
        except Exception:
            # start_stream rolled the chat state back; restore it and try the next one.
            set_group(chat_id, now_playing=current, is_playing=True)
            continue
        if song is not current:
            for key in (_song_key(song.title), _song_key(song.source)):
                if key:
                    history.append(key)
            del history[:-40]
        return True
    set_group(chat_id, now_playing=current, is_playing=True)
    return False


@language
@handle_error
async def stream_end(_, update: Update, lang):
    if isinstance(update, StreamEnded):
        chat_id = update.chat_id
        if chat_id in _autoplay_busy:  # duplicate end event while one is handled
            return
        group = get_group(chat_id)
        if group["loop"]:
            await start_stream(group["now_playing"], lang)
        else:
            queue = get_queue(chat_id)
            if len(queue) > 0:
                next_song = await queue.get()
                if not next_song.parsed:
                    ok, status = await next_song.parse()
                    if not ok:
                        raise Exception(status)
                set_group(chat_id, now_playing=next_song)
                await start_stream(next_song, lang)
            else:
                current = group.get("now_playing")
                if group.get("autoplay") and current is not None:
                    _autoplay_busy.add(chat_id)
                    try:
                        if await _autoplay_next(chat_id, current, lang):
                            return
                    except Exception as exc:
                        import logging
                        logging.getLogger("ogmusic").warning("autoplay failed (%s)", type(exc).__name__)
                    finally:
                        _autoplay_busy.discard(chat_id)
                    # Autoplay stays ON; only the user's button switches it off.
                    try:
                        from core.premium import send_text
                        from core.fonts import sc
                        from pyrogram import enums
                        await send_text(current.request_msg,
                                        f"⚠️ <b>{sc('autoplay could not find the next song')}</b>\n"
                                        f"<blockquote>{sc('autoplay is still on · play any song to continue the loop.')}</blockquote>",
                                        quote=False, parse_mode=enums.ParseMode.HTML)
                    except Exception:
                        pass
                if safone.get(chat_id) is not None:
                    try:
                        await safone[chat_id].delete()
                    except BaseException:
                        pass
                await set_title(chat_id, "", client=app_for(chat_id))
                set_group(chat_id, is_playing=False, now_playing=None)
                try:
                    await calls_for(chat_id).leave_call(chat_id)
                except (NoActiveGroupCall, NotInCallError):
                    pass


@handle_error
async def closed_vc(_, update: Update):
    chat_id = update.chat_id
    if chat_id in all_groups():
        if safone.get(chat_id) is not None:
            try:
                await safone[chat_id].delete()
            except BaseException:
                pass
        await set_title(chat_id, "", client=app_for(chat_id))
        set_group(chat_id, now_playing=None, is_playing=False)
        clear_queue(chat_id)


def setup_command_menu():
    """Fill Telegram's '/' command menu so users can tap /play, /search, ..."""
    from pyrogram.types import BotCommand, BotCommandScopeChat
    base = [
        ("start", "ꜱᴛᴀʀᴛ ᴍᴀʜɪ ᴍᴜꜱɪᴄ"),
        ("help", "ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ & ɢᴜɪᴅᴇ"),
        ("play", "ᴘʟᴀʏ ᴀ ꜱᴏɴɢ ɪɴ ᴠᴏɪᴄᴇ ᴄʜᴀᴛ"),
        ("search", "ꜱᴇᴀʀᴄʜ ᴛʀᴀᴄᴋꜱ ᴡɪᴛʜ ʙᴜᴛᴛᴏɴꜱ"),
        ("song", "ᴅᴏᴡɴʟᴏᴀᴅ ᴀ ꜱᴏɴɢ ᴀꜱ ᴀᴜᴅɪᴏ"),
        ("pause", "ᴘᴀᴜꜱᴇ ᴛʜᴇ ꜱᴛʀᴇᴀᴍ"),
        ("resume", "ʀᴇꜱᴜᴍᴇ ᴛʜᴇ ꜱᴛʀᴇᴀᴍ"),
        ("skip", "ꜱᴋɪᴘ ᴛᴏ ɴᴇxᴛ ᴛʀᴀᴄᴋ"),
        ("stop", "ꜱᴛᴏᴘ & ᴄʟᴇᴀʀ ǫᴜᴇᴜᴇ"),
        ("queue", "ꜱʜᴏᴡ ᴛʜᴇ ǫᴜᴇᴜᴇ"),
        ("loop", "ᴛᴏɢɢʟᴇ ʀᴇᴘᴇᴀᴛ"),
        ("shuffle", "ꜱʜᴜꜰꜰʟᴇ ᴛʜᴇ ǫᴜᴇᴜᴇ"),
        ("mute", "ᴍᴜᴛᴇ ᴛʜᴇ ꜱᴛʀᴇᴀᴍ"),
        ("unmute", "ᴜɴᴍᴜᴛᴇ ᴛʜᴇ ꜱᴛʀᴇᴀᴍ"),
        ("radio", "ᴘʟᴀʏ ᴀ ʟɪᴠᴇ ʀᴀᴅɪᴏ ᴜʀʟ"),
        ("playlist", "ǫᴜᴇᴜᴇ ᴀ ʏᴏᴜᴛᴜʙᴇ ᴘʟᴀʏʟɪꜱᴛ"),
        ("admin", "ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ ᴘᴀɴᴇʟ"),
        ("assistant", "ᴡʜɪᴄʜ ᴀꜱꜱɪꜱᴛᴀɴᴛ ꜱᴇʀᴠᴇꜱ ᴛʜɪꜱ ɢʀᴏᴜᴘ"),
        ("ping", "ᴄʜᴇᴄᴋ ʙᴏᴛ ꜱᴘᴇᴇᴅ"),
    ]
    client.set_bot_commands([BotCommand(c, d) for c, d in base])
    for uid in config.SUDOERS:
        try:
            owner = base + [("owner", "ᴏᴡɴᴇʀ ᴘᴀɴᴇʟ"), ("stats", "ʙᴏᴛ & ꜱʏꜱᴛᴇᴍ ꜱᴛᴀᴛꜱ"),
                            ("active", "ᴀᴄᴛɪᴠᴇ ᴠᴏɪᴄᴇ ᴄʜᴀᴛꜱ"), ("groups", "ᴀʟʟ ꜱᴇʀᴠᴇᴅ ɢʀᴏᴜᴘꜱ"),
                            ("assistants", "ᴍᴀɴᴀɢᴇ ᴀꜱꜱɪꜱᴛᴀɴᴛꜱ"), ("broadcast", "ꜱᴇɴᴅ ᴀ ʙʀᴏᴀᴅᴄᴀꜱᴛ"),
                            ("maintenance", "ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ")]
            client.set_bot_commands([BotCommand(c, d) for c, d in owner], scope=BotCommandScopeChat(chat_id=uid))
        except Exception:
            pass  # owner has not opened the bot yet; they get the normal list


add_update_handler(None, stream_end)
add_update_handler(fl.chat_update(ChatUpdate.Status.LEFT_CALL), closed_vc)


if __name__ == "__main__":
    client.start()
    if config.BOT_TOKEN:
        try:
            setup_command_menu()
        except Exception as exc:
            print("WARNING: could not set the command menu:", type(exc).__name__)
    from core import assistants as _assistants
    _assistants.boot_saved()
    pytgcalls.run()
