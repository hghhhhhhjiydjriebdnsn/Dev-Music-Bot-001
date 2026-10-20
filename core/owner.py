"""Owner / sudo control panel for PIHU MUSIC.

Owners = the user IDs in SUDOERS from the environment (cannot be removed here).
Sudoers added with /addsudo are saved in the database and get the stats-type
tools. Everything is gated by user ID, never by name or username.
"""
import asyncio
import html
import os
import platform
import shutil
import time

from pyrogram import filters, enums, StopPropagation
from pyrogram import __version__ as PYROGRAM_VERSION
from pyrogram.errors import FloodWait
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

from config import config
from core import store
from core.fonts import sc, bold
from core.premium import edit_text, send_text

START_TIME = time.time()
PAGE = 8
BC = {"running": False, "cancel": False}
HTML = enums.ParseMode.HTML


def _h(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def is_owner(user):
    return bool(user) and user.id in config.OWNERS


def is_sudo(user):
    return bool(user) and user.id in config.SUDOERS


def card(icon, title, body=None, note=None):
    text = f"{icon} <b>{sc(title)}</b>"
    if body:
        text += f"\n<blockquote>{body}</blockquote>"
    if note:
        text += f"\n<i>{sc(note)}</i>"
    return text


def _uptime(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return (f"{d}d " if d else "") + f"{h}h {m}m {s}s"


def _size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def active_chats():
    from core.groups import GROUPS
    return [(cid, g) for cid, g in GROUPS.items() if g.get("is_playing")]


def system_info():
    info = {"python": platform.python_version(), "os": platform.system(), "uptime": _uptime(time.time() - START_TIME)}
    try:
        import psutil
        info["cpu"] = f"{psutil.cpu_percent(interval=0.2)}%"
        vm = psutil.virtual_memory()
        info["ram"] = f"{_size(vm.used)} / {_size(vm.total)} ({vm.percent}%)"
    except Exception:
        try:
            info["cpu"] = "load " + " ".join(f"{x:.2f}" for x in os.getloadavg())
        except Exception:
            info["cpu"] = "n/a"
        try:
            mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in open("/proc/meminfo") if ":" in l}
            used = mem["MemTotal"] - mem.get("MemAvailable", mem["MemFree"])
            info["ram"] = f"{_size(used)} / {_size(mem['MemTotal'])} ({used * 100 // mem['MemTotal']}%)"
        except Exception:
            info["ram"] = "n/a"
    try:
        du = shutil.disk_usage("/")
        info["disk"] = f"{_size(du.used)} / {_size(du.total)} ({du.used * 100 // du.total}%)"
    except Exception:
        info["disk"] = "n/a"
    try:
        info["db"] = _size(store.db_path().stat().st_size)
    except Exception:
        info["db"] = "n/a"
    return info


# ----------------------------------------------------------------- panels
def _nav(back=True):
    row = []
    if back:
        row.append(Btn("⬅️ " + sc("back"), callback_data="ogo:home"))
    row.append(Btn("✖ " + sc("close"), callback_data="ogo:close"))
    return row


def _home():
    from core import assistants
    text = (
        f"👑 <b>{bold('PIHU MUSIC')} — {sc('owner panel')}</b>\n\n"
        f"<blockquote>👤 {sc('users')} : <b>{store.count('users')}</b>\n"
        f"👥 {sc('groups')} : <b>{store.count('chats')}</b>\n"
        f"🎧 {sc('active voice chats')} : <b>{len(active_chats())}</b>\n"
        f"🤖 {sc('assistants')} : <b>{len(assistants.alive())}</b>\n"
        f"🛠 {sc('maintenance')} : <b>{sc('on' if store.get_setting('maintenance') else 'off')}</b></blockquote>\n"
        f"<i>{sc('pick a section below')}</i>"
    )
    kb = Kb([
        [Btn("📊 " + sc("stats"), callback_data="ogo:stats"), Btn("👥 " + sc("groups"), callback_data="ogo:groups:0")],
        [Btn("🎧 " + sc("active"), callback_data="ogo:active"), Btn("🤖 " + sc("assistants"), callback_data="ogo:assist")],
        [Btn("🛡️ " + sc("sudoers"), callback_data="ogo:sudo"), Btn("🚫 " + sc("blocklist"), callback_data="ogo:block")],
        [Btn("📣 " + sc("broadcast"), callback_data="ogo:bc"), Btn("🛠 " + sc("maintenance"), callback_data="ogo:maint")],
        [Btn("⚙️ " + sc("system"), callback_data="ogo:system"), Btn("📡 " + sc("logger"), callback_data="ogo:logger")],
        [Btn("🔄 " + sc("refresh"), callback_data="ogo:home"), Btn("✖ " + sc("close"), callback_data="ogo:close")],
    ])
    return text, kb


def _stats():
    from core import assistants
    body = (
        f"👤 {sc('users')} : <b>{store.count('users')}</b>\n"
        f"👥 {sc('groups')} : <b>{store.count('chats')}</b>\n"
        f"🎧 {sc('active voice chats')} : <b>{len(active_chats())}</b>\n"
        f"🤖 {sc('assistants')} : <b>{len(assistants.alive())}</b>\n"
        f"🛡️ {sc('sudoers')} : <b>{len(config.SUDOERS)}</b>\n"
        f"🚫 {sc('blocked')} : <b>{len(store.blocked_list('user'))}</b> {sc('users')} · "
        f"<b>{len(store.blocked_list('chat'))}</b> {sc('chats')}"
    )
    si = system_info()
    sysbody = (f"⏱ {sc('uptime')} : <code>{si['uptime']}</code>\n"
               f"🖥 {sc('cpu')} : <code>{si['cpu']}</code>\n"
               f"💾 {sc('ram')} : <code>{si['ram']}</code>\n"
               f"💿 {sc('disk')} : <code>{si['disk']}</code>")
    text = card("📊", "bot statistics", body) + "\n" + card("⚙️", "system", sysbody)
    return text, Kb([[Btn("🔄 " + sc("refresh"), callback_data="ogo:stats")], _nav()])


def _groups(page):
    total = store.count("chats")
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = store.chats_page(page * PAGE, PAGE)
    lines = [f"<b>{page * PAGE + i}.</b> {_h(t or 'Unknown')} · <code>{cid}</code>" for i, (cid, t) in enumerate(rows, 1)]
    body = "\n".join(lines) if lines else sc("no groups yet")
    text = card("👥", f"groups · {total}", body, f"page {page + 1}/{pages}")
    nav = []
    if page > 0:
        nav.append(Btn("◀️", callback_data=f"ogo:groups:{page - 1}"))
    if page < pages - 1:
        nav.append(Btn("▶️", callback_data=f"ogo:groups:{page + 1}"))
    kb = [nav] if nav else []
    kb.append(_nav())
    return text, Kb(kb)


def _active():
    rows = active_chats()
    lines = []
    for cid, g in rows[:15]:
        song = g.get("now_playing")
        title = _h(getattr(song, "title", "—"))
        lines.append(f"🎵 <b>{title}</b>\n    <code>{cid}</code>")
    body = "\n".join(lines) if lines else sc("nothing is playing right now")
    text = card("🎧", f"active voice chats · {len(rows)}", body)
    return text, Kb([[Btn("🔄 " + sc("refresh"), callback_data="ogo:active")], _nav()])


def _assistants_page():
    from core import assistants
    counts = store.assignment_counts()
    lines = []
    kb = []
    for a in assistants.ASSISTANTS:
        uname = f"@{_h(a.username)}" if a.username else "—"
        tag = sc("primary") if a.primary else sc("extra")
        lines.append(f"🤖 <b>{_h(a.name)}</b> · {uname}\n    <code>{a.user_id}</code> · {tag} · {counts.get(a.user_id, 0)} {sc('chats')}")
        if not a.primary:
            kb.append([Btn(f"🗑 {sc('remove')} {a.name[:18]}", callback_data=f"ogo:asrm:{a.user_id}")])
    body = "\n".join(lines) or sc("none")
    how = (f"\n\n<i>{sc('add more')} : </i><code>/addassistant SESSION_STRING</code>\n"
           f"<i>{sc('use a')} <b>pyrogram</b> {sc('string session of a normal user account.')}</i>")
    text = card("🤖", "assistants", body) + how
    kb.append(_nav())
    return text, Kb(kb)


def _sudo_page():
    owners = "\n".join(f'👑 <a href="tg://user?id={u}">{u}</a>' for u in config.OWNERS)
    extra = [u for u in store.sudo_ids()]
    sud = "\n".join(f'🛡️ <a href="tg://user?id={u}">{u}</a>' for u in extra) or sc("none")
    text = (card("👑", "owners", owners) + "\n" + card("🛡️", "sudoers", sud) +
            f"\n<i>{sc('manage')} : </i><code>/addsudo</code> · <code>/delsudo</code> · <code>/sudolist</code>")
    return text, Kb([_nav()])


def _block_page():
    users = store.blocked_list("user")
    chats = store.blocked_list("chat")
    ub = "\n".join(f"<code>{u}</code>" for u in users[:25]) or sc("none")
    cb = "\n".join(f"<code>{c}</code>" for c in chats[:25]) or sc("none")
    text = (card("🚫", f"blocked users · {len(users)}", ub) + "\n" + card("🚫", f"blocked chats · {len(chats)}", cb) +
            f"\n<i><code>/block</code> · <code>/unblock</code> · <code>/blockchat</code> · <code>/unblockchat</code></i>")
    return text, Kb([_nav()])


def _bc_page():
    body = (f"<code>/broadcast text</code> — {sc('send to every user & group')}\n"
            f"{sc('reply to any message with')} <code>/broadcast</code> — {sc('copy it to everyone')}\n"
            f"<code>-users</code> · <code>-groups</code> — {sc('limit the target')}\n"
            f"<code>-pin</code> — {sc('pin it in groups')}\n"
            f"<code>/broadcast -cancel</code> — {sc('stop a running broadcast')}")
    return card("📣", "broadcast", body), Kb([_nav()])


def _maint_page():
    on = bool(store.get_setting("maintenance"))
    reason = store.get_setting("maintenance_reason")
    body = f"{sc('status')} : <b>{sc('on') if on else sc('off')}</b>"
    if on and reason:
        body += f"\n{sc('reason')} : {_h(reason)}"
    text = card("🛠", "maintenance mode", body, "when on, only owners & sudoers can use commands")
    label = ("🟢 " + sc("turn off")) if on else ("🔴 " + sc("turn on"))
    return text, Kb([[Btn(label, callback_data="ogo:maint:toggle")], _nav()])


def _logger_page():
    on = bool(store.get_setting("logger"))
    text = card("📡", "logger", f"{sc('status')} : <b>{sc('on') if on else sc('off')}</b>",
                "owners get a message when the bot joins/leaves a group or a new user starts it")
    label = ("🟢 " + sc("turn off")) if on else ("🔴 " + sc("turn on"))
    return text, Kb([[Btn(label, callback_data="ogo:logger:toggle")], _nav()])


async def _system_page(client):
    si = system_info()
    t = time.perf_counter()
    try:
        await client.get_me()
        ping = f"{(time.perf_counter() - t) * 1000:.0f} ms"
    except Exception:
        ping = "n/a"
    body = (f"⏱ {sc('uptime')} : <code>{si['uptime']}</code>\n"
            f"🏓 {sc('api ping')} : <code>{ping}</code>\n"
            f"🖥 {sc('cpu')} : <code>{si['cpu']}</code>\n"
            f"💾 {sc('ram')} : <code>{si['ram']}</code>\n"
            f"💿 {sc('disk')} : <code>{si['disk']}</code>\n"
            f"🗃 {sc('database')} : <code>{si['db']}</code>\n"
            f"🐍 python : <code>{si['python']}</code> · pyrogram <code>{PYROGRAM_VERSION}</code>\n"
            f"🌐 {sc('os')} : <code>{si['os']}</code>")
    return card("⚙️", "system", body), Kb([[Btn("🔄 " + sc("refresh"), callback_data="ogo:system")], _nav()])


# ------------------------------------------------------------- notifications
async def notify(client, text):
    if not store.get_setting("logger"):
        return
    for uid in config.OWNERS:
        try:
            await send_text_to(client, uid, text)
        except Exception:
            pass


async def send_text_to(client, chat_id, text):
    from core.premium import decorate_html
    try:
        return await client.send_message(chat_id, decorate_html(text), parse_mode=HTML, disable_web_page_preview=True)
    except Exception:
        return await client.send_message(chat_id, text, parse_mode=HTML, disable_web_page_preview=True)


def _mention(user):
    if not user:
        return "—"
    return f'<a href="tg://user?id={user.id}">{_h(user.first_name)}</a> · <code>{user.id}</code>'


# -------------------------------------------------------------- registration
def register_owner(client):
    from pyrogram.types import BotCommand  # noqa: F401  (kept for parity with menu setup)
    config.OWNERS = tuple(config.SUDOERS)
    for uid in store.sudo_ids():
        if uid not in config.SUDOERS:
            config.SUDOERS.append(uid)

    prefixes = set("".join(config.PREFIXES))

    async def deny(message, owner=True):
        await message.reply_text(card("⛔", "owner only" if owner else "sudo only",
                                      note="you don't have access to this command."), parse_mode=HTML)

    def owner_only(fn):
        async def wrapper(c, m):
            if not is_owner(m.from_user):
                return await deny(m)
            return await fn(c, m)
        return wrapper

    def sudo_only(fn):
        async def wrapper(c, m):
            if not is_sudo(m.from_user):
                return await deny(m, owner=False)
            return await fn(c, m)
        return wrapper

    async def resolve_user(c, m, index=1):
        if m.reply_to_message and m.reply_to_message.from_user:
            return m.reply_to_message.from_user.id
        if len(m.command) > index:
            raw = m.command[index]
            if raw.lstrip("-").isdigit():
                return int(raw)
            try:
                return (await c.get_users(raw)).id
            except Exception:
                return None
        return None

    # ---- gate: blocklist + maintenance (runs before everything else)
    async def gate(c, message):
        user = message.from_user
        if is_sudo(user):
            return
        if user and store.is_blocked("user", user.id):
            raise StopPropagation
        if message.chat.type != enums.ChatType.PRIVATE and store.is_blocked("chat", message.chat.id):
            raise StopPropagation
        text = (message.text or "").lstrip()
        if store.get_setting("maintenance") and text[:1] in prefixes and text[:1]:
            reason = store.get_setting("maintenance_reason")
            await message.reply_text(card("🛠", "under maintenance",
                                          _h(reason) if reason else None,
                                          "i'll be back very soon. thanks for your patience!"), parse_mode=HTML)
            raise StopPropagation

    async def gate_cb(c, query):
        user = query.from_user
        if is_sudo(user):
            return
        if user and store.is_blocked("user", user.id):
            await query.answer("🚫 You are blocked from using this bot.", show_alert=True)
            raise StopPropagation
        if store.get_setting("maintenance"):
            await query.answer("🛠 Under maintenance. Please try again later.", show_alert=True)
            raise StopPropagation

    # ---- tracking
    async def track(c, message):
        try:
            if message.chat.type == enums.ChatType.PRIVATE and message.from_user and not message.from_user.is_bot:
                if store.add_user(message.from_user.id, message.from_user.first_name):
                    await notify(c, card("👤", "new user", f"{_mention(message.from_user)}"))
            elif message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
                store.add_chat(message.chat.id, message.chat.title)
        except Exception:
            pass

    async def bot_added(c, message):
        me_added = any(getattr(m, "is_self", False) for m in (message.new_chat_members or []))
        if not me_added:
            return
        chat = message.chat
        if store.is_blocked("chat", chat.id):
            try:
                await c.leave_chat(chat.id)
            except Exception:
                pass
            return
        new = store.add_chat(chat.id, chat.title)
        greeting = (
            f"🎵 <b>{bold('PIHU MUSIC')}</b> ✨\n"
            f"<blockquote>{sc('thanks for adding me! start a voice chat and send')} <code>/play song name</code>\n"
            f"{sc('make me admin for the best experience.')}</blockquote>"
        )
        try:
            await send_text_to(c, chat.id, greeting)
        except Exception:
            pass
        if new:
            await notify(c, card("➕", "added to a new group",
                                 f"💬 <b>{_h(chat.title)}</b>\n🆔 <code>{chat.id}</code>\n👤 {sc('by')} : {_mention(message.from_user)}"))

    async def bot_left(c, message):
        lm = message.left_chat_member
        if lm and getattr(lm, "is_self", False):
            store.forget("chats", message.chat.id)
            await notify(c, card("➖", "removed from a group", f"💬 <b>{_h(message.chat.title)}</b>\n🆔 <code>{message.chat.id}</code>"))

    # ---- panel
    async def show(message_or_query, text, kb):
        msg = getattr(message_or_query, "message", message_or_query)
        try:
            sent = await edit_text(msg, text, reply_markup=kb, parse_mode=HTML, disable_web_page_preview=True)
        except Exception:
            return None
        try:
            from core.ui import apply_button_style
            await apply_button_style(sent, kb)
        except Exception:
            pass
        return sent

    @owner_only
    async def owner_cmd(c, message):
        text, kb = _home()
        sent = await send_text(message, text, reply_markup=kb, parse_mode=HTML)
        try:
            from core.ui import apply_button_style
            await apply_button_style(sent, kb)
        except Exception:
            pass

    @sudo_only
    async def stats_cmd(c, message):
        text, kb = _stats()
        await send_text(message, text, reply_markup=kb, parse_mode=HTML)

    @sudo_only
    async def active_cmd(c, message):
        text, kb = _active()
        await send_text(message, text, reply_markup=kb, parse_mode=HTML)

    @sudo_only
    async def groups_cmd(c, message):
        page = int(message.command[1]) - 1 if len(message.command) > 1 and message.command[1].isdigit() else 0
        text, kb = _groups(page)
        await send_text(message, text, reply_markup=kb, parse_mode=HTML)

    async def owner_cb(c, query):
        if not is_owner(query.from_user):
            return await query.answer("Owner only.", show_alert=True)
        parts = query.data.split(":")
        action = parts[1]
        arg = parts[2] if len(parts) > 2 else None
        await query.answer()
        if action == "close":
            try:
                await query.message.delete()
            except Exception:
                pass
            return
        if action == "home":
            page = _home()
        elif action == "stats":
            page = _stats()
        elif action == "groups":
            page = _groups(int(arg or 0))
        elif action == "active":
            page = _active()
        elif action == "assist":
            page = _assistants_page()
        elif action == "asrm":
            page = (card("🗑", "remove assistant", f"<code>{_h(arg)}</code>", "its chats will move to another assistant. continue?"),
                    Kb([[Btn("✅ " + sc("yes, remove"), callback_data=f"ogo:asrmy:{arg}"), Btn("❌ " + sc("cancel"), callback_data="ogo:assist")]]))
        elif action == "asrmy":
            from core import assistants
            ok, err = await assistants.remove(int(arg))
            page = _assistants_page()
            if not ok:
                await query.answer(err or "failed", show_alert=True)
        elif action == "sudo":
            page = _sudo_page()
        elif action == "block":
            page = _block_page()
        elif action == "bc":
            page = _bc_page()
        elif action == "bccancel":
            BC["cancel"] = True
            return
        elif action == "maint":
            if arg == "toggle":
                if store.get_setting("maintenance"):
                    store.set_setting("maintenance", "")
                    store.set_setting("maintenance_reason", "")
                else:
                    store.set_setting("maintenance", "1")
            page = _maint_page()
        elif action == "logger":
            if arg == "toggle":
                store.set_setting("logger", "" if store.get_setting("logger") else "1")
            page = _logger_page()
        elif action == "system":
            page = await _system_page(c)
        else:
            return
        await show(query, *page)

    # ---- sudo / block / maintenance / logger commands
    @owner_only
    async def addsudo_cmd(c, message):
        uid = await resolve_user(c, message)
        if not uid:
            return await message.reply_text(card("⚠️", "who?", note="reply to a user or send /addsudo user_id"), parse_mode=HTML)
        if uid in config.OWNERS or uid in config.SUDOERS:
            return await message.reply_text(card("ℹ️", "already a sudoer"), parse_mode=HTML)
        store.add_sudo(uid)
        config.SUDOERS.append(uid)
        await message.reply_text(card("✅", "sudoer added", f'<a href="tg://user?id={uid}">{uid}</a>'), parse_mode=HTML)

    @owner_only
    async def delsudo_cmd(c, message):
        uid = await resolve_user(c, message)
        if not uid or uid in config.OWNERS or not store.del_sudo(uid):
            return await message.reply_text(card("⚠️", "not a removable sudoer", note="owners can't be removed here."), parse_mode=HTML)
        if uid in config.SUDOERS:
            config.SUDOERS.remove(uid)
        await message.reply_text(card("✅", "sudoer removed", f"<code>{uid}</code>"), parse_mode=HTML)

    @sudo_only
    async def sudolist_cmd(c, message):
        text, _ = _sudo_page()
        await message.reply_text(text, parse_mode=HTML)

    def block_cmds(kind, add):
        @owner_only
        async def handler(c, message):
            target = await resolve_user(c, message) if kind == "user" else (
                int(message.command[1]) if len(message.command) > 1 and message.command[1].lstrip("-").isdigit() else message.chat.id)
            if not target:
                return await message.reply_text(card("⚠️", "who?", note="reply to a user or pass an id."), parse_mode=HTML)
            if kind == "user" and (target in config.OWNERS or target in config.SUDOERS):
                return await message.reply_text(card("⚠️", "owners and sudoers can't be blocked"), parse_mode=HTML)
            changed = store.block(kind, target) if add else store.unblock(kind, target)
            title = (f"{kind} blocked" if add else f"{kind} unblocked") if changed else ("already blocked" if add else "was not blocked")
            await message.reply_text(card("🚫" if add else "✅", title, f"<code>{target}</code>"), parse_mode=HTML)
        return handler

    @sudo_only
    async def blacklisted_cmd(c, message):
        text, _ = _block_page()
        await message.reply_text(text, parse_mode=HTML)

    @owner_only
    async def maintenance_cmd(c, message):
        args = message.command[1:]
        if args and args[0].lower() in ("off", "disable", "0"):
            store.set_setting("maintenance", "")
            store.set_setting("maintenance_reason", "")
        elif args and args[0].lower() in ("on", "enable", "1"):
            store.set_setting("maintenance", "1")
            store.set_setting("maintenance_reason", " ".join(args[1:]))
        text, kb = _maint_page()
        await message.reply_text(text, reply_markup=kb, parse_mode=HTML)

    @owner_only
    async def logger_cmd(c, message):
        args = message.command[1:]
        if args and args[0].lower() in ("on", "enable", "1"):
            store.set_setting("logger", "1")
        elif args and args[0].lower() in ("off", "disable", "0"):
            store.set_setting("logger", "")
        text, kb = _logger_page()
        await message.reply_text(text, reply_markup=kb, parse_mode=HTML)

    @owner_only
    async def leave_cmd(c, message):
        target = int(message.command[1]) if len(message.command) > 1 and message.command[1].lstrip("-").isdigit() else message.chat.id
        try:
            await c.leave_chat(target)
            store.forget("chats", target)
            if target != message.chat.id:
                await message.reply_text(card("✅", "left the chat", f"<code>{target}</code>"), parse_mode=HTML)
        except Exception as exc:
            await message.reply_text(card("⚠️", "could not leave", type(exc).__name__), parse_mode=HTML)

    # ---- assistants
    @owner_only
    async def assistants_cmd(c, message):
        text, kb = _assistants_page()
        await send_text(message, text, reply_markup=kb, parse_mode=HTML)

    @owner_only
    async def addassistant_cmd(c, message):
        from core import assistants
        if len(message.command) < 2:
            return await message.reply_text(card("🤖", "add an assistant",
                                                 "<code>/addassistant SESSION_STRING</code>",
                                                 "use a pyrogram string session of a normal user account."), parse_mode=HTML)
        session = message.command[1].strip()
        try:
            await message.delete()  # never leave a session string sitting in chat
        except Exception:
            pass
        note = await c.send_message(message.chat.id, card("⏳", "validating session…"), parse_mode=HTML)
        a, err = await assistants.add_session(session)
        if err:
            hint = ""
            if session.startswith("1") and len(session) > 300:
                hint = f"\n{sc('this looks like a telethon session. a pyrogram session is required.')}"
            return await note.edit_text(card("❌", "could not add assistant", _h(err) + hint), parse_mode=HTML)
        uname = f"@{_h(a.username)}" if a.username else "—"
        await note.edit_text(card("✅", "assistant added",
                                  f"🤖 <b>{_h(a.name)}</b> · {uname}\n🆔 <code>{a.user_id}</code>\n"
                                  f"{sc('total assistants')} : <b>{len(assistants.alive())}</b>",
                                  "new groups are shared across all assistants. add this account to your groups."),
                             parse_mode=HTML)

    @owner_only
    async def rmassistant_cmd(c, message):
        from core import assistants
        if len(message.command) < 2 or not message.command[1].lstrip("-").isdigit():
            return await message.reply_text(card("⚠️", "usage", "<code>/rmassistant user_id</code>"), parse_mode=HTML)
        ok, err = await assistants.remove(int(message.command[1]))
        await message.reply_text(card("✅" if ok else "⚠️", "assistant removed" if ok else "could not remove", _h(err or message.command[1])), parse_mode=HTML)

    @owner_only
    async def setassistant_cmd(c, message):
        from core import assistants
        args = message.command[1:]
        if len(args) != 2 or not all(a.lstrip("-").isdigit() for a in args):
            return await message.reply_text(card("⚠️", "usage", "<code>/setassistant chat_id assistant_user_id</code>"), parse_mode=HTML)
        if not assistants.find(int(args[1])):
            return await message.reply_text(card("⚠️", "no such assistant"), parse_mode=HTML)
        store.set_assignment(int(args[0]), int(args[1]))
        await message.reply_text(card("✅", "assistant assigned", f"<code>{args[0]}</code> → <code>{args[1]}</code>"), parse_mode=HTML)

    async def assistant_info(c, message):
        from core import assistants
        a = assistants.for_chat(message.chat.id)
        uname = f"@{_h(a.username)}" if a.username else _h(a.name)
        await message.reply_text(card("🤖", "assistant for this group",
                                      f"👤 <b>{_h(a.name)}</b> · {uname}\n🆔 <code>{a.user_id}</code>",
                                      "add this account to the group, then start a voice chat and use /play."), parse_mode=HTML)

    # ---- broadcast
    @owner_only
    async def broadcast_cmd(c, message):
        args = message.command[1:]
        flags = {a.lower() for a in args if a.startswith("-")}
        if "-cancel" in flags:
            if BC["running"]:
                BC["cancel"] = True
                return await message.reply_text(card("🚫", "cancelling broadcast…"), parse_mode=HTML)
            return await message.reply_text(card("ℹ️", "no broadcast is running"), parse_mode=HTML)
        if BC["running"]:
            return await message.reply_text(card("⏳", "a broadcast is already running", note="wait for it or use /broadcast -cancel"), parse_mode=HTML)
        text = " ".join(a for a in args if not a.startswith("-")).strip()
        source = message.reply_to_message
        if not source and not text:
            text_, kb = _bc_page()
            return await message.reply_text(text_, parse_mode=HTML)
        want_users = "-groups" not in flags or "-users" in flags
        want_groups = "-users" not in flags or "-groups" in flags
        targets = []
        if want_users:
            targets += [("users", i) for i in store.ids("users")]
        if want_groups:
            targets += [("chats", i) for i in store.ids("chats")]
        if not targets:
            return await message.reply_text(card("⚠️", "no recipients yet"), parse_mode=HTML)
        pin = "-pin" in flags
        BC.update(running=True, cancel=False)
        total = len(targets)
        cancel_kb = Kb([[Btn("🚫 " + sc("cancel broadcast"), callback_data="ogo:bccancel")]])
        status = await message.reply_text(card("📡", "broadcasting…", f"0 / {total}"), reply_markup=cancel_kb, parse_mode=HTML)
        ok = failed = 0
        started = last_edit = time.time()

        async def deliver(cid):
            if source:
                return await source.copy(cid)
            return await c.send_message(cid, text, disable_web_page_preview=True)

        try:
            for i, (table, cid) in enumerate(targets, 1):
                if BC["cancel"]:
                    break
                try:
                    try:
                        sent = await deliver(cid)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 1)
                        sent = await deliver(cid)
                    ok += 1
                    if pin and table == "chats":
                        try:
                            await sent.pin(disable_notification=True)
                        except Exception:
                            pass
                except Exception:
                    failed += 1
                    store.forget(table, cid)
                if time.time() - last_edit > 4:
                    last_edit = time.time()
                    try:
                        await status.edit_text(card("📡", "broadcasting…",
                                                    f"📊 {i} / {total}\n✅ {sc('sent')} : {ok}\n❌ {sc('failed')} : {failed}"),
                                               reply_markup=cancel_kb, parse_mode=HTML)
                    except Exception:
                        pass
                await asyncio.sleep(0.05)
        finally:
            cancelled = BC["cancel"]
            BC.update(running=False, cancel=False)
        rate = (ok * 100 // total) if total else 0
        title = "broadcast cancelled" if cancelled else "broadcast completed"
        await status.edit_text(card("🚫" if cancelled else "✅", title,
                                    f"📊 {sc('targets')} : {total}\n✅ {sc('delivered')} : {ok}\n❌ {sc('failed/removed')} : {failed}\n"
                                    f"✨ {sc('success rate')} : {rate}%\n⏱ {sc('time')} : {_uptime(time.time() - started)}"),
                               parse_mode=HTML)

    # ---- wire up
    def cmd(names, fn, group=-10, extra=None):
        flt = filters.command(names, config.PREFIXES) & ~filters.bot
        if extra is not None:
            flt = flt & extra
        client.add_handler(MessageHandler(fn, flt), group=group)

    client.add_handler(MessageHandler(gate, filters.incoming & ~filters.bot), group=-40)
    client.add_handler(CallbackQueryHandler(gate_cb), group=-40)
    client.add_handler(MessageHandler(track, filters.incoming & ~filters.bot), group=-30)
    client.add_handler(MessageHandler(bot_added, filters.new_chat_members), group=-29)
    client.add_handler(MessageHandler(bot_left, filters.left_chat_member), group=-29)
    client.add_handler(CallbackQueryHandler(owner_cb, filters.regex(r"^ogo:")), group=-10)

    cmd(["owner", "ownerpanel"], owner_cmd)
    cmd("stats", stats_cmd)
    cmd("active", active_cmd)
    cmd(["groups", "chats"], groups_cmd)
    cmd("addsudo", addsudo_cmd)
    cmd("delsudo", delsudo_cmd)
    cmd("sudolist", sudolist_cmd)
    cmd("block", block_cmds("user", True))
    cmd("unblock", block_cmds("user", False))
    cmd("blockchat", block_cmds("chat", True))
    cmd("unblockchat", block_cmds("chat", False))
    cmd("blacklisted", blacklisted_cmd)
    cmd("maintenance", maintenance_cmd)
    cmd("logger", logger_cmd)
    cmd("leavechat", leave_cmd)
    cmd("assistants", assistants_cmd)
    cmd("addassistant", addassistant_cmd)
    cmd("rmassistant", rmassistant_cmd)
    cmd("setassistant", setassistant_cmd)
    cmd("assistant", assistant_info, extra=~filters.private)
    cmd("broadcast", broadcast_cmd)
