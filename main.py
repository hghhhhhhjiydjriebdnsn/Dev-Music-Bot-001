"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import os
import sys
import json
import asyncio
import shutil
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pytgcalls import filters as fl
from pytgcalls.types import Update, ChatUpdate
from pytgcalls.types.stream import StreamEnded
from pytgcalls.exceptions import NotInCallError, NoActiveGroupCall

from config import config
from core.song import Song
from core.decorators import language, register, only_admins, handle_error
from core import (
    app, ytdl, safone, search, is_sudo, is_admin, get_group, get_queue,
    pytgcalls, set_group, set_title, all_groups, clear_queue, check_yt_url,
    extract_args, start_stream, shuffle_queue, delete_messages,
    get_spotify_playlist, get_youtube_playlist,
)

log = logging.getLogger("main")

HTML = enums.ParseMode.HTML

REPO = (
    "🤖 <b>Music Player</b>\n\n"
    "• <b>Developer:</b> <a href=\"https://t.me/DevXGhost\">DevXGhost</a>\n"
    "• <b>Repository:</b> <a href=\"https://github.com/DevXGhost\">GitHub</a>\n"
    "• <b>License:</b> AGPL-3.0-or-later"
)

# ============================================================
#  CLIENT SELECTION
# ============================================================
bot = None
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


# ============================================================
#  HELPERS
# ============================================================
def _queue_full(lang: dict) -> str:
    return lang.get("queueFull", "⚠️ <b>Queue is full!</b> Try skipping some songs.")


async def _add_to_queue(chat_id: int, song: Song, lang: dict, message: Message):
    """Try to add song to queue; returns reply message."""
    queue = get_queue(chat_id)
    try:
        queue.put_nowait(song)
        return await message.reply_text(
            lang["addedToQueue"] % (song.source, song.title, len(queue)),
            parse_mode=HTML,
            disable_web_page_preview=True,
        )
    except asyncio.QueueFull:
        return await message.reply_text(_queue_full(lang), parse_mode=HTML)


# ============================================================
#  BASIC COMMANDS
# ============================================================
@client.on_message(filters.command("repo", config.PREFIXES) & ~filters.bot)
@handle_error
async def repo_cmd(_, message: Message):
    await message.reply_text(REPO, parse_mode=HTML, disable_web_page_preview=True)


@client.on_message(filters.command("ping", config.PREFIXES) & ~filters.bot)
@handle_error
async def ping_cmd(_, message: Message):
    try:
        ping_ms = round(pytgcalls.ping, 2)
    except Exception:
        ping_ms = "N/A"
    await message.reply_text(
        f"🤖 <b>Pong!</b>\n<code>{ping_ms} ms</code>",
        parse_mode=HTML,
    )


@client.on_message(filters.command("start", config.PREFIXES) & ~filters.bot)
@handle_error
@language
async def start_cmd(_, message: Message, lang):
    try:
        text = lang["startText"] % message.from_user.mention
    except (KeyError, TypeError):
        text = "👋 <b>Hello!</b>"
    await message.reply_text(
        text,
        parse_mode=HTML,
        disable_web_page_preview=True,
    )


@client.on_message(filters.command("help", config.PREFIXES) & ~filters.bot)
@handle_error
@language
async def help_cmd(_, message: Message, lang):
    try:
        text = lang["helpText"].replace("<prefix>", config.PREFIXES[0])
    except (KeyError, TypeError):
        text = "🤖 <b>Commands unavailable.</b>"
    await message.reply_text(
        text,
        parse_mode=HTML,
        disable_web_page_preview=True,
    )


# ============================================================
#  PLAY
# ============================================================
@client.on_message(filters.command(["p", "play"], config.PREFIXES) & ~filters.private)
@handle_error
@register
@language
async def play_stream(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)

    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"], parse_mode=HTML)
            return await delete_messages([message, k])

    try:
        song = await search(message)
    except Exception as e:
        log.exception("Search failed")
        k = await message.reply_text(
            f"⚠️ <b>Search error:</b> <code>{e}</code>", parse_mode=HTML
        )
        return await delete_messages([message, k])

    if song is None:
        k = await message.reply_text(lang["notFound"], parse_mode=HTML)
        return await delete_messages([message, k])

    ok, status = await song.parse()
    if not ok:
        raise RuntimeError(f"Parse failed: {status}")

    if not group["is_playing"]:
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        await delete_messages([message])
    else:
        k = await _add_to_queue(chat_id, song, lang, message)
        await delete_messages([message, k])


# ============================================================
#  RADIO / LIVE STREAM
# ============================================================
@client.on_message(
    filters.command(["radio", "stream"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
async def live_stream(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)

    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"], parse_mode=HTML)
            return await delete_messages([message, k])

    args = extract_args(message.text or "")
    if not args:
        k = await message.reply_text(lang["notFound"], parse_mode=HTML)
        return await delete_messages([message, k])

    if " " in args and args.count(" ") == 1 and args.endswith("parse"):
        song = Song({"source": args.split(" ")[0], "parsed": False}, message)
    else:
        is_yt_url, url = check_yt_url(args)
        if is_yt_url:
            meta = ytdl.extract_info(url, download=False)
            formats = meta.get("formats", [meta])
            stream_url = formats[-1]["url"]
            song = Song(
                {"title": "YouTube Stream", "source": stream_url, "remote": stream_url},
                message,
            )
        else:
            song = Song(
                {"title": "Live Stream", "source": args, "remote": args}, message
            )

    ok, status = await song.parse()
    if not ok:
        raise RuntimeError(f"Stream parse failed: {status}")

    if not group["is_playing"]:
        set_group(chat_id, is_playing=True, now_playing=song)
        await start_stream(song, lang)
        await delete_messages([message])
    else:
        k = await _add_to_queue(chat_id, song, lang, message)
        await delete_messages([message, k])


# ============================================================
#  SKIP / NEXT
# ============================================================
@client.on_message(
    filters.command(["skip", "next"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def skip_track(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)

    if group["loop"]:
        await start_stream(group["now_playing"], lang)
        return

    queue = get_queue(chat_id)
    if len(queue) > 0:
        next_song = queue.get_nowait()
        if not next_song.parsed:
            ok, status = await next_song.parse()
            if not ok:
                raise RuntimeError(f"Parse failed: {status}")
        set_group(chat_id, now_playing=next_song)
        await start_stream(next_song, lang)
        await delete_messages([message])
    else:
        set_group(chat_id, is_playing=False, now_playing=None)
        await set_title(message, "")
        try:
            await pytgcalls.leave_call(chat_id)
            k = await message.reply_text(lang["queueEmpty"], parse_mode=HTML)
        except (NoActiveGroupCall, NotInCallError):
            k = await message.reply_text(lang["notActive"], parse_mode=HTML)
        await delete_messages([message, k])


# ============================================================
#  MUTE / UNMUTE
# ============================================================
@client.on_message(filters.command(["m", "mute"], config.PREFIXES) & ~filters.private)
@handle_error
@register
@language
@only_admins
async def mute_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.mute_stream(chat_id)
        k = await message.reply_text(lang["muted"], parse_mode=HTML)
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"], parse_mode=HTML)
    await delete_messages([message, k])


@client.on_message(
    filters.command(["um", "unmute"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def unmute_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.unmute_stream(chat_id)
        k = await message.reply_text(lang["unmuted"], parse_mode=HTML)
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"], parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  PAUSE / RESUME
# ============================================================
@client.on_message(filters.command(["ps", "pause"], config.PREFIXES) & ~filters.private)
@handle_error
@register
@language
@only_admins
async def pause_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.pause_stream(chat_id)
        k = await message.reply_text(lang["paused"], parse_mode=HTML)
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"], parse_mode=HTML)
    await delete_messages([message, k])


@client.on_message(
    filters.command(["rs", "resume"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def resume_vc(_, message: Message, lang):
    chat_id = message.chat.id
    try:
        await pytgcalls.resume_stream(chat_id)
        k = await message.reply_text(lang["resumed"], parse_mode=HTML)
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"], parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  STOP / LEAVE
# ============================================================
@client.on_message(
    filters.command(["stop", "leave"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def leave_vc(_, message: Message, lang):
    chat_id = message.chat.id
    set_group(chat_id, is_playing=False, now_playing=None)
    await set_title(message, "")
    clear_queue(chat_id)
    try:
        await pytgcalls.leave_call(chat_id)
        k = await message.reply_text(lang["leaveVC"], parse_mode=HTML)
    except (NoActiveGroupCall, NotInCallError):
        k = await message.reply_text(lang["notActive"], parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  QUEUE
# ============================================================
@client.on_message(
    filters.command(["list", "queue"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
async def queue_list(_, message: Message, lang):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if len(queue) > 0:
        k = await message.reply_text(
            str(queue),
            parse_mode=HTML,
            disable_web_page_preview=True,
        )
    else:
        k = await message.reply_text(lang["queueEmpty"], parse_mode=HTML)
    await delete_messages([message, k])


@client.on_message(
    filters.command(["mix", "shuffle"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def shuffle_list(_, message: Message, lang):
    chat_id = message.chat.id
    if len(get_queue(chat_id)) > 0:
        shuffled = shuffle_queue(chat_id)
        k = await message.reply_text(
            str(shuffled),
            parse_mode=HTML,
            disable_web_page_preview=True,
        )
    else:
        k = await message.reply_text(lang["queueEmpty"], parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  LOOP
# ============================================================
@client.on_message(
    filters.command(["loop", "repeat"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def loop_stream(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["loop"]:
        set_group(chat_id, loop=False)
        k = await message.reply_text(lang["loopMode"] % "Disabled", parse_mode=HTML)
    else:
        set_group(chat_id, loop=True)
        k = await message.reply_text(lang["loopMode"] % "Enabled", parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  MODE (audio/video)
# ============================================================
@client.on_message(
    filters.command(["mode", "switch"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def switch_mode(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["stream_mode"] == "audio":
        set_group(chat_id, stream_mode="video")
        k = await message.reply_text(lang["videoMode"], parse_mode=HTML)
    else:
        set_group(chat_id, stream_mode="audio")
        k = await message.reply_text(lang["audioMode"], parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  ADMINS ONLY
# ============================================================
@client.on_message(
    filters.command(["admins", "adminsonly"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def admins_only_cmd(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)
    if group["admins_only"]:
        set_group(chat_id, admins_only=False)
        k = await message.reply_text(lang["adminsOnly"] % "Disabled", parse_mode=HTML)
    else:
        set_group(chat_id, admins_only=True)
        k = await message.reply_text(lang["adminsOnly"] % "Enabled", parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  LANGUAGE
# ============================================================
@client.on_message(
    filters.command(["lang", "language"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def set_lang(_, message: Message, lang):
    from lang import available_languages

    chat_id = message.chat.id
    lng = extract_args(message.text or "")
    if not lng:
        return

    langs = available_languages()
    if lng == "list":
        k = await message.reply_text("\n".join(langs), parse_mode=HTML)
    elif lng in langs:
        set_group(chat_id, lang=lng)
        k = await message.reply_text(lang["langSet"] % lng, parse_mode=HTML)
    else:
        k = await message.reply_text(lang["notFound"], parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  QUEUE EXPORT / IMPORT
# ============================================================
@client.on_message(
    filters.command(["ep", "export"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def export_queue(_, message: Message, lang):
    chat_id = message.chat.id
    queue = get_queue(chat_id)
    if len(queue) == 0:
        k = await message.reply_text(lang["queueEmpty"], parse_mode=HTML)
        return await delete_messages([message, k])

    data = json.dumps([song.to_dict() for song in queue.to_list()], indent=2)
    filename = f"{message.chat.username or message.chat.id}.json"
    try:
        with open(filename, "w", encoding="utf-8") as file:
            file.write(data)
        await message.reply_document(
            filename,
            caption=lang["queueExported"] % len(queue),
            parse_mode=HTML,
        )
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass
    await delete_messages([message])


@client.on_message(
    filters.command(["ip", "import"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
@only_admins
async def import_queue(_, message: Message, lang):
    if not message.reply_to_message or not message.reply_to_message.document:
        k = await message.reply_text(lang["replyToAFile"], parse_mode=HTML)
        return await delete_messages([message, k])

    chat_id = message.chat.id
    filename = await message.reply_to_message.download()
    try:
        with open(filename, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        k = await message.reply_text(lang["invalidFile"], parse_mode=HTML)
        return await delete_messages([message, k])
    finally:
        try:
            os.remove(filename)
        except OSError:
            pass

    temp_queue = []
    try:
        for song_dict in data:
            if "source" not in song_dict:
                raise ValueError("Missing source")
            s = Song(song_dict["source"], message)
            s.title = song_dict.get("title", "Unknown")
            temp_queue.append(s)
    except Exception:
        k = await message.reply_text(lang["invalidFile"], parse_mode=HTML)
        return await delete_messages([message, k])

    if not temp_queue:
        k = await message.reply_text(lang["queueEmpty"], parse_mode=HTML)
        return await delete_messages([message, k])

    group = get_group(chat_id)
    queue = get_queue(chat_id)
    if group["is_playing"]:
        for s in temp_queue:
            try:
                queue.put_nowait(s)
            except asyncio.QueueFull:
                break
    else:
        song = temp_queue[0]
        set_group(chat_id, is_playing=True, now_playing=song)
        ok, status = await song.parse()
        if not ok:
            raise RuntimeError(f"Parse failed: {status}")
        await start_stream(song, lang)
        for s in temp_queue[1:]:
            try:
                queue.put_nowait(s)
            except asyncio.QueueFull:
                break

    k = await message.reply_text(
        lang["queueImported"] % len(temp_queue), parse_mode=HTML
    )
    await delete_messages([message, k])


# ============================================================
#  PLAYLIST IMPORT
# ============================================================
@client.on_message(
    filters.command(["pl", "playlist"], config.PREFIXES) & ~filters.private
)
@handle_error
@register
@language
async def import_playlist(_, message: Message, lang):
    chat_id = message.chat.id
    group = get_group(chat_id)

    if group["admins_only"]:
        check = await is_admin(message)
        if not check:
            k = await message.reply_text(lang["notAllowed"], parse_mode=HTML)
            return await delete_messages([message, k])

    text = (
        message.reply_to_message.text
        if message.reply_to_message
        else extract_args(message.text or "")
    )
    if not text:
        k = await message.reply_text(lang["notFound"], parse_mode=HTML)
        return await delete_messages([message, k])

    try:
        if "youtube.com/playlist?list=" in text:
            temp_queue = get_youtube_playlist(text, message)
        elif "open.spotify.com/playlist/" in text:
            if not config.SPOTIFY:
                k = await message.reply_text(
                    lang["spotifyNotEnabled"], parse_mode=HTML
                )
                return await delete_messages([message, k])
            temp_queue = get_spotify_playlist(text, message)
        else:
            k = await message.reply_text(lang["invalidFile"], parse_mode=HTML)
            return await delete_messages([message, k])
    except Exception:
        k = await message.reply_text(lang["notFound"], parse_mode=HTML)
        return await delete_messages([message, k])

    queue = get_queue(chat_id)
    count = 0
    if not group["is_playing"]:
        try:
            song = await temp_queue.__anext__()
        except StopAsyncIteration:
            k = await message.reply_text(lang["queueEmpty"], parse_mode=HTML)
            return await delete_messages([message, k])
        set_group(chat_id, is_playing=True, now_playing=song)
        ok, status = await song.parse()
        if not ok:
            raise RuntimeError(f"Parse failed: {status}")
        await start_stream(song, lang)
        count += 1
        async for s in temp_queue:
            try:
                queue.put_nowait(s)
                count += 1
            except asyncio.QueueFull:
                break
    else:
        async for s in temp_queue:
            try:
                queue.put_nowait(s)
                count += 1
            except asyncio.QueueFull:
                break

    k = await message.reply_text(lang["queueImported"] % count, parse_mode=HTML)
    await delete_messages([message, k])


# ============================================================
#  UPDATE / RESTART
# ============================================================
@client.on_message(
    filters.command(["update", "restart"], config.PREFIXES) & ~filters.private
)
@handle_error
@language
async def update_restart(_, message: Message, lang):
    check = await is_sudo(message)
    if not check:
        k = await message.reply_text(lang["notAllowed"], parse_mode=HTML)
        return await delete_messages([message, k])

    stats = await message.reply_text(lang["update"], parse_mode=HTML)
    for chat in all_groups():
        try:
            await pytgcalls.leave_call(chat)
        except (NoActiveGroupCall, NotInCallError):
            pass

    await stats.edit_text(lang["restart"], parse_mode=HTML)
    shutil.rmtree("downloads", ignore_errors=True)
    os.execv(sys.executable, [sys.executable, "main.py"])


# ============================================================
#  STREAM END HANDLER
# ============================================================
@pytgcalls.on_update()
@handle_error
async def stream_end(_, update: Update):
    if not isinstance(update, StreamEnded):
        return

    chat_id = update.chat_id
    group = get_group(chat_id)
    lang = _get_lang_for_chat(chat_id)

    if group["loop"]:
        await start_stream(group["now_playing"], lang)
        return

    queue = get_queue(chat_id)
    if len(queue) > 0:
        next_song = queue.get_nowait()
        if not next_song.parsed:
            ok, status = await next_song.parse()
            if not ok:
                log.error(f"Parse failed: {status}")
                return
        set_group(chat_id, now_playing=next_song)
        await start_stream(next_song, lang)
    else:
        if safone.get(chat_id) is not None:
            try:
                await safone[chat_id].delete()
            except Exception:
                pass
        await set_title(chat_id, "", client=app)
        set_group(chat_id, is_playing=False, now_playing=None)
        try:
            await pytgcalls.leave_call(chat_id)
        except (NoActiveGroupCall, NotInCallError):
            pass


def _get_lang_for_chat(chat_id: int) -> dict:
    """Fetch language dict for a chat (safe fallback)."""
    try:
        from lang import load
        grp = get_group(chat_id)
        return load(grp.get("lang", config.LANGUAGE))
    except Exception:
        from lang import load
        return load(config.LANGUAGE)


# ============================================================
#  VC CLOSED HANDLER
# ============================================================
@pytgcalls.on_update(fl.chat_update(ChatUpdate.Status.LEFT_CALL))
@handle_error
async def closed_vc(_, update: Update):
    chat_id = update.chat_id
    if chat_id in all_groups():
        if safone.get(chat_id) is not None:
            try:
                await safone[chat_id].delete()
            except Exception:
                pass
        await set_title(chat_id, "", client=app)
        set_group(chat_id, now_playing=None, is_playing=False)
        clear_queue(chat_id)


# ============================================================
#  STARTUP
# ============================================================
async def main():
    log.info("Starting userbot...")
    await app.start()

    if bot is not None:
        log.info("Starting bot client...")
        await bot.start()
        me = await bot.get_me()
        log.info(f"Bot started: @{me.username}")

    log.info("Starting PyTgCalls...")
    await pytgcalls.start()

    log.info("🚀 Bot is running. Press Ctrl+C to stop.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutdown requested.")
    finally:
        log.info("Bye.")