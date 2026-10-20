"""Small SQLite store for owner-panel data (users, chats, sudoers, blocklist,
settings, extra assistants and chat->assistant assignments).

Lives in DATA_DIR/owner.sqlite3 so it survives restarts when DATA_DIR is on a
persistent disk. Assistant session strings are stored here: keep DATA_DIR private.
"""
import os
import sqlite3
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, first_seen INTEGER);
CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT, first_seen INTEGER);
CREATE TABLE IF NOT EXISTS sudoers (id INTEGER PRIMARY KEY, added INTEGER);
CREATE TABLE IF NOT EXISTS blocked (kind TEXT NOT NULL, id INTEGER NOT NULL, added INTEGER, PRIMARY KEY (kind, id));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS assistants (user_id INTEGER PRIMARY KEY, name TEXT, session TEXT NOT NULL, added INTEGER);
CREATE TABLE IF NOT EXISTS assignments (chat_id INTEGER PRIMARY KEY, assistant_id INTEGER NOT NULL);
"""


def db_path():
    return Path(os.environ.get("DATA_DIR", "data")).expanduser() / "owner.sqlite3"


def _connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(_SCHEMA)
    return conn


def query(sql, args=()):
    with _LOCK:
        conn = _connect()
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()


def execute(sql, args=()):
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(sql, args)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


# users / chats ---------------------------------------------------------
def add_user(user_id, name):
    return execute("INSERT OR IGNORE INTO users(id,name,first_seen) VALUES (?,?,?)", (int(user_id), name or "", int(time.time()))) > 0


def add_chat(chat_id, title):
    new = execute("INSERT OR IGNORE INTO chats(id,title,first_seen) VALUES (?,?,?)", (int(chat_id), title or "", int(time.time()))) > 0
    if not new and title:
        execute("UPDATE chats SET title=? WHERE id=?", (title, int(chat_id)))
    return new


def ids(table):
    assert table in ("users", "chats")
    return [r[0] for r in query(f"SELECT id FROM {table}")]


def count(table):
    assert table in ("users", "chats", "sudoers", "assistants")
    return query(f"SELECT COUNT(*) FROM {table}")[0][0]


def forget(table, _id):
    assert table in ("users", "chats")
    execute(f"DELETE FROM {table} WHERE id=?", (int(_id),))
    if table == "chats":
        execute("DELETE FROM assignments WHERE chat_id=?", (int(_id),))


def chats_page(offset, limit):
    return query("SELECT id,title FROM chats ORDER BY first_seen DESC LIMIT ? OFFSET ?", (limit, offset))


# sudoers ---------------------------------------------------------------
def sudo_ids():
    return [r[0] for r in query("SELECT id FROM sudoers")]


def add_sudo(uid):
    return execute("INSERT OR IGNORE INTO sudoers(id,added) VALUES (?,?)", (int(uid), int(time.time()))) > 0


def del_sudo(uid):
    return execute("DELETE FROM sudoers WHERE id=?", (int(uid),)) > 0


# blocklist -------------------------------------------------------------
def is_blocked(kind, _id):
    return bool(query("SELECT 1 FROM blocked WHERE kind=? AND id=?", (kind, int(_id))))


def block(kind, _id):
    return execute("INSERT OR IGNORE INTO blocked(kind,id,added) VALUES (?,?,?)", (kind, int(_id), int(time.time()))) > 0


def unblock(kind, _id):
    return execute("DELETE FROM blocked WHERE kind=? AND id=?", (kind, int(_id))) > 0


def blocked_list(kind):
    return [r[0] for r in query("SELECT id FROM blocked WHERE kind=?", (kind,))]


# settings --------------------------------------------------------------
def get_setting(key, default=""):
    rows = query("SELECT value FROM settings WHERE key=?", (key,))
    return rows[0][0] if rows else default


def set_setting(key, value):
    execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# assistants ------------------------------------------------------------
def saved_assistants():
    return query("SELECT user_id,name,session FROM assistants ORDER BY added")


def save_assistant(user_id, name, session):
    execute("INSERT OR REPLACE INTO assistants(user_id,name,session,added) VALUES (?,?,?,?)", (int(user_id), name or "", session, int(time.time())))


def delete_assistant(user_id):
    execute("DELETE FROM assistants WHERE user_id=?", (int(user_id),))
    execute("DELETE FROM assignments WHERE assistant_id=?", (int(user_id),))


def get_assignment(chat_id):
    rows = query("SELECT assistant_id FROM assignments WHERE chat_id=?", (int(chat_id),))
    return rows[0][0] if rows else None


def set_assignment(chat_id, assistant_id):
    execute("INSERT OR REPLACE INTO assignments(chat_id,assistant_id) VALUES (?,?)", (int(chat_id), int(assistant_id)))


def assignment_counts():
    return {r[0]: r[1] for r in query("SELECT assistant_id, COUNT(*) FROM assignments GROUP BY assistant_id")}
