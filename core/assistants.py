"""Multiple assistant (userbot) accounts.

The primary assistant comes from SESSION in the environment. The owner can add
more string sessions at runtime (/addassistant); each gets its own Pyrogram
client and PyTgCalls instance, and every group is bound to one assistant so
load is spread out. All music code asks `calls_for(chat_id)` / `app_for(chat_id)`
instead of using a single global client.
"""
import logging

from config import config
from core import store

log = logging.getLogger("pihu.assistants")


class Assistant:
    def __init__(self, app, calls, primary=False, user_id=0, name=""):
        self.app = app
        self.calls = calls
        self.primary = primary
        self._user_id = user_id
        self._name = name
        self.alive = True

    @property
    def user_id(self):
        me = getattr(self.app, "me", None)
        if me is not None:
            return me.id
        return self._user_id or 0

    @property
    def name(self):
        me = getattr(self.app, "me", None)
        if me is not None:
            return me.first_name or self._name
        return self._name or "Assistant"

    @property
    def username(self):
        me = getattr(self.app, "me", None)
        return getattr(me, "username", None) if me is not None else None


ASSISTANTS = []
BOT = None  # the bot-token client (set by main.py); used to invite/approve/unban assistants
_HANDLERS = []  # (filter or None, coroutine function)


def set_primary(app, calls):
    ASSISTANTS.clear()
    ASSISTANTS.append(Assistant(app, calls, primary=True, name="Primary"))


def add_update_handler(flt, func):
    """Register a PyTgCalls update handler on every current and future assistant."""
    _HANDLERS.append((flt, func))
    for a in ASSISTANTS:
        _attach(a, flt, func)


def _attach(assistant, flt, func):
    deco = assistant.calls.on_update(flt) if flt is not None else assistant.calls.on_update()
    deco(func)


def alive():
    return [a for a in ASSISTANTS if a.alive]


def primary():
    return ASSISTANTS[0]


def for_chat(chat_id):
    pool = alive()
    if len(pool) <= 1:
        return pool[0] if pool else ASSISTANTS[0]
    wanted = store.get_assignment(chat_id)
    for a in pool:
        if wanted and a.user_id == wanted:
            return a
    counts = store.assignment_counts()
    best = min(pool, key=lambda a: counts.get(a.user_id, 0))
    store.set_assignment(chat_id, best.user_id)
    return best


def calls_for(chat_id):
    return for_chat(chat_id).calls


def app_for(chat_id):
    return for_chat(chat_id).app


def find(user_id):
    for a in ASSISTANTS:
        if a.user_id == int(user_id):
            return a
    return None


def _build(session, index):
    from pyrogram import Client
    from pytgcalls import PyTgCalls
    app = Client(f"PihuAssistant{index}", api_id=config.API_ID, api_hash=config.API_HASH,
                 session_string=session, in_memory=True)
    return app, PyTgCalls(app)


def boot_saved():
    """Start saved extra assistants (sync, before the main loop idles)."""
    for user_id, name, session in store.saved_assistants():
        try:
            app, calls = _build(session, len(ASSISTANTS))
            a = Assistant(app, calls, user_id=user_id, name=name)
            for flt, func in _HANDLERS:
                _attach(a, flt, func)
            calls.start()
            ASSISTANTS.append(a)
            log.info("assistant %s started", user_id)
        except Exception as exc:
            log.error("assistant %s failed to start (%s)", user_id, type(exc).__name__)


async def add_session(session):
    """Validate and start a new assistant. Returns (assistant, error)."""
    from pyrogram import Client
    session = (session or "").strip()
    try:
        probe = Client("PihuProbe", api_id=config.API_ID, api_hash=config.API_HASH,
                       session_string=session, in_memory=True)
        await probe.start()
        me = await probe.get_me()
        await probe.stop()
    except Exception as exc:
        return None, f"invalid or expired session ({type(exc).__name__})"
    if me.is_bot:
        return None, "that session belongs to a bot account; an assistant must be a user account"
    if find(me.id):
        return None, "this account is already an assistant"
    try:
        app, calls = _build(session, len(ASSISTANTS))
        a = Assistant(app, calls, user_id=me.id, name=me.first_name or "")
        for flt, func in _HANDLERS:
            _attach(a, flt, func)
        await calls.start()
    except Exception as exc:
        return None, f"could not start the assistant ({type(exc).__name__})"
    ASSISTANTS.append(a)
    store.save_assistant(me.id, me.first_name or "", session)
    return a, None


async def remove(user_id):
    a = find(user_id)
    if a is None:
        return False, "no such assistant"
    if a.primary:
        return False, "the primary assistant comes from SESSION and cannot be removed here"
    a.alive = False
    try:
        await a.app.stop()
    except Exception:
        pass
    ASSISTANTS.remove(a)
    store.delete_assistant(user_id)
    return True, None
