import sqlite3, asyncio, time, httpx, warnings, json, os, logging
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.warnings import PTBUserWarning

warnings.filterwarnings("ignore", category=PTBUserWarning)

_BASE_DIR_EARLY = os.path.dirname(os.path.abspath(__file__))

_root_logger = logging.getLogger()
if not _root_logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(os.path.join(_BASE_DIR_EARLY, "bot.log"), encoding="utf-8"), logging.StreamHandler()],
    )

logging.getLogger("httpx").setLevel(logging.WARNING)

import os
import logging
import sqlite3
import time
import html
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ChatMemberStatus, ParseMode, ChatType
from telegram.error import TelegramError, Forbidden
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ChatMemberHandler, ContextTypes, filters

BOT_NAME = "wT2x2 Moderator"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "wt2x2_moderator.db")

FLOOD_MSG_LIMIT = 3
FLOOD_WINDOW_SEC = 5
VERIFY_TIMEOUT_SEC = 10 * 60
OWNER_SYNC_INTERVAL = 5
GROUP_REFRESH_INTERVAL = 5
MUTE_LEVELS = [60, 600, 3600, 10800, 21600, 43200, 86400]

CASINO_KEYWORDS = [
    "1xbet", "1xslots", "1win", "1x2gaming", "888casino", "888poker", "888starz", "888старз",
    "azino777", "azino999", "joycasino", "джойказино", "vulkan", "вулкан", "vulkanvegas",
    "vulkan-vegas", "riobet", "риобет", "selector", "селектор", "pokerdom", "покердом",
    "pokerstars", "cosmolot", "космолот", "drift", "дрифтказино", "vovan", "вован", "frank",
    "франкказино", "frankcasino", "goldfishka", "голдфишка", "admiral", "адмирал",
    "admiralx", "адмиралx", "playfortuna", "lev", "левказино", "levcasino", "booi", "буи",
    "booicasino", "daddy", "дэдди", "daddycasino", "spinbetter", "спинбеттер", "stake",
    "roxcasino", "rox", "gizbo", "гизбо", "izzicasino", "иззи", "legzo", "легзо", "fresh",
    "freshcasino", "up-x", "upx", "апикс", "1go", "1gocasino", "eldorado", "эльдорадо",
    "casinox", "казиноикс", "slotoking", "слотокинг", "slottica", "слоттика", "richcasino",
    "volna", "волнаказино", "volnacasino", "gaminator", "гаминатор", "funrize", "pinup",
    "пинап", "пин-ап", "pin-up", "bingoboom", "бингобум", "vavada", "вавада", "spinbet",
    "glory", "глориказино", "glorycasino", "monro", "монроказино", "monrocasino", "irwin",
    "ирвин", "irwincasino", "kent", "кентказино", "kentcasino", "luckycasino", "лаккиказино",
    "ggbet", "x2bet", "иксбет", "мостбет", "mostbet", "4rabet", "4рабет",
]

DEFAULT_RULES = (
    "📜 ПРАВИЛА ЧАТА\n"
    "🎯Тема: Только по делу. Оффтоп — нельзя\n"
    "🚫Табу: Никакой политики, религии, шока и NSFW.\n"
    "🤝 Уважение: Без оскорблений команды и участников.\n"
    "💬 Чистота: Без спама. Стикеры — только 7tv.\n"
    "👉 Наш чат - @twitch_narezki_chat\n"
    "👉 Наш бот - @wT2x2_bot"
)

logger = logging.getLogger(BOT_NAME)

class Database:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._init_db()
    def _init_db(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT, first_name TEXT, last_name TEXT, is_admin INTEGER DEFAULT 0, last_seen INTEGER, PRIMARY KEY (chat_id, user_id))")
        try:
            conn.execute("ALTER TABLE users ADD COLUMN joined_at INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN language_code TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE TABLE IF NOT EXISTS warns (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, count INTEGER NOT NULL DEFAULT 0, reasons TEXT DEFAULT '', PRIMARY KEY (chat_id, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS staff (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, name TEXT, added_by INTEGER, added_at INTEGER, PRIMARY KEY (chat_id, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS rules (chat_id INTEGER PRIMARY KEY, chat_title TEXT, text TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS chat_owners (chat_id INTEGER PRIMARY KEY, chat_title TEXT, owner_id INTEGER, owner_username TEXT, confirmed INTEGER DEFAULT 0, member_count INTEGER DEFAULT 0, bot_status TEXT DEFAULT 'active', last_sync INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS chat_settings (chat_id INTEGER PRIMARY KEY, profanity_filter INTEGER DEFAULT 0, appeals_enabled INTEGER DEFAULT 0)")
        try:
            conn.execute("ALTER TABLE chat_settings ADD COLUMN appeals_enabled INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE TABLE IF NOT EXISTS banned_words (chat_id INTEGER NOT NULL, word TEXT NOT NULL, added_by INTEGER, added_at INTEGER, PRIMARY KEY (chat_id, word))")
        conn.execute("CREATE TABLE IF NOT EXISTS appeals (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, text TEXT, created_at INTEGER, status TEXT DEFAULT 'pending')")
        try:
            conn.execute("ALTER TABLE appeals ADD COLUMN decided_by INTEGER")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE TABLE IF NOT EXISTS restrictions (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, type TEXT NOT NULL, name TEXT, reason TEXT, until INTEGER, created_at INTEGER, PRIMARY KEY (chat_id, user_id))")
        try:
            conn.execute("ALTER TABLE restrictions ADD COLUMN appeal_status TEXT DEFAULT 'none'")
        except sqlite3.OperationalError:
            pass
        conn.execute("CREATE TABLE IF NOT EXISTS helpers (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, added_by INTEGER, added_at INTEGER, PRIMARY KEY (chat_id, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS verifications (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, name TEXT, message_id INTEGER, deadline INTEGER NOT NULL, PRIMARY KEY (chat_id, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS moderation_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, action_type TEXT NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT, duration INTEGER, created_at INTEGER NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS pm_users (user_id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS allowed_chats (chat_id INTEGER PRIMARY KEY, title TEXT, added_by INTEGER, added_at INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS panel_admins (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_at INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS mute_history (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, count INTEGER DEFAULT 0, reset_month INTEGER, PRIMARY KEY (chat_id, user_id))")
        conn.commit()
        conn.close()

    def get_conn(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def get_mute_level(self, chat_id, user_id):
        now = datetime.now()
        month = now.year * 12 + now.month
        with self.get_conn() as conn:
            row = conn.execute("SELECT count, reset_month FROM mute_history WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            if not row:
                return 0, month
            count, reset_month = row
            if reset_month != month:
                conn.execute("DELETE FROM mute_history WHERE chat_id=? AND user_id=?", (chat_id, user_id))
                return 0, month
            return count, month

    def increment_mute_level(self, chat_id, user_id):
        now = datetime.now()
        month = now.year * 12 + now.month
        with self.get_conn() as conn:
            row = conn.execute("SELECT count FROM mute_history WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            if row:
                count = row[0] + 1
                conn.execute("UPDATE mute_history SET count=? WHERE chat_id=? AND user_id=?", (count, chat_id, user_id))
            else:
                count = 1
                conn.execute("INSERT INTO mute_history (chat_id, user_id, count, reset_month) VALUES (?, ?, ?, ?)", (chat_id, user_id, count, month))
            return min(count, len(MUTE_LEVELS))

    def is_allowed_chat(self, chat_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT 1 FROM allowed_chats WHERE chat_id=?", (chat_id,)).fetchone() is not None
    def add_allowed_chat(self, chat_id, title, added_by):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO allowed_chats (chat_id, title, added_by, added_at) VALUES (?, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title", (chat_id, title, added_by, int(time.time())))
    def remove_allowed_chat(self, chat_id):
        with self.get_conn() as conn:
            cur = conn.execute("DELETE FROM allowed_chats WHERE chat_id=?", (chat_id,))
            return cur.rowcount > 0
    def list_allowed_chats(self):
        with self.get_conn() as conn:
            return conn.execute("SELECT chat_id, title FROM allowed_chats ORDER BY added_at DESC").fetchall()

    def is_panel_admin(self, user_id, super_admins=()):
        if user_id in super_admins:
            return True
        with self.get_conn() as conn:
            return conn.execute("SELECT 1 FROM panel_admins WHERE user_id=?", (user_id,)).fetchone() is not None
    def add_panel_admin(self, user_id, added_by):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO panel_admins (user_id, added_by, added_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO NOTHING", (user_id, added_by, int(time.time())))
    def remove_panel_admin(self, user_id):
        with self.get_conn() as conn:
            cur = conn.execute("DELETE FROM panel_admins WHERE user_id=?", (user_id,))
            return cur.rowcount > 0
    def list_panel_admins(self):
        with self.get_conn() as conn:
            return conn.execute("SELECT user_id FROM panel_admins ORDER BY added_at DESC").fetchall()

    def record_user(self, chat_id, user, is_admin=False):
        now = int(time.time())
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO users (chat_id, user_id, username, first_name, last_name, is_admin, last_seen, joined_at, language_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, "
                "last_name=excluded.last_name, is_admin=excluded.is_admin, last_seen=excluded.last_seen, "
                "language_code=excluded.language_code",
                (chat_id, user.id, user.username, user.first_name, user.last_name, 1 if is_admin else 0, now, now, getattr(user, "language_code", None)),
            )
    def get_user_meta(self, chat_id, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT username, first_name, last_name, joined_at, language_code FROM users WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    def find_user(self, chat_id, ident):
        with self.get_conn() as conn:
            ident = ident.strip()
            if ident.startswith("@"):
                ident = ident[1:]
                return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE chat_id=? AND username=? COLLATE NOCASE", (chat_id, ident)).fetchone()
            if ident.lstrip("-").isdigit():
                return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE chat_id=? AND user_id=?", (chat_id, int(ident))).fetchone()
            return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE chat_id=? AND (first_name LIKE ? OR last_name LIKE ?) COLLATE NOCASE LIMIT 1", (chat_id, f"%{ident}%", f"%{ident}%")).fetchone()
    def all_users(self, chat_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE chat_id=?", (chat_id,)).fetchall()
    def find_user_global(self, ident):
        with self.get_conn() as conn:
            ident = ident.strip()
            if ident.startswith("@"):
                ident = ident[1:]
                return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE username=? COLLATE NOCASE ORDER BY last_seen DESC LIMIT 1", (ident,)).fetchone()
            if ident.lstrip("-").isdigit():
                return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE user_id=? ORDER BY last_seen DESC LIMIT 1", (int(ident),)).fetchone()
            return conn.execute("SELECT user_id, username, first_name, last_name FROM users WHERE (first_name LIKE ? OR last_name LIKE ?) COLLATE NOCASE ORDER BY last_seen DESC LIMIT 1", (f"%{ident}%", f"%{ident}%")).fetchone()
    def get_warns(self, chat_id, user_id):
        with self.get_conn() as conn:
            row = conn.execute("SELECT count, reasons FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            return (row[0], row[1]) if row else (0, "")
    def add_warn(self, chat_id, user_id, reason=""):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO warns (chat_id, user_id, count, reasons) VALUES (?, ?, 1, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1, reasons = CASE WHEN reasons = '' THEN excluded.reasons ELSE reasons || '\n---\n' || excluded.reasons END", (chat_id, user_id, reason))
            conn.commit()
            row = conn.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            return row[0] if row else 0
    def reset_warns(self, chat_id, user_id):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    def is_staff(self, chat_id, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT 1 FROM staff WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone() is not None
    def add_staff(self, chat_id, user_id, name, added_by):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO staff (chat_id, user_id, name, added_by, added_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET name=excluded.name, added_by=excluded.added_by, added_at=excluded.added_at", (chat_id, user_id, name, added_by, int(time.time())))
    def remove_staff(self, chat_id, user_id):
        with self.get_conn() as conn:
            cur = conn.execute("DELETE FROM staff WHERE chat_id=? AND user_id=?", (chat_id, user_id))
            return cur.rowcount > 0
    def list_staff(self, chat_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT user_id, name FROM staff WHERE chat_id=?", (chat_id,)).fetchall()
    def get_rules(self, chat_id):
        with self.get_conn() as conn:
            row = conn.execute("SELECT text FROM rules WHERE chat_id=?", (chat_id,)).fetchone()
            return row[0] if row else DEFAULT_RULES
    def set_rules(self, chat_id, chat_title, text):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO rules (chat_id, chat_title, text) VALUES (?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET text=excluded.text, chat_title=excluded.chat_title", (chat_id, chat_title, text))
    def upsert_chat(self, chat_id, chat_title, member_count=None):
        with self.get_conn() as conn:
            row = conn.execute("SELECT chat_id FROM chat_owners WHERE chat_id=?", (chat_id,)).fetchone()
            if row:
                if member_count is not None:
                    conn.execute("UPDATE chat_owners SET chat_title=?, member_count=?, last_sync=? WHERE chat_id=?", (chat_title, member_count, int(time.time()), chat_id))
                else:
                    conn.execute("UPDATE chat_owners SET chat_title=?, last_sync=? WHERE chat_id=?", (chat_title, int(time.time()), chat_id))
            else:
                conn.execute("INSERT INTO chat_owners (chat_id, chat_title, member_count, bot_status, last_sync) VALUES (?, ?, ?, 'active', ?)", (chat_id, chat_title, member_count or 0, int(time.time())))
    def get_owner(self, chat_id):
        with self.get_conn() as conn:
            row = conn.execute("SELECT owner_id, owner_username, confirmed FROM chat_owners WHERE chat_id=?", (chat_id,)).fetchone()
            return (row[0], row[1], bool(row[2])) if row else (None, None, False)
    def set_owner(self, chat_id, chat_title, owner_id, owner_username, confirmed=True):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO chat_owners (chat_id, chat_title, owner_id, owner_username, confirmed, bot_status, last_sync) VALUES (?, ?, ?, ?, ?, 'active', ?) ON CONFLICT(chat_id) DO UPDATE SET chat_title=excluded.chat_title, owner_id=excluded.owner_id, owner_username=excluded.owner_username, confirmed=excluded.confirmed, bot_status='active', last_sync=excluded.last_sync", (chat_id, chat_title, owner_id, owner_username, 1 if confirmed else 0, int(time.time())))
    def set_chat_status(self, chat_id, status):
        with self.get_conn() as conn:
            conn.execute("UPDATE chat_owners SET bot_status=? WHERE chat_id=?", (status, chat_id))
    def get_owned_chats(self, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT chat_id, chat_title FROM chat_owners WHERE owner_id=? AND bot_status='active'", (user_id,)).fetchall()
    def get_all_active_chats(self):
        with self.get_conn() as conn:
            return conn.execute("SELECT chat_id FROM chat_owners WHERE bot_status='active'").fetchall()
    def get_profanity_filter(self, chat_id):
        with self.get_conn() as conn:
            row = conn.execute("SELECT profanity_filter FROM chat_settings WHERE chat_id=?", (chat_id,)).fetchone()
            return bool(row[0]) if row else False
    def set_profanity_filter(self, chat_id, enabled):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO chat_settings (chat_id, profanity_filter) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET profanity_filter=excluded.profanity_filter", (chat_id, 1 if enabled else 0))
    def get_appeals_enabled(self, chat_id):
        with self.get_conn() as conn:
            row = conn.execute("SELECT appeals_enabled FROM chat_settings WHERE chat_id=?", (chat_id,)).fetchone()
            return bool(row[0]) if row else False
    def set_appeals_enabled(self, chat_id, enabled):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO chat_settings (chat_id, appeals_enabled) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET appeals_enabled=excluded.appeals_enabled", (chat_id, 1 if enabled else 0))
    def list_banned_words(self, chat_id):
        with self.get_conn() as conn:
            rows = conn.execute("SELECT word FROM banned_words WHERE chat_id=? ORDER BY word", (chat_id,)).fetchall()
            return [r[0] for r in rows]
    def add_banned_word(self, chat_id, word, added_by):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO banned_words (chat_id, word, added_by, added_at) VALUES (?, ?, ?, ?) ON CONFLICT(chat_id, word) DO NOTHING", (chat_id, word.lower().strip(), added_by, int(time.time())))
    def remove_banned_word(self, chat_id, word):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM banned_words WHERE chat_id=? AND word=?", (chat_id, word.lower().strip()))
    def add_appeal(self, chat_id, user_id, text):
        with self.get_conn() as conn:
            cur = conn.execute("INSERT INTO appeals (chat_id, user_id, text, created_at, status) VALUES (?, ?, ?, ?, 'pending')", (chat_id, user_id, text, int(time.time())))
            return cur.lastrowid
    def get_open_appeal(self, chat_id, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT id FROM appeals WHERE chat_id=? AND user_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (chat_id, user_id)).fetchone()
    def get_appeal(self, appeal_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT id, chat_id, user_id, text, status FROM appeals WHERE id=?", (appeal_id,)).fetchone()
    def set_appeal_status(self, appeal_id, status, decided_by=None):
        with self.get_conn() as conn:
            conn.execute("UPDATE appeals SET status=?, decided_by=? WHERE id=?", (status, decided_by, appeal_id))
    def list_open_appeals(self, chat_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT id, user_id, text, created_at FROM appeals WHERE chat_id=? AND status='pending' ORDER BY created_at ASC", (chat_id,)).fetchall()
    def user_known(self, user_id):
        with self.get_conn() as conn:
            row = conn.execute("SELECT 1 FROM pm_users WHERE user_id=?", (user_id,)).fetchone()
            return row is not None
    def mark_pm_user(self, user_id):
        with self.get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO pm_users (user_id) VALUES (?)", (user_id,))
    def add_restriction(self, chat_id, user_id, rtype, name, reason=None, until=None):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO restrictions (chat_id, user_id, type, name, reason, until, created_at, appeal_status) VALUES (?, ?, ?, ?, ?, ?, ?, 'none') ON CONFLICT(chat_id, user_id) DO UPDATE SET type=excluded.type, name=excluded.name, reason=excluded.reason, until=excluded.until, created_at=excluded.created_at, appeal_status='none'", (chat_id, user_id, rtype, name, reason, until, int(time.time())))
    def remove_restriction(self, chat_id, user_id):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM restrictions WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    def list_restrictions(self, chat_id, rtype):
        with self.get_conn() as conn:
            return conn.execute("SELECT user_id, name, reason, until FROM restrictions WHERE chat_id=? AND type=? ORDER BY created_at DESC", (chat_id, rtype)).fetchall()
    def get_restriction(self, chat_id, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT type, name, reason, until, appeal_status FROM restrictions WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    def set_restriction_appeal_status(self, chat_id, user_id, status):
        with self.get_conn() as conn:
            conn.execute("UPDATE restrictions SET appeal_status=? WHERE chat_id=? AND user_id=?", (status, chat_id, user_id))
    def get_user_active_restriction(self, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT chat_id, type, appeal_status FROM restrictions WHERE user_id=? AND appeal_status!='rejected' ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
    def is_helper(self, chat_id, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT 1 FROM helpers WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone() is not None
    def add_helper(self, chat_id, user_id, added_by):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO helpers (chat_id, user_id, added_by, added_at) VALUES (?, ?, ?, ?) ON CONFLICT(chat_id, user_id) DO NOTHING", (chat_id, user_id, added_by, int(time.time())))
    def remove_helper(self, chat_id, user_id):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM helpers WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    def list_helpers(self, chat_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT user_id FROM helpers WHERE chat_id=?", (chat_id,)).fetchall()
    def get_helper_chats(self, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT chat_id FROM helpers WHERE user_id=?", (user_id,)).fetchall()
    def add_verification(self, chat_id, user_id, name, message_id, deadline_ts):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO verifications (chat_id, user_id, name, message_id, deadline) VALUES (?, ?, ?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET name=excluded.name, message_id=excluded.message_id, deadline=excluded.deadline", (chat_id, user_id, name, message_id, deadline_ts))
    def get_verification(self, chat_id, user_id):
        with self.get_conn() as conn:
            return conn.execute("SELECT name, message_id, deadline FROM verifications WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    def remove_verification(self, chat_id, user_id):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM verifications WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    def get_expired_verifications(self, now_ts):
        with self.get_conn() as conn:
            return conn.execute("SELECT chat_id, user_id, name, message_id FROM verifications WHERE deadline<=?", (now_ts,)).fetchall()
    def log_action(self, chat_id, user_id, action_type, moderator_id, reason=None, duration=None):
        with self.get_conn() as conn:
            conn.execute("INSERT INTO moderation_actions (chat_id, user_id, action_type, moderator_id, reason, duration, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (chat_id, user_id, action_type, moderator_id, reason, duration, int(time.time())))

def display_name(username, first_name, last_name):
    name = " ".join(p for p in (first_name, last_name) if p)
    if not name:
        name = username or "пользователь"
    return name

def user_link(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'

def tg_user_link(user):
    name = display_name(user.username, user.first_name, user.last_name)
    return user_link(user.id, name)

def parse_duration(token):
    m = re.match(r"^(\d+)([hdmy])$", token, re.IGNORECASE)
    if not m:
        return None
    amount, unit = int(m.group(1)), m.group(2).lower()
    units = {"h": 3600, "d": 86400, "m": 60, "y": 365 * 86400}
    return timedelta(seconds=amount * units[unit])

def format_duration(td):
    total = int(td.total_seconds())
    units = {"y": 365 * 86400, "d": 86400, "h": 3600, "m": 60}
    names = {"y": "г", "d": "д", "h": "ч", "m": "мин"}
    for unit, sec in units.items():
        if total % sec == 0 and total // sec > 0:
            return f"{total // sec}{names[unit]}"
    return f"{total}с"

def get_mute_duration(level):
    if level <= 0 or level > len(MUTE_LEVELS):
        return 60
    return MUTE_LEVELS[level - 1]

_PROFANITY_ROOTS = [r"[хx][уy][ий]", r"п[иеё]зд", r"ебл", r"[её]б[аоыи]", r"бля[дт]", r"мудак", r"сука", r"пидор", r"гандон", r"мраз", r"тварь", r"шлюх", r"нах[уy][ий]"]
_PROFANITY_RE = re.compile("|".join(_PROFANITY_ROOTS), re.IGNORECASE)
_LEET_MAP = {"0": "о", "a": "а", "@": "а", "b": "б", "e": "е", "3": "з", "y": "у", "u": "у", "i": "и", "1": "и", "!": "и", "o": "о", "p": "р", "x": "х", "h": "х", "c": "с", "k": "к", "m": "м", "t": "т"}

def _normalize_for_profanity(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[\s\.\-_*\u200b]+", "", t)
    t = "".join(_LEET_MAP.get(ch, ch) for ch in t)
    t = re.sub(r"(.)\1{1,}", r"\1", t)
    return t

def is_profane(text: str, extra_words: Optional[List[str]] = None) -> bool:
    if not text:
        return False
    normalized = _normalize_for_profanity(text)
    if _PROFANITY_RE.search(normalized) or _PROFANITY_RE.search(text.lower()):
        return True
    if extra_words:
        return contains_banned_words(text, extra_words)
    return False

def contains_banned_words(text: str, words: Optional[List[str]]) -> bool:
    if not text or not words:
        return False
    normalized = _normalize_for_profanity(text)
    lower = text.lower()
    for w in words:
        w = w.lower().strip()
        if not w:
            continue
        w_norm = _normalize_for_profanity(w)
        if w_norm and w_norm in normalized:
            return True
        if w in lower:
            return True
    return False

def no_permissions():
    return ChatPermissions(can_send_messages=False, can_send_audios=False, can_send_documents=False, can_send_photos=False, can_send_videos=False, can_send_video_notes=False, can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False, can_invite_users=False, can_pin_messages=False)

def full_permissions():
    return ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True, can_change_info=False, can_invite_users=True, can_pin_messages=False)

def build_action_text(emoji, verb, target_html, reason=None, duration_text=None, admin_html=None):
    lines = [f"{emoji} {target_html} {verb}."]
    if duration_text:
        lines.append(f"🕑Время: {html.escape(duration_text)}")
    lines.append(f"📃Причина: {html.escape(reason) if reason else '—'}")
    if admin_html:
        lines.append(f"🛡️Администратор: {admin_html}")
    return "\n".join(lines)

def parse_target_and_reason(context, message):
    args = context.args or []
    if message.reply_to_message and message.reply_to_message.from_user:
        reason = " ".join(args) if args else ""
        return None, message.reply_to_message.from_user.id, reason
    if args:
        ident = args[0]
        reason = " ".join(args[1:])
        return ident, None, reason
    return None, None, ""

class WT2X2Moderator:
    def __init__(self, super_admins=()):
        self.db = Database()
        self.application = None
        self.bot_username = None
        self.bot_id = None
        self.super_admins = tuple(super_admins)
        self._owner_sync_attempts = {}

    def is_allowed_chat(self, chat_id):
        return self.db.is_allowed_chat(chat_id)

    def is_panel_admin(self, user_id):
        return self.db.is_panel_admin(user_id, self.super_admins)

    async def set_me(self, application):
        me = await application.bot.get_me()
        self.bot_username = me.username
        self.bot_id = me.id

    def _appeal_kb_row(self, chat_id, target_id):
        if not self.db.get_appeals_enabled(chat_id) or not self.bot_username:
            return None
        return [InlineKeyboardButton("📮 Подать апелляцию", url=f"https://t.me/{self.bot_username}?start=appeal_{chat_id}_{target_id}")]

    async def handle_appeal_deeplink(self, update, context, payload):
        self.db.mark_pm_user(update.effective_user.id)
        parts = payload.split("_")
        if len(parts) < 3:
            return False
        try:
            chat_id, target_id = int(parts[1]), int(parts[2])
        except ValueError:
            return False
        reply = update.effective_message.reply_text
        if update.effective_user.id != target_id:
            await reply("Эта апелляция не для вас.")
            return True
        if not self.db.get_appeals_enabled(chat_id):
            await reply("Апелляции в этой группе отключены.")
            return True
        restriction = self.db.get_restriction(chat_id, target_id)
        if not restriction:
            await reply("У вас нет активных ограничений в этой группе.")
            return True
        if restriction[4] == "rejected":
            await reply("По этому ограничению апелляция уже была отклонена, повторная подача недоступна.")
            return True
        if self.db.get_open_appeal(chat_id, target_id):
            await reply("Ваша апелляция уже на рассмотрении, дождитесь решения.")
            return True
        context.user_data["writing_appeal"] = chat_id
        await reply("📮 Опишите одним сообщением, почему санкция была наложена ошибочно.")
        return True

    async def handle_rules_deeplink(self, update, context, payload):
        try:
            chat_id = int(payload.split("_", 1)[1])
        except ValueError:
            chat_id = None
        rules = self.db.get_rules(chat_id) if chat_id else None
        if rules:
            await update.message.reply_text(f"📜 Правила группы\n\n{html.escape(rules)}", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("В этой группе правила ещё не заданы.")

    async def my_appeal_button(self, update, context):
        query = update.callback_query
        row = self.db.get_user_active_restriction(query.from_user.id)
        if not row:
            await query.answer("У вас нет активных ограничений.", show_alert=True)
            return
        chat_id, _, _ = row
        payload = f"appeal_{chat_id}_{query.from_user.id}"
        await query.answer()
        await self.handle_appeal_deeplink(update, context, payload)

    async def _guard_group_allowed(self, update, context):
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            return True
        if self.is_allowed_chat(chat.id):
            return True
        return False

    def register(self, application):
        self.application = application
        app = self.application
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("modhelp", self.cmd_help))
        app.add_handler(CommandHandler("settings", self.cmd_settings))
        app.add_handler(CommandHandler("rules", self.cmd_rules))
        app.add_handler(CommandHandler("syncowner", self.cmd_syncowner))
        app.add_handler(CommandHandler("ban", self.cmd_ban))
        app.add_handler(CommandHandler("mute", self.cmd_mute))
        app.add_handler(CommandHandler("warn", self.cmd_warn))
        app.add_handler(CommandHandler("unban", self.cmd_unban))
        app.add_handler(CommandHandler("unmute", self.cmd_unmute))
        app.add_handler(CommandHandler("info", self.cmd_info))
        app.add_handler(CommandHandler("write", self.cmd_write))
        app.add_handler(CommandHandler("helper", self.cmd_helper))
        app.add_handler(CommandHandler("staff", self.cmd_staff))
        app.add_handler(CommandHandler("invstaff", self.cmd_invstaff))
        app.add_handler(CommandHandler("rmstaff", self.cmd_rmstaff))
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.on_new_members))
        app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, self.on_left_member))
        app.add_handler(ChatMemberHandler(self.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
        app.add_handler(ChatMemberHandler(self.on_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, self.track_and_flood), group=10)
        app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self.private_text_handler), group=11)
        job_queue = getattr(application, "job_queue", None)
        if job_queue:
            job_queue.run_repeating(self.refresh_all_groups_job, interval=GROUP_REFRESH_INTERVAL, first=5)
            job_queue.run_repeating(self.verify_timeout_job, interval=60, first=30)
        logger.info(f"{BOT_NAME} зарегистрирован в основном процессе")

    async def on_error(self, update, context):
        logger.error("Необработанная ошибка модерации: %s", context.error, exc_info=context.error)

    async def _find_owner_in_chat(self, chat_id):
        try:
            admins = await self.application.bot.get_chat_administrators(chat_id)
        except TelegramError as e:
            return None
        for m in admins:
            if m.status == ChatMemberStatus.OWNER:
                return m
        return None

    async def try_sync_owner(self, chat_id, chat_title=None):
        owner_member = await self._find_owner_in_chat(chat_id)
        if owner_member is None:
            return False
        try:
            chat = await self.application.bot.get_chat(chat_id)
            title = chat.title or chat_title or str(chat_id)
        except TelegramError:
            title = chat_title or str(chat_id)
        self.db.set_owner(chat_id, title, owner_member.user.id, owner_member.user.username, confirmed=True)
        self.db.record_user(chat_id, owner_member.user, is_admin=True)
        return True

    async def owner_sync_job(self, context):
        chat_id = context.job.data["chat_id"]
        attempts = self._owner_sync_attempts.get(chat_id, 0) + 1
        self._owner_sync_attempts[chat_id] = attempts
        found = await self.try_sync_owner(chat_id)
        if found:
            context.job.schedule_removal()
            self._owner_sync_attempts.pop(chat_id, None)
            return
        if attempts >= 60:
            context.job.schedule_removal()
            self._owner_sync_attempts.pop(chat_id, None)
            await self._offer_manual_owner_confirmation(chat_id)

    async def _offer_manual_owner_confirmation(self, chat_id):
        try:
            chat = await self.application.bot.get_chat(chat_id)
            title = chat.title or str(chat_id)
        except TelegramError:
            title = str(chat_id)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Подтвердить использование", callback_data=f"confirm_owner_{chat_id}")]])
        try:
            await self.application.bot.send_message(chat_id, "⚠️ Не удалось автоматически определить владельца.\nВладелец должен нажать кнопку ниже.", reply_markup=kb)
        except TelegramError:
            pass

    async def _confirm_owner_button(self, update, context, chat_id):
        query = update.callback_query
        user = query.from_user
        try:
            member = await self.application.bot.get_chat_member(chat_id, user.id)
        except TelegramError:
            await query.answer("Не удалось проверить статус.", show_alert=True)
            return
        if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            await query.answer("Подтвердить может только владелец или администратор.", show_alert=True)
            return
        try:
            chat = await self.application.bot.get_chat(chat_id)
            title = chat.title or str(chat_id)
        except TelegramError:
            title = str(chat_id)
        self.db.set_owner(chat_id, title, user.id, user.username, confirmed=True)
        self.db.record_user(chat_id, user, is_admin=True)
        await query.answer("Подтверждено!")
        try:
            await query.message.edit_text(f"✅ Владение подтверждено {tg_user_link(user)}.", parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

    async def refresh_all_groups_job(self, context):
        chats = self.db.get_all_active_chats()
        for (chat_id,) in chats:
            try:
                chat = await self.application.bot.get_chat(chat_id)
            except Forbidden:
                self.db.set_chat_status(chat_id, "removed")
                continue
            except TelegramError:
                continue
            try:
                member_count = await self.application.bot.get_chat_member_count(chat_id)
            except TelegramError:
                member_count = None
            self.db.upsert_chat(chat_id, chat.title or str(chat_id), member_count)
            try:
                admins = await self.application.bot.get_chat_administrators(chat_id)
                for m in admins:
                    self.db.record_user(chat_id, m.user, is_admin=True)
                    if m.status == ChatMemberStatus.OWNER:
                        owner_id, owner_username, confirmed = self.db.get_owner(chat_id)
                        if owner_id != m.user.id:
                            self.db.set_owner(chat_id, chat.title or str(chat_id), m.user.id, m.user.username, confirmed=True)
            except TelegramError:
                pass

    async def verify_timeout_job(self, context):
        expired = self.db.get_expired_verifications(int(time.time()))
        for chat_id, user_id, name, message_id in expired:
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
                self.db.log_action(chat_id, user_id, "kick_no_verify", self.bot_id, "не прошёл проверку")
            except TelegramError:
                pass
            if message_id:
                try:
                    await context.bot.delete_message(chat_id, message_id)
                except TelegramError:
                    pass
            self.db.remove_verification(chat_id, user_id)

    async def _can_moderate(self, chat_id, user_id):
        owner_id, _, _ = self.db.get_owner(chat_id)
        if user_id == owner_id:
            return True
        if self.db.is_staff(chat_id, user_id):
            return True
        try:
            member = await self.application.bot.get_chat_member(chat_id, user_id)
            return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
        except TelegramError:
            return False

    async def _resolve_target(self, update, context):
        message = update.effective_message
        chat_id = update.effective_chat.id
        ident, replied_id, reason = parse_target_and_reason(context, message)
        if replied_id:
            u = message.reply_to_message.from_user
            return u.id, display_name(u.username, u.first_name, u.last_name), reason, None
        if ident:
            row = self.db.find_user(chat_id, ident)
            if not row:
                row = self.db.find_user_global(ident)
            if row:
                uid, username, first_name, last_name = row
                return uid, display_name(username, first_name, last_name), reason, None
            if ident.startswith("@"):
                try:
                    chat = await self.application.bot.get_chat(ident)
                    return chat.id, chat.first_name or chat.title or ident, reason, None
                except TelegramError:
                    return None, None, reason, f"Не нашёл пользователя {html.escape(ident)}"
            if ident.lstrip("-").isdigit():
                return int(ident), ident, reason, None
            return None, None, reason, "Укажите @username, ID, либо ответьте на сообщение."
        return None, None, reason, None

    async def _target_is_protected(self, chat_id, actor_id, target_id):
        owner_id, _, _ = self.db.get_owner(chat_id)
        if actor_id == owner_id:
            return None
        if target_id == owner_id:
            return "Нельзя применять санкции к владельцу."
        target_is_staff = self.db.is_staff(chat_id, target_id)
        target_is_admin = False
        try:
            member = await self.application.bot.get_chat_member(chat_id, target_id)
            target_is_admin = member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
        except TelegramError:
            pass
        if target_is_staff or target_is_admin:
            return "Стафф не может применять санкции к другому стаффу/администратору."
        return None

    async def _notify_user_of_action(self, context, chat_id, target_id, action, reason):
        try:
            chat = await context.bot.get_chat(chat_id)
            chat_title = chat.title or str(chat_id)
        except TelegramError:
            chat_title = str(chat_id)
        if action == "ban":
            text = f"🔨 Вас забанили в группе «{html.escape(chat_title)}»."
            if reason:
                text += f"\n📃Причина: {html.escape(reason)}"
            if self.db.get_appeals_enabled(chat_id):
                text += "\n\nЕсли считаете бан ошибочным — подайте апелляцию из сообщения о бане в группе."
        elif action == "unban":
            text = f"🔓 Вас разбанили в группе «{html.escape(chat_title)}». Вы снова можете зайти."
        else:
            return
        try:
            await context.bot.send_message(target_id, text, parse_mode=ParseMode.HTML)
        except TelegramError:
            logger.info(f"Не удалось уведомить пользователя {target_id}: он ни разу не писал боту в ЛС.")

    async def cmd_start(self, update, context):
        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text(f"👋 Привет! Я {BOT_NAME}. Используйте /help.")
            return
        self.db.mark_pm_user(update.effective_user.id)
        args = context.args
        if args and args[0].startswith("appeal_"):
            try:
                chat_id = int(args[0].split("_", 1)[1])
            except ValueError:
                chat_id = None
            if chat_id and self.db.get_appeals_enabled(chat_id):
                context.user_data["writing_appeal"] = chat_id
                await update.message.reply_text("📮 Опишите одним сообщением, почему санкция была наложена ошибочно.")
            else:
                await update.message.reply_text("Апелляции в этой группе отключены.")
            return
        if args and args[0].startswith("rules_"):
            try:
                chat_id = int(args[0].split("_", 1)[1])
            except ValueError:
                chat_id = None
            rules = self.db.get_rules(chat_id) if chat_id else None
            if rules:
                await update.message.reply_text(f"📜 Правила группы\n\n{html.escape(rules)}", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text("В этой группе правила ещё не заданы.")
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Команды", callback_data="help_commands")], [InlineKeyboardButton("📜 О боте", callback_data="help_about")]])
        await update.message.reply_text(f"👋 Привет, {update.effective_user.first_name}!\nЯ {BOT_NAME} — бот-модератор для групп.\n\nДобавьте меня в группу и выдайте права администратора.", reply_markup=kb)

    async def cmd_help(self, update, context):
        text = "📋 Команды wT2x2 Moderator\n\nМодерация:\n/ban, /unban, /mute, /unmute, /warn, /info, /write\n\nСтафф:\n/staff, /invstaff, /rmstaff\n\nПрочее:\n/settings, /syncowner"
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

    async def cmd_settings(self, update, context):
        chat = update.effective_chat
        user = update.effective_user
        if chat.type == ChatType.PRIVATE:
            owned = self.db.get_owned_chats(user.id)
            if not owned:
                await update.message.reply_text("У вас нет групп, где вы подтверждены как владелец.")
                return
            kb = [[InlineKeyboardButton(title or str(cid), callback_data=f"settings_chat_{cid}")] for cid, title in owned]
            await update.message.reply_text("Выберите группу:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            owner_id, _, _ = self.db.get_owner(chat.id)
            if user.id != owner_id:
                await update.message.reply_text("Настройки доступны только владельцу в ЛС.")
                return
            try:
                await context.bot.send_message(user.id, f"Настройки группы {chat.title}:")
                await self._send_settings_menu(context, user.id, chat.id)
                await update.message.reply_text("Настройки отправлены в ЛС.")
            except Forbidden:
                await update.message.reply_text(f"Сначала напишите мне в ЛС: @{self.bot_username}")

    async def _send_settings_menu(self, context, user_id, chat_id):
        rules = self.db.get_rules(chat_id)
        staff = self.db.list_staff(chat_id)
        prof_on = self.db.get_profanity_filter(chat_id)
        appeals_on = self.db.get_appeals_enabled(chat_id)
        words = self.db.list_banned_words(chat_id)
        bans = self.db.list_restrictions(chat_id, "ban")
        mutes = self.db.list_restrictions(chat_id, "mute")
        kb = [
            [InlineKeyboardButton(f"📜 {'Изменить' if rules else 'Добавить'} правила", callback_data=f"settings_rules_{chat_id}")],
            [InlineKeyboardButton(f"🛡 Стафф ({len(staff)})", callback_data=f"settings_staff_{chat_id}")],
            [InlineKeyboardButton(f"🤬 Мат-фильтр: {'✅ Вкл' if prof_on else '❌ Выкл'}", callback_data=f"toggleprof_{chat_id}")],
            [InlineKeyboardButton(f"🚫 Запрещённые слова ({len(words)})", callback_data=f"settings_words_{chat_id}")],
            [InlineKeyboardButton(f"📮 Апелляции: {'✅ Вкл' if appeals_on else '❌ Выкл'}", callback_data=f"toggleappeals_{chat_id}")],
            [InlineKeyboardButton(f"🔨 Забаненные ({len(bans)})", callback_data=f"banlist_{chat_id}_0")],
            [InlineKeyboardButton(f"🔇 В муте ({len(mutes)})", callback_data=f"mutelist_{chat_id}_0")],
        ]
        if appeals_on:
            kb.append([InlineKeyboardButton("🛡 Назначить модератора", callback_data=f"assignmod_{chat_id}")])
        await context.bot.send_message(user_id, f"Настройки", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    async def _edit(self, query, text, kb):
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=kb, parse_mode=ParseMode.HTML)
            else:
                await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

    async def _cb_panel_home(self, update, context):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        await query.answer()
        chats = self.db.list_allowed_chats()
        kb = []
        for cid, title in chats:
            kb.append([
                InlineKeyboardButton(title or str(cid), callback_data=f"wtm_chatsettings_{cid}"),
                InlineKeyboardButton("🗑", callback_data=f"wtm_rmchat_{cid}"),
            ])
        kb.append([InlineKeyboardButton("➕ Разрешить чат/канал", callback_data="wtm_addchat_prompt")])
        kb.append([InlineKeyboardButton("👤 Доступ к панели", callback_data="wtm_admins")])
        kb.append([InlineKeyboardButton("« Назад", callback_data="admin_panel")])
        text = "🛡 <b>wT2x2 Moderator</b>\n\nПанель управления системой модерации.\n\n📋 Разрешённые чаты/каналы:" if chats else "🛡 <b>wT2x2 Moderator</b>\n\nПанель управления системой модерации.\n\nПока нет разрешённых чатов/каналов."
        await self._edit(query, text, InlineKeyboardMarkup(kb))

    async def _cb_panel_chats(self, update, context):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        await query.answer()
        chats = self.db.list_allowed_chats()
        kb = []
        for cid, title in chats:
            kb.append([
                InlineKeyboardButton(title or str(cid), callback_data=f"wtm_chatsettings_{cid}"),
                InlineKeyboardButton("🗑", callback_data=f"wtm_rmchat_{cid}"),
            ])
        kb.append([InlineKeyboardButton("➕ Разрешить чат/канал", callback_data="wtm_addchat_prompt")])
        kb.append([InlineKeyboardButton("« Назад", callback_data="wtm_panel")])
        text = "📋 <b>Разрешённые чаты/каналы</b>\n\nЗдесь бот работает как модератор." if chats else "Пока нет разрешённых чатов/каналов."
        await self._edit(query, text, InlineKeyboardMarkup(kb))

    async def _cb_panel_addchat_prompt(self, update, context):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        await query.answer()
        context.user_data["wtm_adding_chat"] = True
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="wtm_chats")]])
        await self._edit(query, "Пришлите числовой ID чата/канала, который нужно разрешить для модерации (бот должен быть в нём администратором).", kb)

    async def _cb_panel_rmchat(self, update, context, chat_id):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        self.db.remove_allowed_chat(chat_id)
        await query.answer("Чат удалён из разрешённых.")
        await self._cb_panel_chats(update, context)

    async def _cb_panel_admins(self, update, context):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        await query.answer()
        admins = self.db.list_panel_admins()
        kb = [[InlineKeyboardButton(f"ID {uid}", callback_data="noop"), InlineKeyboardButton("🗑", callback_data=f"wtm_rmadmin_{uid}")] for (uid,) in admins]
        kb.append([InlineKeyboardButton("➕ Выдать доступ по ID", callback_data="wtm_addadmin_prompt")])
        kb.append([InlineKeyboardButton("« Назад", callback_data="wtm_panel")])
        text = "👤 <b>Доступ к панели</b>\n\nПользователи, которым выдан доступ к админ-панели wT2x2 Moderator."
        await self._edit(query, text, InlineKeyboardMarkup(kb))

    async def _cb_panel_addadmin_prompt(self, update, context):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        await query.answer()
        context.user_data["wtm_adding_admin"] = True
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="wtm_admins")]])
        await self._edit(query, "Пришлите Telegram ID пользователя, которому нужно выдать доступ к админ-панели.", kb)

    async def _cb_panel_rmadmin(self, update, context, target_id):
        query = update.callback_query
        if not self.is_panel_admin(query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        self.db.remove_panel_admin(target_id)
        await query.answer("Доступ отозван.")
        await self._cb_panel_admins(update, context)

    async def _cb_info_warns(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        warns, reasons = self.db.get_warns(chat_id, target_id)
        text = f"⚠️ Предупреждений: {warns}/3"
        if reasons:
            text += "\n\n" + reasons
        await query.answer(text, show_alert=True)

    async def _cb_info_restrict(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        protect_error = await self._target_is_protected(chat_id, query.from_user.id, target_id)
        if protect_error:
            await query.answer(protect_error, show_alert=True); return
        until = datetime.now(timezone.utc) + timedelta(hours=1)
        try:
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=no_permissions(), until_date=until)
        except TelegramError as e:
            await query.answer(f"Ошибка: {e}", show_alert=True); return
        self.db.log_action(chat_id, target_id, "mute", query.from_user.id, "через /info", 3600)
        self.db.add_restriction(chat_id, target_id, "mute", None, "через /info", int(until.timestamp()))
        await query.answer("🔇 Пользователь ограничен на 1 час.", show_alert=True)

    async def _cb_info_ban(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        protect_error = await self._target_is_protected(chat_id, query.from_user.id, target_id)
        if protect_error:
            await query.answer(protect_error, show_alert=True); return
        try:
            await context.bot.ban_chat_member(chat_id, target_id)
        except TelegramError as e:
            await query.answer(f"Ошибка: {e}", show_alert=True); return
        self.db.log_action(chat_id, target_id, "ban", query.from_user.id, "через /info")
        self.db.add_restriction(chat_id, target_id, "ban", None, "через /info")
        await query.answer("🔨 Пользователь заблокирован.", show_alert=True)

    async def _cb_info_rights(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Нет доступа.", show_alert=True); return
        try:
            member = await context.bot.get_chat_member(chat_id, target_id)
            await query.answer(f"Статус: {member.status}", show_alert=True)
        except TelegramError as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)

    async def cmd_rules(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        chat = update.effective_chat
        rules = self.db.get_rules(chat.id)
        caption = f"<b>Правила группы:</b>\n\n<blockquote expandable>{html.escape(rules)}</blockquote>"
        await self._send_rules_card(update.effective_message, caption)

    async def _send_rules_card(self, message, caption):
        try:
            file_id = get_main_image()
            if file_id:
                await message.reply_photo(file_id, caption=caption, parse_mode=ParseMode.HTML)
            else:
                await message.reply_text(caption, parse_mode=ParseMode.HTML)
        except TelegramError:
            await message.reply_text(caption, parse_mode=ParseMode.HTML)

    async def cmd_syncowner(self, update, context):
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Эту команду нужно использовать в группе.")
            return
        ok = await self.try_sync_owner(chat.id, chat.title)
        if ok:
            owner_id, owner_username, _ = self.db.get_owner(chat.id)
            await update.message.reply_text(f"✅ Владелец обновлён: {user_link(owner_id, owner_username or str(owner_id))}", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("Не удалось определить владельца.")

    async def _require_group_and_perm(self, update, context):
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в группах.")
            return False
        if not await self._can_moderate(chat.id, update.effective_user.id):
            return False
        return True

    async def cmd_ban(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        if not await self._require_group_and_perm(update, context):
            return
        chat_id = update.effective_chat.id
        target_id, name, reason, error = await self._resolve_target(update, context)
        if not target_id:
            await update.message.reply_text(error or "Использование: /ban @user [причина]")
            return
        protect_error = await self._target_is_protected(chat_id, update.effective_user.id, target_id)
        if protect_error:
            await update.message.reply_text(protect_error)
            return
        try:
            await context.bot.ban_chat_member(chat_id, target_id)
        except TelegramError as e:
            await update.message.reply_text(f"Ошибка: {e}")
            return
        self.db.log_action(chat_id, target_id, "ban", update.effective_user.id, reason)
        self.db.add_restriction(chat_id, target_id, "ban", name, reason)
        text = build_action_text("🔨", "забанен(а)", user_link(target_id, name), reason, admin_html=tg_user_link(update.effective_user))
        kb_rows = [[InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban_{chat_id}_{target_id}")]]
        appeal_row = self._appeal_kb_row(chat_id, target_id)
        if appeal_row:
            kb_rows.append(appeal_row)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb_rows))
        await self._notify_user_of_action(context, chat_id, target_id, "ban", reason)

    async def cmd_unban(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        if not await self._require_group_and_perm(update, context):
            return
        chat_id = update.effective_chat.id
        target_id, name, _, error = await self._resolve_target(update, context)
        if not target_id:
            await update.message.reply_text(error or "Использование: /unban @user")
            return
        try:
            await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        except TelegramError as e:
            await update.message.reply_text(f"Ошибка: {e}")
            return
        self.db.log_action(chat_id, target_id, "unban", update.effective_user.id)
        self.db.remove_restriction(chat_id, target_id)
        await update.message.reply_text(f"🔓 {user_link(target_id, name)} разбанен(а).\n🛡️Администратор: {tg_user_link(update.effective_user)}", parse_mode=ParseMode.HTML)
        await self._notify_user_of_action(context, chat_id, target_id, "unban", "")

    async def cmd_mute(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        if not await self._require_group_and_perm(update, context):
            return
        chat_id = update.effective_chat.id
        message = update.effective_message
        ident, replied_id, _ = parse_target_and_reason(context, message)
        target_id = None
        name = None
        duration = None
        reason = ""
        if replied_id:
            u = message.reply_to_message.from_user
            target_id, name = u.id, display_name(u.username, u.first_name, u.last_name)
            args = context.args or []
            if args:
                d = parse_duration(args[0])
                if d:
                    duration = d
                    reason = " ".join(args[1:])
                else:
                    reason = " ".join(args)
        elif ident:
            row = self.db.find_user(chat_id, ident)
            if row:
                target_id, username, first_name, last_name = row[0], row[1], row[2], row[3]
                name = display_name(username, first_name, last_name)
            args = context.args or []
            rest = args[1:]
            if rest:
                d = parse_duration(rest[0])
                if d:
                    duration = d
                    reason = " ".join(rest[1:])
                else:
                    reason = " ".join(rest)
        if not target_id and ident and ident.startswith("@"):
            try:
                chat = await self.application.bot.get_chat(ident)
                target_id, name = chat.id, chat.first_name or chat.title or ident
            except TelegramError:
                pass
        if not target_id:
            await update.message.reply_text("Использование: /mute @user [10m|1h|1d] [причина]")
            return
        protect_error = await self._target_is_protected(chat_id, update.effective_user.id, target_id)
        if protect_error:
            await update.message.reply_text(protect_error)
            return

        level, _ = self.db.get_mute_level(chat_id, target_id)
        if duration is None:
            if level == 0:
                duration_sec = 60
            else:
                duration_sec = get_mute_duration(level)
            duration = timedelta(seconds=duration_sec)
            self.db.increment_mute_level(chat_id, target_id)
        else:
            duration_sec = int(duration.total_seconds())

        until = datetime.now(timezone.utc) + duration
        try:
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=no_permissions(), until_date=until)
        except TelegramError as e:
            await update.message.reply_text(f"Ошибка: {e}")
            return
        self.db.log_action(chat_id, target_id, "mute", update.effective_user.id, reason, duration_sec)
        until_ts = int(until.timestamp())
        self.db.add_restriction(chat_id, target_id, "mute", name, reason, until_ts)
        dur_text = format_duration(duration)
        text = build_action_text("🔇", "замучен(а)", user_link(target_id, name), reason, duration_text=dur_text, admin_html=tg_user_link(update.effective_user))
        kb_rows = [[InlineKeyboardButton("🔊 Снять мут", callback_data=f"unmute_{chat_id}_{target_id}")]]
        appeal_row = self._appeal_kb_row(chat_id, target_id)
        if appeal_row:
            kb_rows.append(appeal_row)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb_rows))

    async def cmd_unmute(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        if not await self._require_group_and_perm(update, context):
            return
        chat_id = update.effective_chat.id
        target_id, name, _, error = await self._resolve_target(update, context)
        if not target_id:
            await update.message.reply_text(error or "Использование: /unmute @user")
            return
        try:
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=full_permissions())
        except TelegramError as e:
            await update.message.reply_text(f"Ошибка: {e}")
            return
        self.db.log_action(chat_id, target_id, "unmute", update.effective_user.id)
        self.db.remove_restriction(chat_id, target_id)
        await update.message.reply_text(f"🔊 {user_link(target_id, name)} размучен(а).\n🛡️Администратор: {tg_user_link(update.effective_user)}", parse_mode=ParseMode.HTML)

    async def cmd_warn(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        if not await self._require_group_and_perm(update, context):
            return
        chat_id = update.effective_chat.id
        target_id, name, reason, error = await self._resolve_target(update, context)
        if not target_id:
            await update.message.reply_text(error or "Использование: /warn @user [причина]")
            return
        protect_error = await self._target_is_protected(chat_id, update.effective_user.id, target_id)
        if protect_error:
            await update.message.reply_text(protect_error)
            return
        count = self.db.add_warn(chat_id, target_id, reason)
        self.db.log_action(chat_id, target_id, "warn", update.effective_user.id, reason)
        text = f"⚠️ {user_link(target_id, name)} получил(а) предупреждение ({count}/3).\n📃Причина: {html.escape(reason) if reason else '—'}\n🛡️Администратор: {tg_user_link(update.effective_user)}"
        kb_rows = [[InlineKeyboardButton("♻️ Снять предупреждение", callback_data=f"unwarn_{chat_id}_{target_id}")]]
        if count >= 3:
            try:
                until = datetime.now(timezone.utc) + timedelta(days=7)
                await context.bot.ban_chat_member(chat_id, target_id, until_date=until)
                self.db.reset_warns(chat_id, target_id)
                self.db.log_action(chat_id, target_id, "ban", self.bot_id, "3/3 предупреждений", int(timedelta(days=7).total_seconds()))
                self.db.add_restriction(chat_id, target_id, "ban", name, "3/3 предупреждений", int(until.timestamp()))
                text += "\n🔨 Достигнут лимит предупреждений (3/3) — бан на 7 дней."
                kb_rows.append([InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban_{chat_id}_{target_id}")])
            except TelegramError:
                pass
        appeal_row = self._appeal_kb_row(chat_id, target_id)
        if appeal_row:
            kb_rows.append(appeal_row)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb_rows))

    async def cmd_info(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в группах.")
            return
        if not await self._can_moderate(chat.id, update.effective_user.id):
            await update.message.reply_text("Нет прав.")
            return
        try:
            target_id, name, _, error = await self._resolve_target(update, context)
            target_user = None
            searched_username = None
            args = context.args
            if args and args[0].startswith("@"):
                searched_username = args[0][1:]
            if not target_id:
                if error:
                    await update.message.reply_text(error)
                    return
                u = update.effective_user
                target_id, name = u.id, display_name(u.username, u.first_name, u.last_name)
                target_user = u
            elif update.effective_message.reply_to_message:
                target_user = update.effective_message.reply_to_message.from_user

            member = None
            try:
                member = await context.bot.get_chat_member(chat.id, target_id)
                if target_user is None and member.user:
                    target_user = member.user
            except TelegramError:
                member = None

            meta = self.db.get_user_meta(chat.id, target_id)
            username = (target_user.username if target_user else None) or (meta[0] if meta else None) or searched_username
            first_name = (target_user.first_name if target_user else None) or (meta[1] if meta else None) or name
            last_name = (target_user.last_name if target_user else None) or (meta[2] if meta else None)
            joined_at = meta[3] if meta else None
            lang_code = (target_user.language_code if target_user else None) or (meta[4] if meta else None)

            warns, _ = self.db.get_warns(chat.id, target_id)
            is_staff = self.db.is_staff(chat.id, target_id)
            owner_id, _, _ = self.db.get_owner(chat.id)

            restriction = self.db.get_restriction(chat.id, target_id)
            has_restriction = restriction is not None

            state = "👀 Участник"
            kb_rows = []
            if member:
                if member.status == ChatMemberStatus.BANNED:
                    state = "🔨 Забанен(а)"
                elif member.status == ChatMemberStatus.RESTRICTED and not member.can_send_messages:
                    state = "🔇 В муте"
                elif member.status == ChatMemberStatus.LEFT:
                    state = "🚪 Покинул(а) чат"
                elif member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                    state = "🛡 Администратор" if member.status == ChatMemberStatus.ADMINISTRATOR else "👑 Владелец"
            else:
                state = "🚪 Не найден(а) в чате"

            lang_names = {"ru": "Russian", "en": "English", "uk": "Ukrainian", "kk": "Kazakh", "be": "Belarusian"}
            lang_display = lang_names.get(lang_code, lang_code.capitalize()) if lang_code else "—"
            joined_display = datetime.fromtimestamp(joined_at).strftime("%d.%m.%y в %H:%M") if joined_at else "неизвестно"

            lines = [
                f"<b>wT2x2 Moderator</b>",
                f"🆔 <b>ID</b>: <code>{target_id}</code> #id{target_id}",
                f"👤 <b>Имя</b>: {html.escape(first_name or '—')}",
            ]
            if last_name:
                lines.append(f"👥 <b>Фамилия</b>: \"{html.escape(last_name)}\"")
            lines.append(f"🌐 <b>Имя пользователя</b>: {('@' + username) if username else '—'}")
            lines.append(f"👀 <b>Состояние</b>: {state}")
            lines.append(f"❗ <b>Предупреждения</b>: {warns}/3")
            lines.append(f"↳ <b>Вступил(а)</b>: {joined_display}")
            lines.append(f"🇷🇺 <b>Язык</b>: {lang_display}")
            text = "\n".join(lines)

            if has_restriction:
                rtype = restriction[0]
                if rtype == "ban":
                    kb_rows.append([InlineKeyboardButton("🔓 Разблокировать", callback_data=f"unban_{chat.id}_{target_id}")])
                elif rtype == "mute":
                    kb_rows.append([InlineKeyboardButton("🔊 Снять ограничение", callback_data=f"unmute_{chat.id}_{target_id}")])
            else:
                kb_rows.append([InlineKeyboardButton("❗ Предупреждения", callback_data=f"infowarns_{chat.id}_{target_id}")])
                kb_rows.append([
                    InlineKeyboardButton("🔪 Ограничить", callback_data=f"inforestrict_{chat.id}_{target_id}"),
                    InlineKeyboardButton("🚫 Заблокировать", callback_data=f"infoban_{chat.id}_{target_id}"),
                ])
                kb_rows.append([InlineKeyboardButton("🕹 Разрешения", callback_data=f"inforights_{chat.id}_{target_id}")])

            kb = InlineKeyboardMarkup(kb_rows)
            await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            logger.exception("Ошибка в /info")
            await update.message.reply_text("⚠️ Не удалось получить информацию.")

    async def cmd_write(self, update, context):
        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в ЛС с ботом.")
            return
        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text("Использование: /write @user текст")
            return
        ident = args[0]
        text_to_send = " ".join(args[1:])
        row = self.db.find_user_global(ident)
        target_id = None
        name = None
        if row:
            uid, username, first_name, last_name = row
            target_id, name = uid, display_name(username, first_name, last_name)
        elif ident.lstrip("-").isdigit():
            target_id, name = int(ident), ident
        if not target_id:
            await update.message.reply_text("Пользователь не найден.")
            return
        with self.db.get_conn() as conn:
            chats = conn.execute("SELECT DISTINCT chat_id FROM users WHERE user_id=?", (target_id,)).fetchall()
        allowed = self.is_panel_admin(update.effective_user.id)
        if not allowed:
            for (cid,) in chats:
                if await self._can_moderate(cid, update.effective_user.id):
                    allowed = True
                    break
        if not allowed:
            await update.message.reply_text("У вас нет прав писать этому пользователю.")
            return
        try:
            await context.bot.send_message(target_id, text_to_send)
        except TelegramError:
            await update.message.reply_text(f"⚠️ Не удалось отправить сообщение {user_link(target_id, name)}: пользователь ни разу не писал боту в ЛС, а Telegram не позволяет боту писать первым.", parse_mode=ParseMode.HTML)
            return
        await update.message.reply_text(f"✅ Сообщение отправлено {user_link(target_id, name)}.", parse_mode=ParseMode.HTML)

    async def cmd_staff(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в группах.")
            return
        staff = self.db.list_staff(chat.id)
        owner_id, owner_username, _ = self.db.get_owner(chat.id)
        lines = ["🛡 Стафф группы\n"]
        if owner_id:
            lines.append(f"👑 {user_link(owner_id, owner_username or str(owner_id))} — владелец")
        if staff:
            for uid, name in staff:
                lines.append(f"🛡 {user_link(uid, name or str(uid))}")
        else:
            lines.append("Стафф пока не назначен.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_invstaff(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в группах.")
            return
        owner_id, _, _ = self.db.get_owner(chat.id)
        if update.effective_user.id != owner_id:
            await update.message.reply_text("Назначать стафф может только владелец.")
            return
        target_id, name, _, error = await self._resolve_target(update, context)
        if not target_id:
            await update.message.reply_text(error or "Использование: /invstaff @user")
            return
        self.db.add_staff(chat.id, target_id, name, update.effective_user.id)
        await update.message.reply_text(f"✅ {user_link(target_id, name)} назначен(а) стаффом.", parse_mode=ParseMode.HTML)

    async def cmd_rmstaff(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        chat = update.effective_chat
        if chat.type == ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в группах.")
            return
        owner_id, _, _ = self.db.get_owner(chat.id)
        if update.effective_user.id != owner_id:
            await update.message.reply_text("Снимать стафф может только владелец.")
            return
        target_id, name, _, error = await self._resolve_target(update, context)
        if not target_id:
            await update.message.reply_text(error or "Использование: /rmstaff @user")
            return
        removed = self.db.remove_staff(chat.id, target_id)
        if removed:
            await update.message.reply_text(f"✅ {user_link(target_id, name)} больше не стафф.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("Этот пользователь не в списке стаффа.")

    async def on_new_members(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        chat = update.effective_chat
        message = update.effective_message
        for member in message.new_chat_members:
            if member.id == self.bot_id:
                continue
            self.db.record_user(chat.id, member)
            mention = tg_user_link(member)
            try:
                await context.bot.restrict_chat_member(chat.id, member.id, permissions=no_permissions())
            except TelegramError:
                pass
            deadline = int(time.time()) + VERIFY_TIMEOUT_SEC
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Бурмалда", callback_data=f"verify_{chat.id}_{member.id}")]])
            try:
                sent = await context.bot.send_message(chat.id, f"👋 {mention} Подтвердите что вы не робот нажав на кнопку \"Бурмалда\"", parse_mode=ParseMode.HTML, reply_markup=kb)
                self.db.add_verification(chat.id, member.id, mention, sent.message_id, deadline)
            except TelegramError:
                pass
        try:
            await message.delete()
        except TelegramError:
            pass

    async def on_left_member(self, update, context):
        try:
            await update.effective_message.delete()
        except TelegramError:
            pass

    async def on_chat_member_update(self, update, context):
        cmu = update.chat_member
        if not cmu:
            return
        chat_id = cmu.chat.id
        new = cmu.new_chat_member
        is_admin = new.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
        self.db.record_user(chat_id, new.user, is_admin=is_admin)
        if new.status == ChatMemberStatus.OWNER:
            self.db.set_owner(chat_id, cmu.chat.title or str(chat_id), new.user.id, new.user.username, confirmed=True)

    async def on_my_chat_member(self, update, context):
        cmu = update.my_chat_member
        chat = cmu.chat
        new_status = cmu.new_chat_member.status
        old_status = cmu.old_chat_member.status
        was_in_chat = old_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
        is_in_chat = new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
        if is_in_chat and not was_in_chat:
            self.db.upsert_chat(chat.id, chat.title or str(chat.id))
            self.db.set_chat_status(chat.id, "active")
            self._owner_sync_attempts[chat.id] = 0
            found = await self.try_sync_owner(chat.id, chat.title)
            if not found and self.application.job_queue:
                self.application.job_queue.run_repeating(self.owner_sync_job, interval=OWNER_SYNC_INTERVAL, first=OWNER_SYNC_INTERVAL, data={"chat_id": chat.id}, name=f"owner_sync_{chat.id}")
            try:
                await context.bot.send_message(chat.id, f"👋 Привет! Я {BOT_NAME}. Выдайте мне права администратора. /help — список команд.")
            except TelegramError:
                pass
        elif not is_in_chat and was_in_chat:
            self.db.set_chat_status(chat.id, "removed")
            if self.application.job_queue:
                for job in self.application.job_queue.get_jobs_by_name(f"owner_sync_{chat.id}"):
                    job.schedule_removal()
            self._owner_sync_attempts.pop(chat.id, None)
        elif new_status == ChatMemberStatus.ADMINISTRATOR and old_status != ChatMemberStatus.ADMINISTRATOR:
            await self.try_sync_owner(chat.id, chat.title)

    async def track_and_flood(self, update, context):
        if not await self._guard_group_allowed(update, context):
            return
        message = update.effective_message
        if not message or not update.effective_user:
            return
        chat_id = update.effective_chat.id
        user = update.effective_user
        self.db.record_user(chat_id, user)
        if user.is_bot:
            return

        text = message.text or ""
        casino_kw_group = "|".join(re.escape(k) for k in CASINO_KEYWORDS)
        casino_link_pattern = (
            r'(?:https?://|www\.|t\.me/|telegram\.me/)\S*'
            r'(?:' + casino_kw_group + r'|1xbet|1хбет|казино|casino|poker|roulette|slot|vulkan|азарт)\S*'
            r'|(?:[a-z0-9-]+\.(?:xyz|bet|win|casino|vip|club|top|site|online))\b'
            r'|\b(?:' + casino_kw_group + r')\b\S{0,20}(?:\.(?:xyz|bet|win|casino|vip|club|top|site|online|ru|com|net)|https?://\S+|t\.me/\S+)'
        )
        casino_links = re.findall(casino_link_pattern, text, re.IGNORECASE)
        if casino_links:
            try:
                await message.delete()
                duration_sec = 86400
                until = datetime.now(timezone.utc) + timedelta(seconds=duration_sec)
                await context.bot.restrict_chat_member(chat_id, user.id, permissions=no_permissions(), until_date=until)
                self.db.increment_mute_level(chat_id, user.id)
                self.db.log_action(chat_id, user.id, "mute_auto_casino", self.bot_id, "Запрещённый контент", duration_sec)
                self.db.add_restriction(chat_id, user.id, "mute", tg_user_link(user), "Запрещённый контент", int(until.timestamp()))
                await context.bot.send_message(chat_id, f"🔇 {tg_user_link(user)} замучен(а) на {format_duration(timedelta(seconds=duration_sec))} по причине: Запрещённый контент", parse_mode=ParseMode.HTML)
                for aid in self.super_admins:
                    try:
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔨 Бан", callback_data=f"ban_{chat_id}_{user.id}")],
                            [InlineKeyboardButton("⚠️ Выдать предупреждение", callback_data=f"warn_{chat_id}_{user.id}")]
                        ])
                        await context.bot.send_message(aid, f"🚫 Запрещённый контент\nПользователь: {tg_user_link(user)}\nID: {user.id}\nСсылки на казино\nДействие: мут {format_duration(timedelta(seconds=duration_sec))}", parse_mode=ParseMode.HTML, reply_markup=kb)
                    except:
                        pass
            except TelegramError:
                pass
            return

        custom_words = self.db.list_banned_words(chat_id)
        prof_on = self.db.get_profanity_filter(chat_id)
        text_hit = message.text and (
            (prof_on and is_profane(message.text)) or contains_banned_words(message.text, custom_words)
        )
        if text_hit and not await self._can_moderate(chat_id, user.id):
            try:
                await message.delete()
                level, _ = self.db.get_mute_level(chat_id, user.id)
                duration_sec = get_mute_duration(level + 1)
                until = datetime.now(timezone.utc) + timedelta(seconds=duration_sec)
                await context.bot.restrict_chat_member(chat_id, user.id, permissions=no_permissions(), until_date=until)
                self.db.increment_mute_level(chat_id, user.id)
                text = build_action_text("🔇", "замучен(а)", tg_user_link(user), reason="Запрещённое слово", duration_text=format_duration(timedelta(seconds=duration_sec)), admin_html=tg_user_link(await context.bot.get_me()))
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔊 Снять мут", callback_data=f"unmute_{chat_id}_{user.id}")]])
                await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
                self.db.log_action(chat_id, user.id, "auto_mute_profanity", self.bot_id, "Запрещённое слово", duration_sec)
                self.db.add_restriction(chat_id, user.id, "mute", tg_user_link(user), "Запрещённое слово", int(until.timestamp()))
            except TelegramError:
                pass
            return

        now = time.time()
        key = f"flood_{chat_id}_{user.id}"
        bucket = context.chat_data.setdefault(key, [])
        bucket.append(now)
        while bucket and now - bucket[0] > FLOOD_WINDOW_SEC:
            bucket.pop(0)
        if len(bucket) > FLOOD_MSG_LIMIT:
            if await self._can_moderate(chat_id, user.id):
                return
            try:
                level, _ = self.db.get_mute_level(chat_id, user.id)
                duration_sec = get_mute_duration(level + 1)
                until = datetime.now(timezone.utc) + timedelta(seconds=duration_sec)
                await context.bot.restrict_chat_member(chat_id, user.id, permissions=no_permissions(), until_date=until)
                self.db.increment_mute_level(chat_id, user.id)
                text = build_action_text("🔇", "замучен(а)", tg_user_link(user), reason="Флуд", duration_text=format_duration(timedelta(seconds=duration_sec)), admin_html=tg_user_link(await context.bot.get_me()))
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔊 Снять мут", callback_data=f"unmute_{chat_id}_{user.id}")]])
                await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
                self.db.log_action(chat_id, user.id, "auto_mute_flood", self.bot_id, "Флуд", duration_sec)
                self.db.add_restriction(chat_id, user.id, "mute", tg_user_link(user), "Флуд", int(until.timestamp()))
            except TelegramError:
                pass
            bucket.clear()

    async def callback_handler(self, update, context):
        query = update.callback_query
        data = query.data or ""
        try:
            if data == "help_commands":
                await query.message.edit_text("📋 Команды\n\n/ban, /mute, /warn, /write\n/unban, /unmute, /info\n/staff, /invstaff, /rmstaff\n/settings, /syncowner", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu")]]), parse_mode=ParseMode.HTML)
                await query.answer()
            elif data == "help_about":
                await query.message.edit_text(f"ℹ️ {BOT_NAME}\nБот-модератор для Telegram-групп.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="start_menu")]]), parse_mode=ParseMode.HTML)
                await query.answer()
            elif data == "start_menu":
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Команды", callback_data="help_commands")], [InlineKeyboardButton("📜 О боте", callback_data="help_about")]])
                await query.message.edit_text(f"👋 {BOT_NAME} — главное меню.", reply_markup=kb)
                await query.answer()
            elif data.startswith("confirm_owner_"):
                chat_id = int(data.split("_", 2)[2])
                await self._confirm_owner_button(update, context, chat_id)
            elif data.startswith("settings_chat_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._settings_chat(update, context, chat_id)
            elif data.startswith("settings_rules_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._settings_rules(update, context, chat_id)
            elif data.startswith("settings_staff_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._settings_staff(update, context, chat_id)
            elif data.startswith("unban_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_unban(update, context, int(chat_id), int(target_id))
            elif data.startswith("unmute_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_unmute(update, context, int(chat_id), int(target_id))
            elif data.startswith("unwarn_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_unwarn(update, context, int(chat_id), int(target_id))
            elif data.startswith("verify_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_verify(update, context, int(chat_id), int(target_id))
            elif data.startswith("toggleprof_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._cb_toggle_profanity(update, context, chat_id)
            elif data.startswith("toggleappeals_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._cb_toggle_appeals(update, context, chat_id)
            elif data.startswith("settings_words_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._settings_words(update, context, chat_id)
            elif data.startswith("addword_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._cb_add_word_prompt(update, context, chat_id)
            elif data.startswith("rmword_"):
                _, chat_id, word = data.split("_", 2)
                await self._cb_remove_word(update, context, int(chat_id), word)
            elif data.startswith("appeal_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_appeal_request(update, context, int(chat_id), int(target_id))
            elif data.startswith("dmuser_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_dm_user_prompt(update, context, int(chat_id), int(target_id))
            elif data.startswith("assignmod_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._cb_assign_mod_prompt(update, context, chat_id)
            elif data.startswith("apacc_"):
                appeal_id = int(data.rsplit("_", 1)[1])
                await self._cb_appeal_decision(update, context, appeal_id, accept=True)
            elif data.startswith("aprej_"):
                appeal_id = int(data.rsplit("_", 1)[1])
                await self._cb_appeal_decision(update, context, appeal_id, accept=False)
            elif data.startswith("openappeal_"):
                appeal_id = int(data.rsplit("_", 1)[1])
                await self._cb_open_appeal(update, context, appeal_id)
            elif data == "my_appeal":
                await self.my_appeal_button(update, context)
            elif data.startswith("banlist_"):
                _, chat_id, page = data.split("_")
                await self._cb_restriction_list(update, context, int(chat_id), "ban", int(page))
            elif data.startswith("mutelist_"):
                _, chat_id, page = data.split("_")
                await self._cb_restriction_list(update, context, int(chat_id), "mute", int(page))
            elif data == "wtm_panel":
                await self._cb_panel_home(update, context)
            elif data == "wtm_chats":
                await self._cb_panel_chats(update, context)
            elif data == "wtm_addchat_prompt":
                await self._cb_panel_addchat_prompt(update, context)
            elif data.startswith("wtm_rmchat_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._cb_panel_rmchat(update, context, chat_id)
            elif data.startswith("wtm_chatsettings_"):
                chat_id = int(data.rsplit("_", 1)[1])
                await self._settings_chat(update, context, chat_id)
            elif data == "wtm_admins":
                await self._cb_panel_admins(update, context)
            elif data == "wtm_addadmin_prompt":
                await self._cb_panel_addadmin_prompt(update, context)
            elif data.startswith("wtm_rmadmin_"):
                target_id = int(data.rsplit("_", 1)[1])
                await self._cb_panel_rmadmin(update, context, target_id)
            elif data.startswith("infowarns_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_info_warns(update, context, int(chat_id), int(target_id))
            elif data.startswith("inforestrict_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_info_restrict(update, context, int(chat_id), int(target_id))
            elif data.startswith("infoban_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_info_ban(update, context, int(chat_id), int(target_id))
            elif data.startswith("inforights_"):
                _, chat_id, target_id = data.split("_")
                await self._cb_info_rights(update, context, int(chat_id), int(target_id))
            else:
                await query.answer()
        except Exception as e:
            logger.warning(f"Ошибка в callback: {e}", exc_info=True)
            try:
                await query.answer("Произошла ошибка.", show_alert=True)
            except TelegramError:
                pass

    async def _settings_chat(self, update, context, chat_id):
        query = update.callback_query
        user_id = query.from_user.id
        owner_id, _, _ = self.db.get_owner(chat_id)
        if user_id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        rules = self.db.get_rules(chat_id)
        staff = self.db.list_staff(chat_id)
        prof_on = self.db.get_profanity_filter(chat_id)
        appeals_on = self.db.get_appeals_enabled(chat_id)
        words = self.db.list_banned_words(chat_id)
        bans = self.db.list_restrictions(chat_id, "ban")
        mutes = self.db.list_restrictions(chat_id, "mute")
        kb = [
            [InlineKeyboardButton(f"📜 {'Изменить' if rules else 'Добавить'} правила", callback_data=f"settings_rules_{chat_id}")],
            [InlineKeyboardButton(f"🛡 Стафф ({len(staff)})", callback_data=f"settings_staff_{chat_id}")],
            [InlineKeyboardButton(f"🤬 Мат-фильтр: {'✅ Вкл' if prof_on else '❌ Выкл'}", callback_data=f"toggleprof_{chat_id}")],
            [InlineKeyboardButton(f"🚫 Запрещённые слова ({len(words)})", callback_data=f"settings_words_{chat_id}")],
            [InlineKeyboardButton(f"📮 Апелляции: {'✅ Вкл' if appeals_on else '❌ Выкл'}", callback_data=f"toggleappeals_{chat_id}")],
            [InlineKeyboardButton(f"🔨 Забаненные ({len(bans)})", callback_data=f"banlist_{chat_id}_0")],
            [InlineKeyboardButton(f"🔇 В муте ({len(mutes)})", callback_data=f"mutelist_{chat_id}_0")],
        ]
        if appeals_on:
            kb.append([InlineKeyboardButton("🛡 Назначить модератора", callback_data=f"assignmod_{chat_id}")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")])
        await query.message.edit_text(f"⚙️ Настройки\n\nПравила: {'✅' if rules else '❌'}\nСтафф: {len(staff)}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        await query.answer()

    async def _settings_rules(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        context.user_data["editing_rules"] = chat_id
        await query.message.edit_text("📜 Отправьте новый текст правил сообщением.")
        await query.answer()

    async def _settings_staff(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        staff = self.db.list_staff(chat_id)
        lines = ["🛡 Стафф группы\n"]
        if staff:
            for uid, name in staff:
                lines.append(f"• {user_link(uid, name or str(uid))}")
        else:
            lines.append("Стафф не назначен.")
        lines.append("\nКоманды в группе:\n/invstaff @user, /rmstaff @user")
        await query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"settings_chat_{chat_id}")]]), parse_mode=ParseMode.HTML)
        await query.answer()

    async def _cb_unban(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Только для модераторов.", show_alert=True)
            return
        try:
            await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        except TelegramError as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)
            return
        self.db.log_action(chat_id, target_id, "unban", query.from_user.id)
        self.db.remove_restriction(chat_id, target_id)
        await query.answer("Разбанен(а).")
        try:
            base = query.message.text_html or query.message.text or ""
            await query.message.edit_text(base + f"\n\n✅ Снято {tg_user_link(query.from_user)}.", parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

    async def _cb_unmute(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Только для модераторов.", show_alert=True)
            return
        try:
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=full_permissions())
        except TelegramError as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)
            return
        self.db.log_action(chat_id, target_id, "unmute", query.from_user.id)
        self.db.remove_restriction(chat_id, target_id)
        await query.answer("Мут снят.")
        try:
            base = query.message.text_html or query.message.text or ""
            await query.message.edit_text(base + f"\n\n✅ Снято {tg_user_link(query.from_user)}.", parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

    async def _cb_unwarn(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("Только для модераторов.", show_alert=True)
            return
        self.db.reset_warns(chat_id, target_id)
        self.db.log_action(chat_id, target_id, "unwarn", query.from_user.id)
        await query.answer("Предупреждения сняты.")
        try:
            base = query.message.text_html or query.message.text or ""
            await query.message.edit_text(base + f"\n\n✅ Снято {tg_user_link(query.from_user)}.", parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

    async def _cb_verify(self, update, context, chat_id, target_id):
        query = update.callback_query
        if query.from_user.id != target_id:
            await query.answer("Эта кнопка не для вас.", show_alert=True)
            return
        row = self.db.get_verification(chat_id, target_id)
        if not row:
            await query.answer("Проверка уже пройдена или истекла.", show_alert=True)
            return
        try:
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=full_permissions())
        except TelegramError as e:
            await query.answer(f"Ошибка: {e}", show_alert=True)
            return
        self.db.remove_verification(chat_id, target_id)
        await query.answer("Проверка пройдена!")
        try:
            await query.message.edit_text("✅ Проверка пройдена, добро пожаловать!")
        except TelegramError:
            pass
        rules = self.db.get_rules(chat_id)
        caption = f"<b>Правила группы:</b>\n\n<blockquote expandable>{html.escape(rules)}</blockquote>"
        await self._send_rules_card(query.message, caption)

    async def _cb_toggle_profanity(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        new_state = not self.db.get_profanity_filter(chat_id)
        self.db.set_profanity_filter(chat_id, new_state)
        await query.answer(f"Мат-фильтр {'включён' if new_state else 'выключен'}.")
        await self._settings_chat(update, context, chat_id)

    async def _cb_toggle_appeals(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        new_state = not self.db.get_appeals_enabled(chat_id)
        self.db.set_appeals_enabled(chat_id, new_state)
        await query.answer(f"Апелляции {'включены' if new_state else 'выключены'}.")
        await self._settings_chat(update, context, chat_id)

    async def _settings_words(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        words = self.db.list_banned_words(chat_id)
        lines = ["🚫 Запрещённые слова\n"]
        kb_rows = []
        if words:
            for w in words:
                lines.append(f"• {html.escape(w)}")
                kb_rows.append([InlineKeyboardButton(f"❌ Удалить: {w}", callback_data=f"rmword_{chat_id}_{w}")])
        else:
            lines.append("Список пуст.")
        kb_rows.append([InlineKeyboardButton("➕ Добавить слово", callback_data=f"addword_{chat_id}")])
        kb_rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"settings_chat_{chat_id}")])
        await query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)
        await query.answer()

    async def _cb_add_word_prompt(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        context.user_data["adding_banned_word"] = chat_id
        await query.message.edit_text("🚫 Отправьте слово (или несколько через запятую), которое нужно запретить.")
        await query.answer()

    async def _cb_remove_word(self, update, context, chat_id, word):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        self.db.remove_banned_word(chat_id, word)
        await query.answer("Удалено.")
        await self._settings_words(update, context, chat_id)

    async def _cb_appeal_request(self, update, context, chat_id, target_id):
        query = update.callback_query
        if query.from_user.id != target_id:
            await query.answer("Эта кнопка не для вас.", show_alert=True)
            return
        if not self.db.get_appeals_enabled(chat_id):
            await query.answer("Апелляции отключены.", show_alert=True)
            return
        if not self.db.user_known(target_id):
            await query.answer()
            deep_link = f"https://t.me/{self.bot_username}?start=appeal_{chat_id}"
            try:
                await query.message.reply_text(
                    "📮 Чтобы подать апелляцию, откройте бота в личных сообщениях и нажмите Start.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Открыть бота", url=deep_link)]]),
                )
            except TelegramError:
                pass
            return
        context.user_data["writing_appeal"] = chat_id
        await query.answer()
        try:
            await context.bot.send_message(target_id, "📮 Опишите одним сообщением, почему санкция была наложена ошибочно.")
        except TelegramError:
            await query.answer("Не удалось написать в ЛС.", show_alert=True)

    async def _cb_dm_user_prompt(self, update, context, chat_id, target_id):
        query = update.callback_query
        if not await self._can_moderate(chat_id, query.from_user.id):
            await query.answer("У вас нет прав.", show_alert=True)
            return
        context.user_data["dm_target"] = (chat_id, target_id)
        await query.answer()
        try:
            await context.bot.send_message(query.from_user.id, "✉️ Напишите одним сообщением текст, который нужно отправить пользователю.")
        except TelegramError:
            await query.answer(f"Сначала напишите мне в ЛС: @{self.bot_username}", show_alert=True)

    async def _cb_assign_mod_prompt(self, update, context, chat_id):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        context.user_data["assigning_mod"] = chat_id
        await query.message.edit_text("🛡 Отправьте @username или ID пользователя, которого назначить модератором.")
        await query.answer()

    async def _can_decide_appeal(self, chat_id, user_id):
        owner_id, _, _ = self.db.get_owner(chat_id)
        if user_id == owner_id or self.db.is_staff(chat_id, user_id) or self.db.is_helper(chat_id, user_id):
            return True
        return await self._can_moderate(chat_id, user_id)

    async def _cb_appeal_decision(self, update, context, appeal_id, accept):
        query = update.callback_query
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            await query.answer("Апелляция не найдена.", show_alert=True)
            return
        _, chat_id, user_id, appeal_text, status = appeal
        if status != "pending":
            await query.answer("Эта апелляция уже рассмотрена.", show_alert=True)
            return
        if not await self._can_decide_appeal(chat_id, query.from_user.id):
            await query.answer("У вас нет прав решать апелляции.", show_alert=True)
            return
        restriction = self.db.get_restriction(chat_id, user_id)
        if accept:
            self.db.set_appeal_status(appeal_id, "accepted", query.from_user.id)
            if restriction:
                rtype = restriction[0]
                try:
                    if rtype == "ban":
                        await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
                    else:
                        await context.bot.restrict_chat_member(chat_id, user_id, permissions=full_permissions())
                except TelegramError:
                    pass
                self.db.log_action(chat_id, user_id, f"unban" if rtype == "ban" else "unmute", query.from_user.id, "апелляция принята")
                self.db.remove_restriction(chat_id, user_id)
            await query.answer("Ограничение снято.")
            try:
                await context.bot.send_message(user_id, "✅ Ваша апелляция принята, ограничение снято.")
            except TelegramError:
                pass
        else:
            self.db.set_appeal_status(appeal_id, "rejected", query.from_user.id)
            if restriction:
                self.db.set_restriction_appeal_status(chat_id, user_id, "rejected")
            await query.answer("Апелляция отклонена.")
            try:
                await context.bot.send_message(user_id, "❌ Ваша апелляция отклонена.")
            except TelegramError:
                pass
        try:
            base = query.message.text_html or query.message.text or ""
            decision = "✅ Принято" if accept else "❌ Отклонено"
            await query.message.edit_text(base + f"\n\n{decision} — {tg_user_link(query.from_user)}", parse_mode=ParseMode.HTML)
        except TelegramError:
            pass

    async def _cb_open_appeal(self, update, context, appeal_id):
        query = update.callback_query
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            await query.answer("Апелляция не найдена.", show_alert=True)
            return
        _, chat_id, user_id, appeal_text, status = appeal
        if not await self._can_decide_appeal(chat_id, query.from_user.id):
            await query.answer("У вас нет прав.", show_alert=True)
            return
        restriction = self.db.get_restriction(chat_id, user_id)
        rtype = restriction[0] if restriction else "—"
        rreason = restriction[2] if restriction else None
        text = (
            f"📮 Апелляция\nПользователь: {user_id}\nОграничение: {'бан' if rtype == 'ban' else 'мут' if rtype == 'mute' else rtype}\n"
            f"Причина: {html.escape(rreason) if rreason else '—'}\n\nТекст: {html.escape(appeal_text)}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Снять ограничение", callback_data=f"apacc_{appeal_id}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"aprej_{appeal_id}")],
        ]) if status == "pending" else None
        await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        await query.answer()

    async def cmd_helper(self, update, context):
        if update.effective_chat.type != ChatType.PRIVATE:
            await update.message.reply_text("Эта команда работает только в ЛС с ботом.")
            return
        user_id = update.effective_user.id
        helper_chats = [cid for (cid,) in self.db.get_helper_chats(user_id)]
        owned_chats = [cid for cid, _ in self.db.get_owned_chats(user_id)]
        chats = set(helper_chats) | set(owned_chats)
        if not chats:
            await update.message.reply_text("У вас нет прав рассматривать апелляции.")
            return
        lines = ["🛡 Открытые апелляции\n"]
        kb_rows = []
        for chat_id in chats:
            for appeal_id, uid, text, created_at in self.db.list_open_appeals(chat_id):
                lines.append(f"• #{appeal_id} от {uid}")
                kb_rows.append([InlineKeyboardButton(f"Открыть апелляцию #{appeal_id}", callback_data=f"openappeal_{appeal_id}")])
        if not kb_rows:
            lines.append("Открытых апелляций нет.")
        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else None)

    async def _cb_restriction_list(self, update, context, chat_id, rtype, page):
        query = update.callback_query
        owner_id, _, _ = self.db.get_owner(chat_id)
        if query.from_user.id != owner_id:
            await query.answer("Только владелец.", show_alert=True)
            return
        items = self.db.list_restrictions(chat_id, rtype)
        page_size = 10
        start = page * page_size
        page_items = items[start:start + page_size]
        title = "🔨 Забаненные" if rtype == "ban" else "🔇 В муте"
        action_prefix = "unban" if rtype == "ban" else "unmute"
        action_label = "🔓 Разбанить" if rtype == "ban" else "🔊 Снять мут"
        list_prefix = "banlist" if rtype == "ban" else "mutelist"
        lines = [f"{title} ({len(items)})\n"]
        kb_rows = []
        if not page_items:
            lines.append("Список пуст.")
        for user_id, name, reason, until in page_items:
            lines.append(f"• {name or user_id}" + (f" — {html.escape(reason)}" if reason else ""))
            kb_rows.append([InlineKeyboardButton(f"{action_label}: {name or user_id}", callback_data=f"{action_prefix}_{chat_id}_{user_id}")])
        nav_row = []
        if start > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"{list_prefix}_{chat_id}_{page-1}"))
        if start + page_size < len(items):
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"{list_prefix}_{chat_id}_{page+1}"))
        if nav_row:
            kb_rows.append(nav_row)
        kb_rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"settings_chat_{chat_id}")])
        await query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML)
        await query.answer()

    async def private_text_handler(self, update, context):
        text = update.message.text
        if not text:
            return
        self.db.mark_pm_user(update.effective_user.id)
        if context.user_data.get("wtm_adding_chat") and self.is_panel_admin(update.effective_user.id):
            context.user_data.pop("wtm_adding_chat")
            ident = text.strip()
            try:
                chat_id = int(ident)
            except ValueError:
                await update.message.reply_text("Нужен числовой ID чата/канала.")
                return
            try:
                chat = await context.bot.get_chat(chat_id)
                title = chat.title or str(chat_id)
            except TelegramError:
                title = str(chat_id)
            self.db.add_allowed_chat(chat_id, title, update.effective_user.id)
            await update.message.reply_text(f"✅ Чат «{html.escape(title)}» разрешён для модерации.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wtm_chats")]]))
            return
        if context.user_data.get("wtm_adding_admin") and self.is_panel_admin(update.effective_user.id):
            context.user_data.pop("wtm_adding_admin")
            ident = text.strip()
            try:
                target_id = int(ident)
            except ValueError:
                await update.message.reply_text("Нужен числовой Telegram ID пользователя.")
                return
            self.db.add_panel_admin(target_id, update.effective_user.id)
            await update.message.reply_text(f"✅ Пользователю {target_id} выдан доступ.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wtm_admins")]]))
            return
        if "editing_rules" in context.user_data:
            chat_id = context.user_data.pop("editing_rules")
            owner_id, _, _ = self.db.get_owner(chat_id)
            if owner_id != update.effective_user.id:
                await update.message.reply_text("Только владелец.")
                return
            self.db.set_rules(chat_id, str(chat_id), text)
            await update.message.reply_text("✅ Правила сохранены.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"settings_chat_{chat_id}")]]))
            return
        if "adding_banned_word" in context.user_data:
            chat_id = context.user_data.pop("adding_banned_word")
            owner_id, _, _ = self.db.get_owner(chat_id)
            if owner_id != update.effective_user.id:
                await update.message.reply_text("Только владелец.")
                return
            words = [w.strip() for w in text.split(",") if w.strip()]
            for w in words:
                self.db.add_banned_word(chat_id, w, update.effective_user.id)
            await update.message.reply_text(f"✅ Добавлено слов: {len(words)}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"settings_words_{chat_id}")]]))
            return
        if "assigning_mod" in context.user_data:
            chat_id = context.user_data.pop("assigning_mod")
            owner_id, _, _ = self.db.get_owner(chat_id)
            if owner_id != update.effective_user.id:
                await update.message.reply_text("Только владелец.")
                return
            ident = text.strip()
            row = self.db.find_user(chat_id, ident) or self.db.find_user_global(ident)
            target_id = None
            if row:
                target_id = row[0]
            elif ident.lstrip("-").isdigit():
                target_id = int(ident)
            if not target_id:
                await update.message.reply_text("Пользователь не найден.")
                return
            self.db.add_helper(chat_id, target_id, update.effective_user.id)
            await update.message.reply_text("✅ Модератор назначен.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=f"settings_chat_{chat_id}")]]))
            try:
                await context.bot.send_message(target_id, "🛡 Вас назначили модератором для рассмотрения апелляций. Используйте /helper.")
            except TelegramError:
                pass
            return
        if "dm_target" in context.user_data:
            chat_id, target_id = context.user_data.pop("dm_target")
            if not await self._can_moderate(chat_id, update.effective_user.id):
                await update.message.reply_text("У вас нет прав.")
                return
            try:
                await context.bot.send_message(target_id, text)
            except TelegramError:
                await update.message.reply_text("⚠️ Не удалось отправить.")
                return
            await update.message.reply_text("✅ Сообщение отправлено.")
            return
        if "writing_appeal" in context.user_data:
            chat_id = context.user_data.pop("writing_appeal")
            user = update.effective_user
            restriction = self.db.get_restriction(chat_id, user.id)
            if not restriction:
                await update.message.reply_text("У вас нет активных ограничений.")
                return
            if restriction[4] == "rejected":
                await update.message.reply_text("Апелляция уже отклонена.")
                return
            if self.db.get_open_appeal(chat_id, user.id):
                await update.message.reply_text("Апелляция уже на рассмотрении.")
                return
            appeal_id = self.db.add_appeal(chat_id, user.id, text)
            self.db.set_restriction_appeal_status(chat_id, user.id, "pending")
            recipients = set()
            owner_id, _, _ = self.db.get_owner(chat_id)
            if owner_id:
                recipients.add(owner_id)
            for uid, _ in self.db.list_helpers(chat_id):
                recipients.add(uid)
            chat_title = None
            try:
                chat = await context.bot.get_chat(chat_id)
                chat_title = chat.title
            except TelegramError:
                pass
            rtype, rname, rreason, _, _ = restriction
            appeal_text = (
                f"📮 Новая апелляция\nГруппа: {html.escape(chat_title or str(chat_id))}\n"
                f"От: {tg_user_link(user)}\nОграничение: {'бан' if rtype == 'ban' else 'мут'}\n"
                f"Причина: {html.escape(rreason) if rreason else '—'}\n\nТекст: {html.escape(text)}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Снять ограничение", callback_data=f"apacc_{appeal_id}")],
                [InlineKeyboardButton("❌ Отклонить", callback_data=f"aprej_{appeal_id}")],
            ])
            sent_any = False
            for uid in recipients:
                try:
                    await context.bot.send_message(uid, appeal_text, parse_mode=ParseMode.HTML, reply_markup=kb)
                    sent_any = True
                except TelegramError:
                    continue
            if sent_any:
                await update.message.reply_text("✅ Апелляция отправлена.")
            else:
                await update.message.reply_text("Не удалось доставить апелляцию.")
            return
        await update.message.reply_text("Не понял. Используйте /help.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Меню", callback_data="start_menu")]]))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SERVICE_NAME = "wt2x2-emir"
SERVICE_PATH = f"/etc/systemd/system/{SERVICE_NAME}.service"

def _load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _ask(prompt, validator=None, error_msg="Некорректное значение, попробуйте ещё раз."):
    while True:
        value = input(prompt).strip()
        if not value:
            print("Значение не может быть пустым.")
            continue
        if validator and not validator(value):
            print(error_msg)
            continue
        return value

def _is_valid_token(t):
    parts = t.split(":")
    return len(parts) == 2 and parts[0].isdigit() and len(parts[1]) >= 30

def _is_valid_id(t):
    return t.lstrip("-").isdigit()

def _install_systemd():
    import subprocess, sys as _sys
    if os.geteuid() != 0:
        print("\n⚠ Чтобы бот работал в фоне, перезапустите с правами root: sudo python3 " + os.path.basename(__file__))
        return False
    unit = f"""[Unit]
Description=wT2x2 Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={BASE_DIR}
ExecStart={_sys.executable} {os.path.abspath(__file__)}
Restart=on-failure
RestartSec=5
StandardOutput=append:{os.path.join(BASE_DIR, 'bot.log')}
StandardError=append:{os.path.join(BASE_DIR, 'bot.log')}

[Install]
WantedBy=multi-user.target
"""
    with open(SERVICE_PATH, "w", encoding="utf-8") as f:
        f.write(unit)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", SERVICE_NAME], check=False)
    subprocess.run(["systemctl", "restart", SERVICE_NAME], check=False)
    print(f"\n✓ systemd-сервис '{SERVICE_NAME}' установлен.")
    return True

def run_first_setup_wizard():
    print("=== Первичная настройка wT2x2 бота ===\n")
    token = _ask("Токен бота (от @BotFather): ", _is_valid_token, "Неверный формат токена.")
    admin_id_raw = _ask("Ваш Telegram ID: ", _is_valid_id, "ID должен быть числом.")
    crypto_token = input("CryptoPay токен (Enter — пропустить): ").strip()
    cfg = {"bot_token": token, "admin_ids": [int(admin_id_raw)], "crypto_token": crypto_token}
    _save_config(cfg)
    print(f"\n✓ Конфигурация сохранена в {CONFIG_PATH}")
    installed = _install_systemd()
    if installed:
        raise SystemExit(0)
    return cfg

_cfg = _load_config()
if not _cfg.get("bot_token"):
    import sys as _sys_mod
    if _sys_mod.stdin.isatty():
        _cfg = run_first_setup_wizard()
    else:
        raise SystemExit("Бот не настроен. Запустите вручную: python3 " + os.path.basename(__file__))

TOKEN = _cfg.get("bot_token")
CRYPTO_TOKEN = _cfg.get("crypto_token") or ""
ADMIN_ID = _cfg.get("admin_ids") or []

moderator = WT2X2Moderator(super_admins=ADMIN_ID)

BROADCAST_MSG = 1
FULL_CODE_ADD = 2
FULL_MEDIA_ADD = 3
FULL_CODE_GET = 4
SUGGEST_WAIT_INPUT = 5
DONATE_AMOUNT_WAIT = 6
ADMIN_SET_LIMIT_WAIT = 7
ADMIN_SET_IMAGE_WAIT = 8
ADMIN_REPLY_WAIT = 9
ADMIN_SET_AUTOREPLY_WAIT = 10
ADMIN_SET_RULES_TEXT_WAIT = 11

GAME_DATA = {
    "🎲": {"win": [6]},
    "🎯": {"win": [6]},
    "🏀": {"win": [4, 5]},
    "⚽": {"win": [3, 4, 5]},
    "🎳": {"win": [6]},
    "🎰": {"win": [1, 22, 43, 64]}
}

EMIR_DB_PATH = os.path.join(BASE_DIR, "emir.db")

def get_emir_conn():
    conn = sqlite3.connect(EMIR_DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn

def init_db():
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
    c.execute('CREATE TABLE IF NOT EXISTS stats (action TEXT PRIMARY KEY, count INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS fulls (code TEXT PRIMARY KEY, from_chat_id INTEGER, message_id INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS game_limits (user_id INTEGER PRIMARY KEY, plays INTEGER, reset_time REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS bot_data (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("daily_attempts", 1)')
    conn.commit()
    conn.close()

def get_main_image():
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM bot_data WHERE key = "main_image"')
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def set_main_image(file_id):
    conn = get_emir_conn()
    c = conn.cursor()
    if file_id:
        c.execute('INSERT OR REPLACE INTO bot_data (key, value) VALUES ("main_image", ?)', (file_id,))
    else:
        c.execute('DELETE FROM bot_data WHERE key = "main_image"')
    conn.commit()
    conn.close()

def get_auto_reply():
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM bot_data WHERE key = "auto_reply_chat_id"')
    chat_id = c.fetchone()
    c.execute('SELECT value FROM bot_data WHERE key = "auto_reply_msg_id"')
    msg_id = c.fetchone()
    conn.close()
    if chat_id and msg_id:
        return int(chat_id[0]), int(msg_id[0])
    return None, None

def set_auto_reply(chat_id, msg_id):
    conn = get_emir_conn()
    c = conn.cursor()
    if chat_id and msg_id:
        c.execute('INSERT OR REPLACE INTO bot_data (key, value) VALUES ("auto_reply_chat_id", ?)', (str(chat_id),))
        c.execute('INSERT OR REPLACE INTO bot_data (key, value) VALUES ("auto_reply_msg_id", ?)', (str(msg_id),))
    else:
        c.execute('DELETE FROM bot_data WHERE key IN ("auto_reply_chat_id", "auto_reply_msg_id")')
    conn.commit()
    conn.close()

DEFAULT_AUTOREPLY_RULES_TEXT = (
    "📜 ПРАВИЛА ЧАТА\n"
    "🎯 Тема: Только по делу. Оффтоп — нельзя\n"
    "🚫 Табу: Никакой политики, религии, шока и NSFW.\n"
    "🤝 Уважение: Без оскорблений команды и участников.\n"
    "💬 Чистота: Без спама. Стикеры — только 7tv.\n"
    "👉 Наш чат - @twitch_narezki_chat\n"
    "👉 Наш бот - @wT2x2_bot"
)

def get_autoreply_rules_text():
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM bot_data WHERE key = "autoreply_rules_text"')
    res = c.fetchone()
    conn.close()
    return res[0] if res else DEFAULT_AUTOREPLY_RULES_TEXT

def set_autoreply_rules_text(text):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO bot_data (key, value) VALUES ("autoreply_rules_text", ?)', (text,))
    conn.commit()
    conn.close()

def get_max_attempts():
    if get_mishka_enabled():
        return MISHKA_ATTEMPTS
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = "daily_attempts"')
    val = c.fetchone()[0]
    conn.close()
    return val

def set_max_attempts(val):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('UPDATE settings SET value = ? WHERE key = "daily_attempts"', (val,))
    conn.commit()
    conn.close()

def get_mishka_enabled():
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = "mishka_enabled"')
    row = c.fetchone()
    conn.close()
    return bool(row[0]) if row else False

def set_mishka_enabled(val):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("mishka_enabled", ?)', (1 if val else 0,))
    conn.commit()
    conn.close()

MISHKA_ATTEMPTS = 3

def reset_all_limits():
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('DELETE FROM game_limits')
    conn.commit()
    conn.close()

def can_play(user_id):
    max_plays = get_max_attempts()
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT plays, reset_time FROM game_limits WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    now = time.time()
    if row:
        plays, reset_time = row
        if now > reset_time:
            return True, reset_time, max_plays
        elif plays < max_plays:
            return True, reset_time, max_plays - plays
        else:
            return False, reset_time, 0
    return True, 0, max_plays

def record_play(user_id):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT plays, reset_time FROM game_limits WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    now = time.time()
    is_first_play = False
    reset_time = now + 86400
    if row:
        plays, old_reset_time = row
        if now > old_reset_time:
            c.execute('UPDATE game_limits SET plays = 1, reset_time = ? WHERE user_id = ?', (reset_time, user_id))
            is_first_play = True
        else:
            c.execute('UPDATE game_limits SET plays = plays + 1 WHERE user_id = ?', (user_id,))
            reset_time = old_reset_time
    else:
        c.execute('INSERT INTO game_limits (user_id, plays, reset_time) VALUES (?, 1, ?)', (user_id, reset_time))
        is_first_play = True
    conn.commit()
    conn.close()
    return is_first_play, reset_time

def add_user(user_id):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def log_stat(action):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('INSERT INTO stats (action, count) VALUES (?, 1) ON CONFLICT(action) DO UPDATE SET count = count + 1', (action,))
    conn.commit()
    conn.close()

async def notify_restored(context, user_id, wait_time):
    await asyncio.sleep(wait_time)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Играть", callback_data="games")]])
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 <b>Твои попытки для казино обновились!</b>\nЗаходи и испытай удачу снова.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    except:
        pass

async def show_main_menu(update, context, is_callback=False):
    file_id = get_main_image()
    text = "<b>Главное меню:</b>\n\n"
    user_id = update.effective_user.id if update.effective_user else None
    has_appeal_button = bool(user_id and moderator.db.get_user_active_restriction(user_id))
    kb = startt(has_appeal_button)
    if is_callback:
        query = update.callback_query
        if query.message.photo and not file_id:
            await query.message.delete()
            await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=kb, parse_mode="HTML")
        elif file_id:
            if query.message.photo:
                try: await query.edit_message_caption(caption=text, reply_markup=kb, parse_mode="HTML")
                except: pass
            else:
                await query.message.delete()
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=file_id, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            try: await query.edit_message_text(text=text, reply_markup=kb, parse_mode="HTML")
            except: pass
    else:
        if file_id:
            await update.message.reply_photo(photo=file_id, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await update.message.reply_text(text=text, reply_markup=kb, parse_mode="HTML")

async def show_text_menu(query, context, text, kb):
    if query.message.photo:
        try:
            await query.edit_message_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        except TelegramError:
            pass
    else:
        try: await query.edit_message_text(text=text, reply_markup=kb, parse_mode="HTML")
        except TelegramError: pass

def startt(show_appeal=False):
    keyboard = [
        [InlineKeyboardButton("✍️ Предложка", callback_data="suggest")],
        [
            InlineKeyboardButton("💸 Купить рекламу", callback_data="pay_ad"),
            InlineKeyboardButton("🎮 Игры", callback_data="games")
        ],
        [InlineKeyboardButton("🔥 Получить фулл", callback_data="full")],
        [
            InlineKeyboardButton("🎁 Донат", callback_data="donate"),
            InlineKeyboardButton("ℹ️ Информация", callback_data="info")
        ]
    ]
    if show_appeal:
        keyboard.append([InlineKeyboardButton("📮 Подать апелляцию по нарушению", callback_data="my_appeal")])
    return InlineKeyboardMarkup(keyboard)

def games_kb(prefix="play"):
    keyboard = [
        [InlineKeyboardButton("🎲 Кубик", callback_data=f"{prefix}_🎲"), InlineKeyboardButton("🎯 Дротик", callback_data=f"{prefix}_🎯")],
        [InlineKeyboardButton("🏀 Баскет", callback_data=f"{prefix}_🏀"), InlineKeyboardButton("⚽ Футбол", callback_data=f"{prefix}_⚽")],
        [InlineKeyboardButton("🎳 Боулинг", callback_data=f"{prefix}_🎳"), InlineKeyboardButton("🎰 Казино", callback_data=f"{prefix}_🎰")],
        [InlineKeyboardButton("« Назад", callback_data="admin_panel" if prefix == "aplay" else "startt")]
    ]
    return InlineKeyboardMarkup(keyboard)

def pay_add():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Написать по рекламе", url="https://t.me/nirexen")], [InlineKeyboardButton("« Назад", callback_data="startt")]])

def infoo():
    return InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="startt")]])

def donatee():
    keyboard = [
        [InlineKeyboardButton("💎 CryptoPay", callback_data="cryptopay"), InlineKeyboardButton("❤️ DonatePay", url="https://new.donatepay.ru/@TWITCH_NAREZKI_T2X2")],
        [InlineKeyboardButton("« Назад", callback_data="startt")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_kb():
    max_plays = get_max_attempts()
    mishka_on = get_mishka_enabled()
    keyboard = [
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("➕ Добавить фулл", callback_data="admin_add_full"),
         InlineKeyboardButton("🖼 Изменить фото", callback_data="admin_set_image")],
        [InlineKeyboardButton("📝 Настроить автоответ", callback_data="admin_set_autoreply")],
        [InlineKeyboardButton("✏️ Текст правил (авто-ответ)", callback_data="admin_set_rules_text")],
        [InlineKeyboardButton("🎮 Игры (Безлимит)", callback_data="admin_games")],
        [InlineKeyboardButton(f"🧸 Мишка: {'Вкл ✅' if mishka_on else 'Выкл ❌'}", callback_data="admin_toggle_mishka")],
        [InlineKeyboardButton(f"⚙️ Лимит: {max_plays}/сут", callback_data="admin_set_limit"),
         InlineKeyboardButton("🔄 Сброс попыток", callback_data="admin_reset_limits")],
        [InlineKeyboardButton("🛡 wT2x2 Moderator", callback_data="wtm_panel")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def play_game_logic(update, context, emoji, is_admin):
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id, emoji=emoji)
    game_info = GAME_DATA.get(emoji, {"win": [6]})
    value = dice_msg.dice.value
    admin_tag = "👑 Админ: " if is_admin else ""
    user = update.effective_user
    username = f"@{user.username}" if user.username else f"ID {user.id}"
    if value in game_info["win"]:
        text = f"{admin_tag}🎉 Ты <b>выиграл!</b> (выпало: {value})"
        if not is_admin and emoji == "🎰" and get_mishka_enabled():
            text += "\n\n🧸 Приз: 15 ⭐ — напиши администратору, чтобы получить приз!"
            for aid in ADMIN_ID:
                try:
                    await context.bot.send_message(
                        chat_id=aid,
                        text=f"🎰 <b>Победа в казино!</b>\nЮзер: {username}\nID: <code>{user.id}</code>\nИгра: {emoji} (Выпало: {value})",
                        parse_mode="HTML"
                    )
                except: pass
        await dice_msg.reply_text(text, parse_mode="HTML")
    else:
        await asyncio.sleep(3)
        try: await dice_msg.delete()
        except: pass

async def chat_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if getattr(update.message, 'is_automatic_forward', False):
        auto_chat_id, auto_msg_id = get_auto_reply()
        try:
            if auto_chat_id and auto_msg_id:
                await context.bot.copy_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=auto_chat_id,
                    message_id=auto_msg_id,
                    reply_to_message_id=update.message.message_id
                )
            else:
                rules_text = get_autoreply_rules_text()
                await update.message.reply_text(rules_text, reply_to_message_id=update.message.message_id)
        except:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    add_user(update.effective_user.id)
    log_stat("cmd_start")
    args = context.args
    if args and args[0].startswith("appeal_"):
        await moderator.handle_appeal_deeplink(update, context, args[0])
        return
    if args and args[0].startswith("rules_"):
        await moderator.handle_rules_deeplink(update, context, args[0])
        return
    await show_main_menu(update, context, is_callback=False)

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    if uid in ADMIN_ID:
        await update.message.reply_text("👑 <b>Админ панель:</b>", reply_markup=admin_kb(), parse_mode="HTML")
    elif moderator.is_panel_admin(uid):
        await update.message.reply_text("🛡 <b>Панель модерации:</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛡 wT2x2 Moderator", callback_data="wtm_panel")]]), parse_mode="HTML")

async def obrabotka(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await _obrabotka_impl(update, context)
    except Exception as e:
        logging.getLogger(__name__).error("Ошибка в obrabotka: %s", e, exc_info=True)
        try:
            await query.answer("⚠️ Произошла ошибка, попробуйте ещё раз.", show_alert=False)
        except TelegramError:
            pass

async def _obrabotka_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    try:
        await query.answer()
    except:
        pass

    mod_callbacks = {
        "help_commands", "help_about", "start_menu", "confirm_owner_", "my_appeal",
        "wtm_panel", "wtm_chats", "wtm_addchat_prompt", "wtm_admins", "wtm_addadmin_prompt"
    }
    mod_prefixes = ("wtm_", "settings_", "unban_", "unmute_", "unwarn_", "verify_", 
                    "toggleprof_", "toggleappeals_", "addword_", "rmword_", "appeal_", 
                    "dmuser_", "banlist_", "mutelist_", "infowarns_", "inforestrict_", 
                    "infoban_", "inforights_", "apacc_", "aprej_", "assignmod_", "openappeal_")

    if data in mod_callbacks or data.startswith(mod_prefixes):
        await moderator.callback_handler(update, context)
        return

    if data == "games" or data.startswith("play_") or data.startswith("aplay_"):
        if query.message.chat.type != "private":
            await query.answer("❌ Игры работают только в ЛС с ботом!", show_alert=True)
            return
        log_stat(f"btn_{data}")
        if data.startswith("play_"):
            emoji = data.split("_")[1]
            if emoji == "🎰":
                can_roll, reset_time, plays_left = can_play(user_id)
                if not can_roll:
                    msk_time = datetime.fromtimestamp(reset_time + 10800).strftime('%d.%m.%Y в %H:%M')
                    await query.answer(f"⏳ Попытки закончились!\nОбновление: {msk_time} МСК", show_alert=True)
                    return
                is_first_play, reset_time = record_play(user_id)
                if is_first_play:
                    wait_time = reset_time - time.time()
                    asyncio.create_task(notify_restored(context, user_id, wait_time))
            await play_game_logic(update, context, emoji, is_admin=False)
            return
        elif data.startswith("aplay_"):
            if user_id not in ADMIN_ID:
                await query.answer("Нет доступа.", show_alert=True)
                return
            emoji = data.split("_")[1]
            await play_game_logic(update, context, emoji, is_admin=True)
            return

    if data == "admin_reset_limits":
        if user_id not in ADMIN_ID:
            await query.answer("Нет доступа.", show_alert=True)
            return
        reset_all_limits()
        await query.answer("✅ Всем пользователям сброшены попытки!", show_alert=True)
        return

    if data == "admin_toggle_mishka":
        if user_id not in ADMIN_ID:
            await query.answer("Нет доступа.", show_alert=True)
            return
        set_mishka_enabled(not get_mishka_enabled())
        await query.answer("✅ Режим 'Мишка' переключён.")
        try:
            await query.edit_message_reply_markup(reply_markup=admin_kb())
        except TelegramError:
            pass
        return

    if data == "startt":
        await show_main_menu(update, context, is_callback=True)
        return

    if data == "info":
        text = (
            f"<b>ℹ️ Информация</b>\n\n"
            f"Это официальный бот нарезчика @nirexen...\n"
            f"👉 ЛС нарезчика - @nirexen\n"
            f"👉 Основной канал - <a href='https://www.youtube.com/@wT2x2'>тык</a>\n"
            f"👉 Резервный канал - <a href='https://www.youtube.com/@twitch_t2x2'>тык</a>\n"
            f"👉 Наш Телеграм Канал - @wT2x2"
        )
        await show_text_menu(query, context, text, infoo())
        return

    if data == "games":
        max_plays = get_max_attempts()
        if get_mishka_enabled():
            text = f"<b>🎮 Выбери игру:</b>\n\n🎰 Казино: доступно попыток: {max_plays}.\n🧸 Приз: 15 ⭐"
        else:
            text = f"<b>🎮 Выбери игру:</b>\n\n🎰 Казино: доступно попыток: {max_plays}."
        await show_text_menu(query, context, text, games_kb("play"))
        return

    if data == "admin_panel":
        if user_id in ADMIN_ID:
            await show_text_menu(query, context, "👑 <b>Админ панель:</b>", admin_kb())
        return

    if data == "admin_games":
        if user_id in ADMIN_ID:
            await show_text_menu(query, context, "🎮 <b>Безлимитные игры админа:</b>", games_kb("aplay"))
        return

    if data == "pay_ad":
        text = (
            f"<b>📊 Рекламные тарифы:</b>\n\n"
            f"🔹 900 ₽ - формат 1/24\n"
            f"🔹 1 100 ₽ - формат 1/24 + напоминание\n"
            f"🔹 +400 ₽ - закреп"
        )
        await show_text_menu(query, context, text, pay_add())
        return

    if data == "donate":
        await show_text_menu(query, context, "Нравятся нарезки? Ты можешь скинуть мне денек на еду в подвал😋", donatee())
        return

    if data == "admin_stats":
        if user_id in ADMIN_ID:
            await admin_stats_callback(update, context)
        return

    await query.answer("Неизвестная команда.", show_alert=False)

def get_pretty_action_name(action):
    names = {
        "cmd_start": "Команда /start", "btn_suggest": "✍️ Предложка", "btn_pay_ad": "💸 Купить рекламу",
        "btn_full": "🔥 Получить фулл", "btn_donate": "🎁 Донат", "btn_info": "ℹ️ Информация",
        "btn_startt": "🔙 Назад", "btn_cryptopay": "💎 CryptoPay",
        "btn_admin_broadcast": "📢 Рассылка", "btn_admin_stats": "📊 Статистика",
        "btn_admin_add_full": "➕ Добавить фулл", "btn_admin_panel": "👑 Админ панель",
        "btn_games": "🎮 Игры", "btn_admin_games": "🎮 Безлимитные игры",
        "btn_cancel_full": "❌ Отмена фулла", "btn_cancel_suggest": "❌ Отмена предложки",
        "btn_cancel_donate": "❌ Отмена доната", "btn_admin_set_image": "🖼 Изменить фото",
        "btn_admin_cancel": "❌ Отмена", "btn_admin_reset_limits": "🔄 Сброс попыток",
        "btn_admin_set_autoreply": "📝 Автоответ"
    }
    if action in names: return names[action]
    if action.startswith("btn_play_"): return f"🕹 Игра: {action.split('_')[-1]}"
    if action.startswith("game_"): return f"🎲 Сыграно: {action.split('_')[-1]}"
    if action.startswith("btn_aplay_"): return f"👑 Админ играет: {action.split('_')[-1]}"
    return action

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    users_count = c.fetchone()[0]
    c.execute('SELECT action, count FROM stats')
    stats = c.fetchall()
    conn.close()
    text = f"📊 <b>Статистика:</b>\n👥 Юзеров: <b>{users_count}</b>\n\n<b>Клики:</b>\n"
    for action, count in stats:
        text += f"▪️ {get_pretty_action_name(action)}: {count}\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="admin_panel")]])
    await show_text_menu(query, context, text, kb)

async def admin_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_text_menu(query, context, "👑 <b>Админ панель:</b>", admin_kb())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END

async def autoreply_set_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return ConversationHandler.END
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    text = "📝 Отправь сообщение для автоответа.\nИли отправь <code>0</code>, чтобы вернуть стандартный текст."
    await show_text_menu(query, context, text, kb)
    return ADMIN_SET_AUTOREPLY_WAIT

async def autoreply_set_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "0":
        set_auto_reply(None, None)
        await update.message.reply_text("✅ Автоответ сброшен.")
    else:
        set_auto_reply(update.effective_chat.id, update.message.message_id)
        await update.message.reply_text("✅ Автоответ сохранён!")
    return ConversationHandler.END

async def rules_text_set_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return ConversationHandler.END
    await query.answer()
    current = get_autoreply_rules_text()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    text = f"✏️ Текущий текст правил:\n\n{current}\n\nПришли новый текст или <code>0</code> для сброса."
    await show_text_menu(query, context, text, kb)
    return ADMIN_SET_RULES_TEXT_WAIT

async def rules_text_set_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() == "0":
        set_autoreply_rules_text(DEFAULT_AUTOREPLY_RULES_TEXT)
        await update.message.reply_text("✅ Текст правил сброшен.")
    else:
        set_autoreply_rules_text(update.message.text)
        await update.message.reply_text("✅ Текст правил обновлён.")
    return ConversationHandler.END

async def image_set_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return ConversationHandler.END
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    await show_text_menu(query, context, "🖼 Отправь ФОТО для меню или <code>0</code> чтобы удалить.", kb)
    return ADMIN_SET_IMAGE_WAIT

async def image_set_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "0":
        set_main_image(None)
        await update.message.reply_text("✅ Фото удалено.")
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        set_main_image(file_id)
        await update.message.reply_text("✅ Фото меню обновлено!")
    else:
        await update.message.reply_text("❌ Это не фото.")
        return ADMIN_SET_IMAGE_WAIT
    return ConversationHandler.END

async def set_limit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return ConversationHandler.END
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    await show_text_menu(query, context, "⚙️ Введите количество попыток для Казино в сутки:", kb)
    return ADMIN_SET_LIMIT_WAIT

async def set_limit_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val <= 0: raise ValueError
        set_max_attempts(val)
        await update.message.reply_text(f"✅ Лимит изменен на <b>{val}</b> в сутки.", parse_mode="HTML")
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return ADMIN_SET_LIMIT_WAIT
    return ConversationHandler.END

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return ConversationHandler.END
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    await show_text_menu(query, context, "📢 Отправь пост для рассылки:", kb)
    return BROADCAST_MSG

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users')
    users = c.fetchall()
    conn.close()
    await update.message.reply_text("⏳ Рассылка началась...")
    for u in users:
        try: await context.bot.copy_message(chat_id=u[0], from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except: pass
    await update.message.reply_text("✅ Рассылка завершена!")
    return ConversationHandler.END

async def add_full_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_ID: return ConversationHandler.END
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    await show_text_menu(query, context, "➕ Напиши код для нового фулла:", kb)
    return FULL_CODE_ADD

async def add_full_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['full_code'] = update.message.text.strip()
    await update.message.reply_text("Теперь отправь медиа для этого фулла:")
    return FULL_MEDIA_ADD

async def add_full_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data['full_code']
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO fulls VALUES (?, ?, ?)', (code, update.effective_chat.id, update.message.message_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Фулл по коду <b>{code}</b> сохранен!", parse_mode="HTML")
    return ConversationHandler.END

async def get_full_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="cancel_full")]])
    await show_text_menu(query, context, "🔥 Введи код для получения фулла:", kb)
    return FULL_CODE_GET

async def cancel_full_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context, is_callback=True)
    return ConversationHandler.END

async def get_full_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    conn = get_emir_conn()
    c = conn.cursor()
    c.execute('SELECT from_chat_id, message_id FROM fulls WHERE code = ?', (code,))
    res = c.fetchone()
    conn.close()
    if res:
        await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=res[0], message_id=res[1])
    else:
        await update.message.reply_text("❌ Код не найден.")
    return ConversationHandler.END

async def suggest_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="cancel_suggest")]])
    await show_text_menu(query, context, "<b>✍️ Предложка</b>\n\nПрисылай своё фото, видео или текст.", kb)
    return SUGGEST_WAIT_INPUT

async def suggest_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else f"ID {user.id}"
    await update.message.reply_text("✅ Спасибо! Предложка отправлена админам.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{user.id}")]])
    for admin_id in ADMIN_ID:
        try:
            await context.bot.send_message(chat_id=admin_id, text=f"📥 <b>Новая предложка!</b>\nОт: {username}", parse_mode="HTML")
            await context.bot.copy_message(chat_id=admin_id, from_chat_id=update.effective_chat.id, message_id=update.message.message_id, reply_markup=kb)
        except: pass
    return ConversationHandler.END

async def cancel_suggest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context, is_callback=True)
    return ConversationHandler.END

async def admin_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    target_id = query.data.split("_")[1]
    context.user_data['reply_target'] = target_id
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="admin_cancel")]])
    await query.message.reply_text(f"✍️ Напиши ответ пользователю {target_id}:", reply_markup=kb)
    return ADMIN_REPLY_WAIT

async def admin_reply_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_id = context.user_data['reply_target']
    try:
        await context.bot.send_message(chat_id=target_id, text="🔔 <b>Ответ от администратора:</b>", parse_mode="HTML")
        await context.bot.copy_message(chat_id=target_id, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await update.message.reply_text("✅ Ответ отправлен!")
    except:
        await update.message.reply_text("❌ Ошибка отправки.")
    return ConversationHandler.END

async def donate_crypto_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="cancel_donate")]])
    await show_text_menu(query, context, "💎 <b>CryptoPay Донат</b>\n\nВведите сумму в РУБЛЯХ:", kb)
    return DONATE_AMOUNT_WAIT

async def donate_crypto_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(',', '.')
    try:
        amount = float(text)
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число.")
        return DONATE_AMOUNT_WAIT
    await update.message.reply_text("⏳ Генерирую счет...")
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    payload = {"currency_type": "fiat", "fiat": "RUB", "amount": str(amount), "description": "Донат на развитие"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=10.0)
            data = response.json()
            if data.get("ok"):
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Оплатить", url=data["result"]["pay_url"])], [InlineKeyboardButton("« В меню", callback_data="startt")]])
                await update.message.reply_text(f"✅ <b>Счет на {amount} ₽ создан!</b>", reply_markup=kb, parse_mode="HTML")
            else:
                error_msg = data.get("error", {}).get("name", "Неизвестная ошибка")
                await update.message.reply_text(f"❌ Ошибка: {error_msg}", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка соединения: {e}")
    return ConversationHandler.END

async def cancel_donate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context, is_callback=True)
    return ConversationHandler.END

async def clear_webhook_job(context):
    try:
        await context.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Вебхук очищен")
    except Exception as e:
        logger.error(f"Ошибка очистки вебхука: {e}")

async def _post_init(application):
    await moderator.set_me(application)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(clear_webhook_job, interval=86400, first=60)

def main():
    init_db()
    application = Application.builder().token(TOKEN).post_init(_post_init).build()
    moderator.register(application)
    admin_fallbacks = [
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(admin_cancel_callback, pattern="^admin_cancel$")
    ]
    application.add_handlers([
        CommandHandler("start", start),
        CommandHandler("admin", admin_cmd),
        CallbackQueryHandler(admin_stats_callback, pattern="^admin_stats$"),
        MessageHandler((filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & ~filters.COMMAND, chat_auto_reply),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(autoreply_set_start, pattern="^admin_set_autoreply$")],
            states={ADMIN_SET_AUTOREPLY_WAIT: [MessageHandler(filters.ALL & ~filters.COMMAND, autoreply_set_process)]},
            fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(rules_text_set_start, pattern="^admin_set_rules_text$")],
            states={ADMIN_SET_RULES_TEXT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rules_text_set_process)]},
            fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(set_limit_start, pattern="^admin_set_limit$")],
            states={ADMIN_SET_LIMIT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_limit_process)]},
            fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(image_set_start, pattern="^admin_set_image$")],
            states={ADMIN_SET_IMAGE_WAIT: [MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, image_set_process)]},
            fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_reply_start, pattern="^reply_")],
            states={ADMIN_REPLY_WAIT: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_reply_send)]},
            fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(broadcast_start, pattern="^admin_broadcast$")],
            states={BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_send)]},
            fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(add_full_start, pattern="^admin_add_full$")],
            states={
                FULL_CODE_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_full_code)],
                FULL_MEDIA_ADD: [MessageHandler(filters.ALL & ~filters.COMMAND, add_full_media)]
            }, fallbacks=admin_fallbacks
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(get_full_start, pattern="^full$")],
            states={FULL_CODE_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_full_send)]},
            fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel_full_callback, pattern="^cancel_full$")]
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(suggest_start, pattern="^suggest$")],
            states={SUGGEST_WAIT_INPUT: [MessageHandler(filters.ALL & ~filters.COMMAND, suggest_receive)]},
            fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel_suggest_callback, pattern="^cancel_suggest$")]
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(donate_crypto_start, pattern="^cryptopay$")],
            states={DONATE_AMOUNT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, donate_crypto_process)]},
            fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel_donate_callback, pattern="^cancel_donate$")]
        ),
        CallbackQueryHandler(obrabotka)
    ])
    print("🤖 Бот запущен!")
    application.run_polling()

if __name__ == "__main__":
    main()