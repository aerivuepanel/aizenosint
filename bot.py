import os
import io
import re
import sys
import json
import math
import html
import hashlib
import secrets
import asyncio
import logging
import socket
import subprocess
import dns.resolver
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv
from PIL import Image, ExifTags
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# =============================================================================
# CONFIG & LOGGING
# =============================================================================
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m', 'INFO': '\033[32m', 'WARNING': '\033[33m',
        'ERROR': '\033[31m', 'CRITICAL': '\033[35m', 'RESET': '\033[0m'
    }
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColoredFormatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("DEMON_OSINT")

load_dotenv()

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USER_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip()

# === GROUP ===
FREE_GROUP_ID = os.getenv("FREE_GROUP_ID", "").strip()
DAILY_SEARCH_LIMIT = int(os.getenv("DAILY_SEARCH_LIMIT", "10"))
REFERRAL_BONUS = int(os.getenv("REFERRAL_BONUS", "5"))

# === API KEYS ===
TG_API_KEY = os.getenv("TG_API_KEY")
TG_API_URL = os.getenv("TG_API_URL")

AADHAR_API_KEY = os.getenv("AADHAR_API_KEY")
AADHAR_API_URL = os.getenv("AADHAR_API_URL")

AERIVUE_API_KEY = os.getenv("AERIVUE_API_KEY")
AERIVUE_URL = os.getenv("AERIVUE_URL")

TURTLEMINT_API_KEY = os.getenv("TURTLEMINT_API_KEY")
TURTLEMINT_URL = os.getenv("TURTLEMINT_URL")

# === NEW LOOKUP APIs ===
VEHICLE_API_URL = os.getenv("VEHICLE_API_URL", "https://vehicle-eight-vert.vercel.app/api").strip()
IMEI_API_URL = os.getenv("IMEI_API_URL", "https://ng-imei-info.vercel.app/").strip()

API_TIMEOUT_SECONDS = float(os.getenv("API_TIMEOUT_SECONDS", "15"))
AUTO_DELETE_USER_SECONDS = int(os.getenv("AUTO_DELETE_USER_SECONDS", "1"))
AUTO_DELETE_RESULT_SECONDS = int(os.getenv("AUTO_DELETE_RESULT_SECONDS", "120"))
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "database.json"

# =============================================================================
# DATABASE
# =============================================================================
DEFAULT_DB = {
    "users": {},
    "searches": [],
    "referrals": [],
    "settings": {
        "created_at": None,
        "force_join": [],
        "maintenance_mode": False,
    },
}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def save_db(db):
    tmp = DB_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    tmp.replace(DB_FILE)

def load_db():
    if not DB_FILE.exists():
        data = json.loads(json.dumps(DEFAULT_DB))
        data["settings"]["created_at"] = now_iso()
        save_db(data)
        return data
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("users", {})
        data.setdefault("searches", [])
        data.setdefault("referrals", [])
        data.setdefault("settings", {})
        data["settings"].setdefault("created_at", now_iso())
        fj = data["settings"].get("force_join")
        if not isinstance(fj, list):
            fj = []
        data["settings"]["force_join"] = fj
        data["settings"].setdefault("maintenance_mode", False)
        save_db(data)
        return data
    except Exception:
        logger.exception("DB load failed; creating fresh DB")
        data = json.loads(json.dumps(DEFAULT_DB))
        data["settings"]["created_at"] = now_iso()
        save_db(data)
        return data

DB = load_db()

# =============================================================================
# PREMIUM EMOJI — SAFE FALLBACK
# =============================================================================
EMOJI = {
    "star": "5467641505525016018", "spark": "6172503852785342178",
    "diamond": "6129812419028982717", "search": "4956282853882069908",
    "user": "5379999674193172777", "crown": "5197269100878907942",
    "shield": "5249231689695115145", "fire": "6026092115631543342",
    "check": "5425124408786197150", "lock": "5258513401784573443",
    "rocket": "5453965363286925977", "globe": "5895476993314524652",
    "phone": "4958485609464202497", "database": "5985796637971191405",
    "bolt": "5303416490295304868", "target": "6203911118964924015",
    "gift": "5326049357332513437", "link": "5355051922862653659",
    "users": "6118385795976930086", "premium": "6125239923831217642",
    "verified": "5359454053887670307", "analytics": "5453991094435997597",
    "security": "6321192055750009250", "global": "5773659712071409251",
    "speed": "6203911118964924015", "tools": "6125264332130359953",
    "network": "6125082079488121878", "card": "5303416490295304868",
    "id": "5359454053887670307", "car": "6203911118964924015",
}




def ce(name: str, fallback: str = "•") -> str:
    emoji_id = EMOJI.get(name)

    if not emoji_id:
        return fallback or "•"

    # Use a real emoji character as the HTML entity content.
    emoji_map = {
        "star": "⭐",
        "spark": "✨",
        "diamond": "🔷",
        "search": "🔎",
        "user": "👤",
        "crown": "👑",
        "shield": "🛡️",
        "fire": "🔥",
        "check": "✅",
        "lock": "🔒",
        "rocket": "🚀",
        "globe": "🌐",
        "phone": "📱",
        "database": "🗄️",
        "bolt": "⚡",
        "target": "🎯",
        "gift": "🎁",
        "link": "🔗",
        "users": "👥",
        "premium": "💎",
        "verified": "✔️",
        "analytics": "📊",
        "security": "🔐",
        "global": "🌍",
        "speed": "💨",
        "tools": "🛠️",
        "network": "🌐",
        "card": "💳",
        "id": "🪪",
        "car": "🚗",
    }

    emoji = emoji_map.get(name, fallback or "•")

    return f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>'





def esc(value) -> str:
    return html.escape(str(value), quote=True)

def clean_html(text: str) -> str:
    if not text:
        return ""

    # Custom Telegram emoji -> fallback character
    text = re.sub(
        r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>",
        r"\1",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Remove Telegram HTML formatting tags
    text = re.sub(r"</?(?:b|strong|i|em|u|s|strike|del|code|pre)>", "", text, flags=re.IGNORECASE)

    # Convert Telegram links to visible text
    text = re.sub(
        r'<a\b[^>]*href=["\'][^"\']*["\'][^>]*>(.*?)</a>',
        r"\1",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Remove any remaining HTML-like tags
    text = re.sub(r"<[^>]+>", "", text)

    return html.unescape(text)



# =============================================================================
# SAFE SEND HELPERS — auto-fallback if custom emoji fails
# =============================================================================
async def safe_reply(message, text, **kwargs):
    try:
        return await message.reply_text(text, **kwargs)

    except BadRequest as e:
        error = str(e).lower()

        logger.error("TELEGRAM EMOJI ERROR: %s | TEXT: %s", e, text)

        if "can't parse entities" in error or \
           "entity_text_invalid" in error or \
           "can't find end tag" in error or \
           "unsupported start tag" in error:

            clean_kwargs = dict(kwargs)
            clean_kwargs.pop("parse_mode", None)

            return await message.reply_text(
                clean_html(text),
                **clean_kwargs
            )

        raise


async def safe_edit(query, text, **kwargs):
    try:
        return await query.edit_message_text(text, **kwargs)

    except BadRequest as e:
        error = str(e).lower()

        if "message is not modified" in error or "not modified" in error:
            return None

        if "can't parse entities" in error or \
           "entity_text_invalid" in error or \
           "can't find end tag" in error or \
           "unsupported start tag" in error:

            clean_kwargs = dict(kwargs)
            clean_kwargs.pop("parse_mode", None)

            return await query.edit_message_text(
                clean_html(text),
                **clean_kwargs
            )

        raise


def help_text(user=None) -> str:
    premium = is_premium_user(user) if user else False

    status = (
        f"{ce('premium', '•')} <b>Premium Active</b>"
        if premium
        else
        f"{ce('user', '•')} <b>Free Account</b>"
    )

    return (
        f"{ce('shield', '•')} <b>DEMON OSINT — COMMAND CENTER</b>\n"
        f"<i>Professional command reference</i>\n\n"

        f"{status}\n\n"

        f"{ce('star', '•')} <b>GENERAL</b>\n"
        f"└ <code>/start</code> — Open main menu\n"
        f"└ <code>/help</code> — Command guide\n"
        f"└ <code>/profile</code> — View profile\n"
        f"└ <code>/refer</code> — Referral center\n"
        f"└ <code>/cancel</code> — Cancel operation\n\n"

        f"{ce('search', '•')} <b>AVAILABLE COMMANDS</b>\n\n"

        f"{ce('user', '•')} <b>TG Info</b>\n"
        f"└ <code>/tg &lt;number&gt;</code>\n\n"

        f"{ce('id', '•')} <b>Aadhaar</b>\n"
        f"└ <code>/aadhar &lt;value&gt;</code>\n\n"

        f"{ce('phone', '•')} <b>Number Lookup</b>\n"
        f"└ <code>/num &lt;number&gt;</code>\n\n"

        f"{ce('car', '•')} <b>Vehicle</b>\n"
        f"└ <code>/veh &lt;registration&gt;</code>\n\n"

        f"{ce('search', '•')} <b>Username</b>\n"
        f"└ <code>/user &lt;username&gt;</code>\n\n"

        f"{ce('network', '•')} <b>Network</b>\n"
        f"└ <code>/target &lt;domain&gt;</code>\n\n"

        f"{ce('verified', '•')} <b>Email</b>\n"
        f"└ <code>/email &lt;email&gt;</code>\n\n"


        f"{ce('security', '•')} <b>Dark Web Demo</b>\n"
        f"└ <code>/darkweb &lt;query&gt;</code>\n\n"

        f"{ce('tools', '•')} <b>Image Forensics</b>\n"
        f"└ Send a photo directly\n\n"

        f"{ce('analytics', '•')} <b>ACCOUNT</b>\n"
        f"└ <code>/profile</code>\n"
        f"└ <code>/refer</code>\n\n"

        f"{ce('shield', '•')} <b>USAGE</b>\n"
        f"• Commands work directly in supported chats.\n"
        f"• Use the bot only for authorized research.\n\n"

        f"{ce('star', '•')} <i>Use /start to open the main menu.</i>"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await enforce_force_join(update):
        return

    user = ensure_user(update.effective_user)

    await safe_reply(
        update.message,
        help_text(user),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=back_keyboard(),
    )


async def safe_edit_message(message, text, **kwargs):
    auto_delete_after = kwargs.pop("auto_delete_after", 0)
    try:
        result = await message.edit_text(text, **kwargs)
        if auto_delete_after:
            schedule_message_delete(result, auto_delete_after)
        return result
    except BadRequest as e:
        err = str(e).lower()
        if "not modified" in err:
            return None
        if "entity_text_invalid" in err or "can't parse entities" in err or "can't find end tag" in err:
            clean_kwargs = dict(kwargs)
            clean_kwargs.pop("parse_mode", None)
            result = await message.edit_text(clean_html(text), **clean_kwargs)
            if auto_delete_after:
                schedule_message_delete(result, auto_delete_after)
            return result
        raise

# =============================================================================
# USER MANAGEMENT
# =============================================================================
def ensure_user(tg_user):
    uid = str(tg_user.id)
    if uid not in DB["users"]:
        DB["users"][uid] = {
            "id": tg_user.id, "username": tg_user.username,
            "first_name": tg_user.first_name, "last_name": tg_user.last_name,
            "created_at": now_iso(), "is_premium": False, "premium_until": None,
            "last_seen": now_iso(), "ref_code": f"ref_{tg_user.id}_{secrets.token_hex(3)}",
            "referred_by": None, "referrals": [], "bonus_searches": 0,
            "total_searches": 0, "last_search_date": today_key(),
            "daily_searches": 0, "is_banned": False,
        }
        save_db(DB)
    else:
        u = DB["users"][uid]
        u["username"] = tg_user.username
        u["first_name"] = tg_user.first_name
        u["last_name"] = tg_user.last_name
        u.setdefault("is_premium", False)
        u.setdefault("premium_until", None)
        u["last_seen"] = now_iso()
        save_db(DB)
    return DB["users"][uid]

def get_user(user_id):
    return DB["users"].get(str(user_id))

def is_admin(user_id) -> bool:
    return user_id in ADMIN_USER_IDS

def is_unlimited_chat(update) -> bool:
    chat = update.effective_chat
    return bool(
        chat and chat.type in ("group", "supergroup") and FREE_GROUP_ID
        and str(chat.id) == FREE_GROUP_ID
    )

def is_premium_user(user) -> bool:
    if not user or not user.get("is_premium"):
        return False
    until = user.get("premium_until")
    if not until:
        return True
    try:
        expires = datetime.fromisoformat(until)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            user["is_premium"] = False
            user["premium_until"] = None
            save_db(DB)
            return False
    except Exception:
        return bool(user.get("is_premium"))
    return True

def reset_daily_if_needed(user):
    if user.get("last_search_date") != today_key():
        user["last_search_date"] = today_key()
        user["daily_searches"] = 0
        save_db(DB)

def get_remaining_searches(user):
    reset_daily_if_needed(user)
    normal = max(DAILY_SEARCH_LIMIT - int(user.get("daily_searches", 0)), 0)
    bonus = int(user.get("bonus_searches", 0))
    return normal + bonus

def consume_search(user, unlimited=False, module="unknown", target=""):
    if unlimited:
        allowed = True
    else:
        reset_daily_if_needed(user)
        daily = int(user.get("daily_searches", 0))
        bonus = int(user.get("bonus_searches", 0))
        if daily < DAILY_SEARCH_LIMIT:
            user["daily_searches"] = daily + 1
            allowed = True
        elif bonus > 0:
            user["bonus_searches"] = bonus - 1
            allowed = True
        else:
            allowed = False
    if not allowed:
        return False
    user["total_searches"] = int(user.get("total_searches", 0)) + 1
    DB.setdefault("searches", []).append({
        "user_id": user.get("id"), "module": module,
        "target": str(target)[:200], "created_at": now_iso(),
    })
    if len(DB["searches"]) > 10000:
        DB["searches"] = DB["searches"][-10000:]
    save_db(DB)
    return True

def search_gate(update, module="unknown", target=""):
    user = ensure_user(update.effective_user)
    if user.get("is_banned"):
        return user, False, "banned"
    unlimited = is_unlimited_chat(update) or is_premium_user(user)
    if consume_search(user, unlimited=unlimited, module=module, target=target):
        return user, True, "ok"
    return user, False, "limit"

def premium_label(user) -> str:
    if not is_premium_user(user):
        return "Free"
    until = user.get("premium_until")
    if until:
        try:
            dt = datetime.fromisoformat(until)
            return f"Premium until {dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        except Exception:
            pass
    return "Premium"

def grant_premium(user, days: int) -> None:
    days = max(1, int(days))
    now = datetime.now(timezone.utc)
    start = now
    if is_premium_user(user) and user.get("premium_until"):
        try:
            current = datetime.fromisoformat(user["premium_until"])
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            if current > now:
                start = current
        except Exception:
            pass
    user["is_premium"] = True
    user["premium_until"] = (start + timedelta(days=days)).isoformat()
    save_db(DB)

def revoke_premium(user) -> None:
    user["is_premium"] = False
    user["premium_until"] = None
    save_db(DB)

def reset_user_limits(user) -> None:
    user["daily_searches"] = 0
    user["bonus_searches"] = 0
    user["last_search_date"] = today_key()
    save_db(DB)

# =============================================================================
# MODERATION / MAINTENANCE / AUTO DELETE
# =============================================================================
def maintenance_enabled() -> bool:
    return bool(DB.setdefault("settings", {}).get("maintenance_mode", False))


def user_delete_seconds() -> int:
    return max(0, int(DB.setdefault("settings", {}).get("user_delete_seconds", AUTO_DELETE_USER_SECONDS)))


def result_delete_seconds() -> int:
    return max(0, int(DB.setdefault("settings", {}).get("result_delete_seconds", AUTO_DELETE_RESULT_SECONDS)))


def maintenance_text() -> str:
    return (
        f"{ce('tools', '•')} <b>MAINTENANCE MODE</b>\n\n"
        f"The bot is temporarily unavailable while maintenance is in progress.\n"
        f"Please try again later."
    )


async def schedule_delete(message, delay: int):
    if not message or delay <= 0:
        return
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass


def schedule_message_delete(message, delay: int):
    if message and delay > 0:
        asyncio.create_task(schedule_delete(message, delay))


async def launch_update_restart() -> bool:
    script = BASE_DIR / "update_restart.sh"
    if not script.exists():
        logger.error("Update script not found: %s", script)
        return False
    try:
        subprocess.Popen(["/bin/bash", str(script)], cwd=str(BASE_DIR), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        logger.exception("Failed to launch update/restart script")
        return False


def delete_user_search_message(update: Update):
    """Delete a user's search/input message after the configured short delay."""
    message = update.effective_message
    if not message or not message.from_user:
        return
    if user_delete_seconds() > 0:
        schedule_message_delete(message, user_delete_seconds())


# =============================================================================
# FORCE JOIN
# =============================================================================
def get_force_join_channels() -> list:
    settings = DB.setdefault("settings", {})
    fj = settings.get("force_join")
    if not isinstance(fj, list):
        fj = []
        settings["force_join"] = fj
    return fj

async def force_join_required(update: Update) -> list:
    if not update.effective_user or is_admin(update.effective_user.id):
        return []
    channels = [c for c in get_force_join_channels() if c.get("enabled") and c.get("chat")]
    if not channels:
        return []
    missing = []
    for c in channels:
        try:
            member = await update.get_bot().get_chat_member(chat_id=c["chat"], user_id=update.effective_user.id)
            if member.status in ("creator", "administrator", "member"):
                continue
            missing.append(c)
        except Exception as e:
             logger.error(f"Force join check failed for {c.get('chat')}: {e}")
             missing.append(c)
    return missing

def force_join_keyboard(missing: list):
    rows = []
    for c in missing:
        rows.append([modern_button(c.get("title") or "Join", url=c.get("url"), style="primary", emoji_name="users")])
    rows.append([modern_button("• I Joined — Check Again", "forcejoin_check", style="success", emoji_name="check")])
    return InlineKeyboardMarkup(rows)

async def enforce_force_join(update: Update) -> bool:
    if update.effective_user and not is_admin(update.effective_user.id) and maintenance_enabled():
        text = maintenance_text()
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await safe_reply(update.callback_query.message, text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
        elif update.effective_message:
            await safe_reply(update.effective_message, text, parse_mode=ParseMode.HTML)
        return True

    missing = await force_join_required(update)
    if missing:
        lines = [f"{ce('lock', '•')} <b>Join Required</b>", "", "Please join the following before using the bot:"]
        for c in missing:
            lines.append(f"  • <b>{esc(c.get('title'))}</b>")
        lines.append("")
        lines.append(f"{ce('check', '•')} After joining, tap the button below.")
        text = "\n".join(lines)
        kb = force_join_keyboard(missing)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except BadRequest:
                await safe_reply(update.callback_query.message, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        elif update.effective_message:
            await safe_reply(update.effective_message, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return True
    return False

# =============================================================================
# MODERN BUTTONS (with safe fallback)
# =============================================================================
def modern_button(text, callback=None, url=None, style=None, emoji_name=None):
    kwargs = {"text": text}
    if callback:
        kwargs["callback_data"] = callback
    if url:
        kwargs["url"] = url
    if style:
        kwargs["style"] = style
    if emoji_name and EMOJI.get(emoji_name):
        kwargs["icon_custom_emoji_id"] = EMOJI[emoji_name]
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        try:
            return InlineKeyboardButton(**kwargs)
        except TypeError:
            kwargs.pop("icon_custom_emoji_id", None)
            return InlineKeyboardButton(**kwargs)

# =============================================================================
# MAIN MENU KEYBOARD
# =============================================================================
def main_keyboard(user=None):
    rows = [
        [
            modern_button("TG Info", "mod_tg", style="primary", emoji_name="user"),
            modern_button("Aadhaar", "mod_aadhar", style="primary", emoji_name="id"),
        ],
        [
            modern_button("Number OSINT", "mod_num", style="primary", emoji_name="phone"),
            modern_button("Vehicle Info", "mod_veh", style="primary", emoji_name="car"),
            modern_button("IMEI Info", "mod_imei", style="primary", emoji_name="phone"),
        ],
        [
            modern_button("Username Recon", "mod_user", style="primary", emoji_name="search"),
            modern_button("Network Intel", "mod_target", style="primary", emoji_name="network"),
        ],
        [
            modern_button("Email Intel", "mod_email", style="primary", emoji_name="verified"),
        ],
        [
            modern_button("Image Forensics", "mod_image", style="primary", emoji_name="tools"),
            modern_button("Dark Web Demo", "mod_darkweb", style="danger", emoji_name="security"),
        ],
        [
            modern_button("Profile", "profile", style="primary", emoji_name="user"),
            modern_button("Refer & Earn", "refer", style="success", emoji_name="gift"),
        ],
        [
            modern_button("Statistics", "stats", style="primary", emoji_name="analytics"),
            modern_button("Help", "help", style="danger", emoji_name="shield"),
        ],
    ]
    if user and is_admin(user.get("id")):
        rows.append([modern_button("• Admin Panel", "admin_panel", style="danger", emoji_name="crown")])
    return InlineKeyboardMarkup(rows)

def back_keyboard():
    return InlineKeyboardMarkup([
        [modern_button("Home", "home", style="primary", emoji_name="star")]
    ])

def number_result_keyboard(number: str, back_data: str = "home"):
    return InlineKeyboardMarkup([
        [modern_button("Number Info", f"numinfo:{number}", style="primary", emoji_name="phone")],
        [
            modern_button("Back", back_data, style="primary", emoji_name="search"),
            modern_button("Home", "home", style="primary", emoji_name="star"),
        ],
    ])

def deep_analysis_keyboard(number: str):
    return InlineKeyboardMarkup([
        [modern_button("Deep Analysis", f"deepnum:{number}", style="primary", emoji_name="analytics")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup([
        [modern_button("Cancel / Home", "home", style="danger", emoji_name="lock")]
    ])

# =============================================================================
# HOME TEXT
# =============================================================================
def home_text(user=None):
    user = user or {}
    remaining = get_remaining_searches(user) if user.get("id") else DAILY_SEARCH_LIMIT
    referrals = len(user.get("referrals", []))
    group_mode = "Unlimited in configured group" if FREE_GROUP_ID else "Standard limits"
    return (
        f'<tg-emoji emoji-id="5467641505525016018">⭐</tg-emoji> <b>AizenOSINT BOT v1.0</b>\n\n'
        f"{ce('diamond')} <b>Modern • Fast • Modular</b>\n"
        f"{ce('shield')} Authorized security research only.\n\n"
        f"{ce('search')} <b>Available Modules:</b>\n"
        f"• TG Info • Aadhaar • Number\n"
        f"• Vehicle • Username • Network\n"
        f"• Email • Image • Dark Web\n\n"
        f"{ce('speed')} <b>Searches remaining:</b> <code>{remaining}</code>\n"
        f"{ce('gift')} <b>Referral bonus:</b> +{REFERRAL_BONUS}\n"
        f"{ce('users')} <b>Your referrals:</b> {referrals}\n\n"
        f"{ce('globe')} <b>Group mode:</b> {esc(group_mode)}\n\n"
        f"{ce('security')} <i>Privacy-aware reporting enabled.</i>"
    )

# =============================================================================
# PROFILE & REFERRAL
# =============================================================================
async def show_profile(update, edit=True):
    user = ensure_user(update.effective_user)
    remaining = get_remaining_searches(user)
    text = (
        f"{ce('user', '•')} <b>YOUR PROFILE</b>\n\n"
        f"{ce('verified', '•')} <b>Name:</b> {esc(user.get('first_name') or 'Unknown')}\n"
        f"{ce('link', '•')} <b>Username:</b> @{esc(user.get('username') or 'not set')}\n"
        f"{ce('database', '•')} <b>User ID:</b> <code>{user['id']}</code>\n"
        f"{ce('premium', '•')} <b>Membership:</b> <b>{esc(premium_label(user))}</b>\n\n"
        f"{ce('search', '•')} <b>Total searches:</b> {user.get('total_searches', 0)}\n"
        f"{ce('speed', '•')} <b>Remaining:</b> {remaining}\n"
        f"{ce('gift', '•')} <b>Referrals:</b> {len(user.get('referrals', []))}\n"
        f"{ce('star', '•')} <b>Bonus searches:</b> {user.get('bonus_searches', 0)}"
    )
    kb = back_keyboard()
    if edit and update.callback_query:
        await safe_edit(update.callback_query, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await safe_reply(update.message, text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def show_referral(update, edit=True):
    user = ensure_user(update.effective_user)
    code = user["ref_code"]
    link = f"https://t.me/{BOT_USERNAME}?start={code}" if BOT_USERNAME else f"https://t.me/YOUR_BOT?start={code}"
    text = (
        f"{ce('gift', '•')} <b>REFERRAL CENTER</b>\n\n"
        f"{ce('users', '•')} <b>Your referrals:</b> {len(user.get('referrals', []))}\n"
        f"{ce('bolt', '•')} <b>Bonus:</b> +{REFERRAL_BONUS} per referral\n\n"
        f"{ce('link', '•')} <b>Your link:</b>\n<code>{esc(link)}</code>"
    )
    kb = InlineKeyboardMarkup([
        [modern_button("• Share Link", url=f"https://t.me/share/url?url={quote(link, safe='')}", style="primary", emoji_name="link")],
        [modern_button("Home", "home", style="primary", emoji_name="star")],
    ])
    if edit and update.callback_query:
        await safe_edit(update.callback_query, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await safe_reply(update.message, text, parse_mode=ParseMode.HTML, reply_markup=kb)

# =============================================================================
# API CALLS
# =============================================================================
async def api_get(url: str, params: dict = None, timeout: float = API_TIMEOUT_SECONDS) -> Optional[dict]:
    try:
        t = aiohttp.ClientTimeout(total=timeout)
        headers = {"Accept": "application/json", "User-Agent": "AizenOSINT/1.0"}
        async with aiohttp.ClientSession(timeout=t, headers=headers) as session:
            async with session.get(url, params=params, allow_redirects=True) as resp:
                text = await resp.text()
                try:
                    payload = json.loads(text)
                except (TypeError, ValueError):
                    payload = {"_raw": text[:5000]}
                if isinstance(payload, dict):
                    payload.setdefault("_status", resp.status)
                    return payload
                return {"data": payload, "_status": resp.status}
    except asyncio.TimeoutError:
        logger.warning("API GET timed out: %s", url)
        return {"success": False, "msg": "API request timed out"}
    except aiohttp.ClientError as e:
        logger.error("API GET %s failed: %s", url, e)
        return {"success": False, "msg": "API request failed"}
    except Exception as e:
        logger.exception("Unexpected API GET failure: %s", e)
        return {"success": False, "msg": "Unexpected API error"}

async def lookup_tg(value: str) -> Optional[dict]:
    if not TG_API_KEY:
        return {"success": False, "msg": "TG API key missing"}

    return await api_get(
        TG_API_URL,
        params={
            "tgusername": value.strip(),
            "apikey": TG_API_KEY
        }
        )
    
    
async def lookup_aadhaar(aadhaar: str) -> Optional[dict]:
    if not AADHAR_API_KEY:
        return {"success": False, "msg": "API key missing"}
    return {
              "success": True,
              "demo": True,
              "data": {
                  "name": " data not available",
                  "aadhaar": "XXXX XXXX 1234",
                  "dob": "01/01/2000",
                  "gender": "Male",
                  "mobile": "XXXXXX7890",
                  "address": " Address, , INdia",
                  "state": "Uttar Pradesh",
                  "status": " Active",
                  "email": "not found"
              }
          }
    # return await api_get(AADHAR_API_URL, params={"key": AADHAR_API_KEY, "q": aadhaar})

async def lookup_number(number: str) -> Optional[dict]:
    return await api_get(AERIVUE_URL, params={"number": number})


async def lookup_vehicle(reg_no: str) -> Optional[dict]:
    reg = re.sub(r"[^A-Za-z0-9]", "", reg_no).upper()
    return await api_get(VEHICLE_API_URL, params={"rc": reg})


async def lookup_imei(imei: str) -> Optional[dict]:
    value = re.sub(r"\D", "", imei)
    return await api_get(IMEI_API_URL, params={"imei_num": value})

# =============================================================================
# FORMATTERS — ONLY DATA, NO CREDITS
# =============================================================================
def fmt_tg(data: dict, number: str) -> str:
    if not data:
        return (
            f"{ce('lock', '•')} <b>No data found</b>\n"
            f"{ce('tools', '•')} Contact @aerivue for API"
        )

    # API response:
    # {
    #   "response": {
    #       "parameters": {...},
    #       "data": [...]
    #   }
    # }

    response = data.get("response", {})
    results = response.get("data", [])

    if not results or not isinstance(results, list):
        return (
            f"{ce('lock', '•')} <b>No data found</b>\n"
            f"{ce('tools', '•')} Contact @aerivue for API"
        )

    r = results[0] or {}

    lines = [
        f"{ce('user', '•')} <b>TELEGRAM INFO</b>",
        "",
        f"{ce('id', '•')} <b>User ID:</b> <code>{esc(r.get('user_id', 'N/A'))}</code>",
        f"{ce('phone', '•')} <b>Number:</b> <code>{esc(r.get('number', 'N/A'))}</code>",
        f"{ce('global', '•')} <b>Country Code:</b> <code>{esc(r.get('country_code', 'N/A'))}</code>",
        f"{ce('globe', '•')} <b>Country:</b> {esc(r.get('country', 'N/A'))}",
    ]

    return "\n".join(lines)

def fmt_aadhaar(data: dict, aadhaar: str) -> str:
    if not data or not data.get("success"):
        return (
            f"• <b>No data found</b>\n"
            f"<pre>{esc(json.dumps(data, indent=2, ensure_ascii=False))}</pre>\n"
            f"Contact @aerivue for API"
        )

    address = data.get("address", "N/A").replace("!", " ")
    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(address)}"

    lines = [
        f"{ce('id', '•')} <b>AADHAAR INFO</b>",
        "",
        f"{ce('card', '•')} <b>Aadhaar:</b> <code>{esc(aadhaar)}</code>",
        f"{ce('user', '•')} <b>Name:</b> {esc(data.get('name', 'N/A'))}",
        f"{ce('users', '•')} <b>Father Name:</b> {esc(data.get('father_name', 'N/A'))}",
        f"{ce('global', '•')} <b>Address:</b> {esc(address)}",
        f'📍 <a href="{maps_url}">Open in Google Maps</a>',
        f"{ce('phone', '•')} <b>Mobile:</b> <code>{esc(data.get('mobile', 'N/A'))}</code>",
        f"{ce('phone', '•')} <b>Alternate:</b> <code>{esc(data.get('alternate', 'N/A'))}</code>",
        f"{ce('network', '•')} <b>Circle:</b> {esc(data.get('circle', 'N/A'))}",
        f"{ce('verified', '•')} <b>Email:</b> {esc(data.get('email', 'N/A'))}",
    ]

    return "\n".join(lines)

def fmt_number(data: dict, number: str) -> str:
    if not data or not data.get("success"):
        return (
            f"• <b>No data found</b>\n"
            f"<pre>{esc(json.dumps(data, indent=2, ensure_ascii=False))}</pre>\n"
            f"Contact @aerivue for API"
        )
    
    result = data.get("result", {}).get("result", {})
    results = result.get("results", [])
    if not results:
        return f"• <b>No data found for</b> <code>{esc(number)}</code>"
    r = results[0]

    address = (r.get("address") or "N/A").replace("!", " ")
    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(address)}"

    lines = [
        f"{ce('phone', '•')} <b>NUMBER LOOKUP</b>",
        "",
        f"{ce('phone', '•')} <b>Mobile:</b> <code>{esc(r.get('mobile', number))}</code>",
        f"{ce('user', '•')} <b>Name:</b> {esc(r.get('name') or 'N/A')}",
        f"{ce('users', '•')} <b>Father Name:</b> {esc(r.get('father_name') or 'N/A')}",
        f"{ce('global', '•')} <b>Address:</b> {esc(address)}",
        f'{ce("global", "•")} <a href="{maps_url}">Open in Google Maps</a>',
        f"{ce('phone', '•')} <b>Alternate:</b> <code>{esc(r.get('alternate') or 'N/A')}</code>",
        f"{ce('network', '•')} <b>Circle:</b> {esc(r.get('circle') or 'N/A')}",
        f"{ce('id', '•')} <b>Aadhaar:</b> <code>{esc(r.get('aadhar') or 'N/A')}</code>",
        f"{ce('verified', '•')} <b>Email:</b> {esc(r.get('email') or 'N/A')}",
        f"{ce('analytics', '•')} <b>Total Results:</b> {esc(result.get('total', 0))}",
    ]
    return "\n".join(lines)

def fmt_vehicle(data: dict, reg: str) -> str:
    if not data or not isinstance(data, dict):
        return f"{ce('lock', '•')} <b>VEHICLE LOOKUP FAILED</b>\n\n{ce('car', '🚗')} <b>Registration:</b> <code>{esc(reg)}</code>"
    details = data.get("details") or {}
    if not isinstance(details, dict) or not details:
        return f"{ce('lock', '•')} <b>NO VEHICLE DATA FOUND</b>\n\n{ce('car', '🚗')} <b>Registration:</b> <code>{esc(data.get('rc') or reg)}</code>"
    lines=[f"{ce('car','🚗')} <b>VEHICLE INFORMATION</b>","",f"{ce('id','🪪')} <b>Registration:</b> <code>{esc(data.get('rc') or reg)}</code>","",f"{ce('user','👤')} <b>Owner Name:</b> {esc(details.get('Owner Name') or 'N/A')}",f"{ce('user','👤')} <b>Owner Serial:</b> {esc(details.get('Owner Serial No') or 'N/A')}",f"{ce('phone','📱')} <b>Phone:</b> <code>{esc(details.get('Phone') or 'N/A')}</code>","",f"{ce('car','🚗')} <b>Maker / Model:</b> {esc(details.get('Maker Model') or 'N/A')}",f"{ce('car','🚗')} <b>Model Name:</b> {esc(details.get('Model Name') or 'N/A')}",f"{ce('tools','🛠️')} <b>Vehicle Class:</b> {esc(details.get('Vehicle Class') or 'N/A')}",f"{ce('target','🎯')} <b>Fuel Type:</b> {esc(details.get('Fuel Type') or 'N/A')}","",f"{ce('network','🌐')} <b>Registered RTO:</b> {esc(details.get('Registered RTO') or 'N/A')}",f"{ce('global','🌍')} <b>City:</b> {esc(details.get('City Name') or 'N/A')}",f"{ce('global','🌍')} <b>Address:</b> {esc(details.get('Address') or 'N/A')}","",f"{ce('check','✅')} <b>Registration Date:</b> {esc(details.get('Registration Date') or 'N/A')}",f"{ce('check','✅')} <b>Fitness Upto:</b> {esc(details.get('Fitness Upto') or 'N/A')}",f"{ce('check','✅')} <b>Tax Upto:</b> {esc(details.get('Tax Upto') or 'N/A')}",f"{ce('check','✅')} <b>PUC Upto:</b> {esc(details.get('PUC Upto') or 'N/A')}","",f"{ce('security','🔐')} <b>Insurance Company:</b> {esc(details.get('Insurance Company') or 'N/A')}",f"{ce('security','🔐')} <b>Insurance Expiry:</b> {esc(details.get('Insurance Expiry') or 'N/A')}",f"{ce('security','🔐')} <b>Insurance Upto:</b> {esc(details.get('Insurance Upto') or 'N/A')}"]
    return "\n".join(lines)


def fmt_imei(data: dict, imei: str) -> str:
    if not data or not isinstance(data, dict):
        return f"{ce('lock','•')} <b>IMEI LOOKUP FAILED</b>\n\n{ce('id','🪪')} <b>IMEI:</b> <code>{esc(imei)}</code>"
    result=data.get('result') or {}; result=result if isinstance(result,dict) else {}
    header=result.get('header') or {}; header=header if isinstance(header,dict) else {}
    items=result.get('items') or []; items=items if isinstance(items,list) else []
    lines=[f"{ce('phone','📱')} <b>IMEI INFORMATION</b>","",f"{ce('id','🪪')} <b>IMEI:</b> <code>{esc(header.get('imei') or imei)}</code>",f"{ce('diamond','🔷')} <b>Brand:</b> {esc(header.get('brand') or 'N/A')}",f"{ce('phone','📱')} <b>Model:</b> {esc(header.get('model') or 'N/A')}"]
    for item in items:
        if not isinstance(item,dict): continue
        role=item.get('role'); title=str(item.get('title') or '').strip(); content=item.get('content')
        if role=='header':
            if title: lines.extend(['',f"{ce('premium','⭐')} <b>{esc(title)}</b>"])
        elif role=='item':
            if content is None or str(content).strip()=='': content='N/A'
            elif isinstance(content,(dict,list)): content=json.dumps(content,ensure_ascii=False,separators=(', ', ': '))
            lines.append(f"{ce('check','•')} <b>{esc(title or 'Info')}:</b> <code>{esc(str(content))}</code>")
    if not items: lines.append(f"\n{ce('lock','•')} <b>No detailed IMEI records returned.</b>")
    return "\n".join(lines)

# =============================================================================
# MODULE NAMES
# =============================================================================
MODULE_NAMES = {
    "tg": ("TG Number Info", "Send telgram user id: (e.g. 9876543210) or username: (e.g. @username)"),
    "aadhar": ("Aadhaar Info", "Send a 12-digit Aadhaar number"),
    "num": ("Number Lookup", "Send a 10-digit mobile number"),
    "veh": ("Vehicle Info", "Send a registration number (e.g. UP63AS0001)"),
    "imei": ("IMEI Info", "Send a 15-digit IMEI number (e.g. 353010111111110)"),
    "user": ("Username Recon", "Send a username to scan platforms"),
    "target": ("Network Intel", "Send a domain or IP"),
    "email": ("Email Intel", "Send an email address"),
    "image": ("Image Forensics", "Upload a photo directly"),
    "darkweb": ("Dark Web Demo", "Send a query (simulated)"),
}

def _pending_prompt(module: str) -> str:
    title, detail = MODULE_NAMES.get(module, ("Module", "Send the input."))
    icons = {
        "tg": "user", "aadhar": "id", "num": "phone", "veh": "car", "imei": "phone",
        "user": "search", "target": "network", "email": "verified",
        "phone": "phone", "image": "tools", "darkweb": "security",
    }
    icon = ce(icons.get(module, "tools"), "•")
    return (
        f"{icon} <b>{esc(title)}</b>\n\n"
        f"{esc(detail)}\n\n"
        f"<b>Send the value directly — no command required.</b>"
    )

# =============================================================================
# MODULE HANDLERS
# =============================================================================
async def handle_tg(update, context, value):
    value = value.strip()

    # @username OR numeric Telegram user ID
    if value.startswith("@"):
        lookup_value = value
    elif value.isdigit():
        lookup_value = value
    elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", value):
        lookup_value = "@" + value
    else:
        await safe_reply(
            update.effective_message,
            f"{ce('lock', '•')} <b>Invalid Telegram username/ID.</b>\n"
            f"Use <code>1234567890</code> or <code>@username</code>",
            parse_mode=ParseMode.HTML
        )
        return

    user, allowed, reason = search_gate(
        update,
        module="tg",
        target=lookup_value
    )

    if not allowed:
        await safe_reply(
            update.effective_message,
            f"{ce('lock', '•')} <b>"
            f"{'Banned.' if reason == 'banned' else 'Daily limit reached.'}"
            f"</b>",
            parse_mode=ParseMode.HTML
        )
        return

    status = await safe_reply(
        update.effective_message,
        f"{ce('search', '•')} <b>Searching...</b>",
        parse_mode=ParseMode.HTML
    )

    data = await lookup_tg(lookup_value)

    number = (
        data.get("response", {})
            .get("data", [{}])[0]
            .get("number")
    )

    keyboard = None

    if number:
        # Use modern_button so the custom emoji/icon is applied consistently.
        keyboard = deep_analysis_keyboard(str(number))
        # Preserve the Telegram result so Back can return here without another TG lookup.
        context.user_data["last_tg_result"] = {
            "text": fmt_tg(data, lookup_value),
            "lookup_value": lookup_value,
            "number": str(number),
        }

    await safe_edit_message(
        status,
        fmt_tg(data, lookup_value),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
        auto_delete_after=result_delete_seconds(),
    )

async def handle_aadhar(update, context, value):
    aadhaar = re.sub(r'\D', '', value)
    if len(aadhaar) != 12:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>Aadhaar must be 12 digits.</b>", parse_mode=ParseMode.HTML)
        return
    user, allowed, reason = search_gate(update, module="aadhar", target=aadhaar)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    status = await safe_reply(update.effective_message, f"{ce('search', '•')} <b>Searching...</b>", parse_mode=ParseMode.HTML)
    data = await lookup_aadhaar(aadhaar)
    await safe_edit_message(status, fmt_aadhaar(data, aadhaar), parse_mode=ParseMode.HTML, disable_web_page_preview=True, auto_delete_after=result_delete_seconds())


def _number_results(data: dict) -> list:
    """Extract the Number Info result list without exposing the raw API payload."""
    if not isinstance(data, dict):
        return []
    result = data.get("result") or {}
    if not isinstance(result, dict):
        return []
    result = result.get("result") or {}
    if not isinstance(result, dict):
        return []
    results = result.get("results") or []
    return results if isinstance(results, list) else []


def _result_id(result: dict, fallback_index: int = 0) -> str:
    """Return a stable display ID for a Number Info result."""
    if not isinstance(result, dict):
        return str(fallback_index + 1)

    value = (
        result.get("id")
        or result.get("ID")
        or result.get("result_id")
        or result.get("uid")
        or result.get("_id")
    )

    if value is None or str(value).strip() == "":
        return str(fallback_index + 1)

    return str(value)


def _number_detail_keyboard(index, total, number, results):
    rows = []

    nav = []

    if index > 0:
        prev_id = _result_id(results[index - 1], index - 1)

        nav.append(
            modern_button(
                f"⭐ ID: {prev_id}",
                f"num_page:{index - 1}",
                style="primary",
                emoji_name="premium"
            )
        )

    if index < total - 1:
        next_id = _result_id(results[index + 1], index + 1)

        nav.append(
            modern_button(
                f"⭐ ID: {next_id}",
                f"num_page:{index + 1}",
                style="primary",
                emoji_name="premium"
            )
        )

    if nav:
        rows.append(nav)

    rows.append([
        modern_button(
            "Download JSON",
            "num_json:all",
            style="success",
            emoji_name="database"
        )
    ])

    rows.append([
        modern_button(
            "Back",
            "deep_back",
            style="primary",
            emoji_name="search"
        ),
        modern_button(
            "Home",
            "home",
            style="primary",
            emoji_name="star"
        )
    ])

    return InlineKeyboardMarkup(rows)


def _format_number_detail(r: dict, number: str, index: int, total: int) -> str:
    r = r or {}
    address = (r.get("address") or "N/A").replace("!", " ")
    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(address)}"

    lines = [
        f"{ce('phone', '📱')} <b>NUMBER INFO</b>",
        "",
        f"{ce('phone', '📱')} <b>Mobile:</b> <code>{esc(r.get('mobile') or number)}</code>",
        f"{ce('user', '👤')} <b>Name:</b> {esc(r.get('name') or 'N/A')}",
        f"{ce('users', '👥')} <b>Father Name:</b> {esc(r.get('father_name') or 'N/A')}",
        f"{ce('global', '🌍')} <b>Address:</b> {esc(address)}",
        f'{ce("global", "🌍")} <a href="{maps_url}">Open in Google Maps</a>',
        f"{ce('phone', '📱')} <b>Alternate:</b> <code>{esc(r.get('alternate') or 'N/A')}</code>",
        "",
        f"{ce('premium', '⭐')} <b>ID:</b> <code>{index + 1}</code> <b>of</b> <code>{total}</code>",
        f"{ce('premium', '⭐')} <b>Result:</b> <code>{index + 1}/{total}</code>",
    ]
    return "\n".join(lines)


def _number_download_payload(results, number):
    """
    Download only the modified/details response for ALL Number Info results.
    Does NOT include the complete upstream API response.
    """
    details = []

    for index, result in enumerate(results, start=1):
        details.append({
            "result": index,
            "id": result.get("id"),
            "mobile": result.get("mobile"),
            "name": result.get("name"),
            "father_name": result.get("father_name"),
            "address": result.get("address"),
            "alternate": result.get("alternate"),
            "circle": result.get("circle"),
            "state": result.get("state"),
            "city": result.get("city"),
            "pincode": result.get("pincode"),
            "operator": result.get("operator"),
            "carrier": result.get("carrier"),
        })

    return {
        "number": number,
        "total_results": len(details),
        "results": details
    }

async def handle_num(update, context, value):
    number = re.sub(r'\D', '', value)
    if len(number) < 10:
        await safe_reply(
            update.effective_message,
            f"{ce('lock', '•')} <b>Invalid number.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    user, allowed, reason = search_gate(update, module="num", target=number)
    if not allowed:
        await safe_reply(
            update.effective_message,
            f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>",
            parse_mode=ParseMode.HTML
        )
        return

    status = await safe_reply(
        update.effective_message,
        f"{ce('search', '🔎')} <b>Number Info: searching...</b>",
        parse_mode=ParseMode.HTML
    )

    data = await lookup_number(number)
    results = _number_results(data)

    if not results:
        await safe_edit_message(
            status,
            fmt_number(data, number),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=back_keyboard(),
            auto_delete_after=result_delete_seconds(),
        )
        return

    # Keep only the details needed for pagination/download in the user's current session.
    context.user_data["number_info"] = {
        "number": number,
        "results": results,
    }
    index = 0
    total = len(results)

    await safe_edit_message(
        status,
        _format_number_detail(results[index], number, index, total),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=_number_detail_keyboard(index, total, number, results),
        auto_delete_after=result_delete_seconds(),
    )

async def handle_veh(update, context, value):
    reg = re.sub(r'[^A-Za-z0-9]', '', value).upper()
    if len(reg) < 8:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>Invalid registration.</b>", parse_mode=ParseMode.HTML)
        return
    user, allowed, reason = search_gate(update, module="veh", target=reg)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    status = await safe_reply(update.effective_message, f"{ce('search', '•')} <b>Searching...</b>", parse_mode=ParseMode.HTML)
    data = await lookup_vehicle(reg)
    await safe_edit_message(status, fmt_vehicle(data, reg), parse_mode=ParseMode.HTML, disable_web_page_preview=True, auto_delete_after=result_delete_seconds())


async def handle_imei(update, context, value):
    imei = re.sub(r"\D", "", value)
    if len(imei) != 15:
        await safe_reply(update.effective_message, f"{ce('lock','•')} <b>IMEI must be 15 digits.</b>", parse_mode=ParseMode.HTML)
        return
    user, allowed, reason = search_gate(update, module="imei", target=imei)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock','•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    status=await safe_reply(update.effective_message, f"{ce('search','🔎')} <b>IMEI Info: searching...</b>", parse_mode=ParseMode.HTML)
    data=await lookup_imei(imei)
    await safe_edit_message(status, fmt_imei(data, imei), parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=back_keyboard(), auto_delete_after=result_delete_seconds())

# =============================================================================
# USERNAME RECON
# =============================================================================
PLATFORM_MAP = {
    "Instagram": "https://www.instagram.com/{}/",
    "Twitter/X": "https://x.com/{}",
    "TikTok": "https://www.tiktok.com/@{}",
    "Facebook": "https://www.facebook.com/{}",
    "LinkedIn": "https://www.linkedin.com/in/{}",
    "Snapchat": "https://www.snapchat.com/add/{}",
    "Pinterest": "https://www.pinterest.com/{}/",
    "Reddit": "https://www.reddit.com/user/{}",
    "GitHub": "https://github.com/{}",
    "GitLab": "https://gitlab.com/{}",
    "StackOverflow": "https://stackoverflow.com/users/{}?tab=profile",
    "Dev.to": "https://dev.to/{}",
    "Medium": "https://medium.com/@{}",
    "YouTube": "https://www.youtube.com/@{}",
    "Twitch": "https://www.twitch.tv/{}",
    "SoundCloud": "https://soundcloud.com/{}",
    "Discord": "https://discord.com/users/{}",
    "Telegram": "https://t.me/{}",
    "Threads": "https://www.threads.net/@{}",
    "Steam": "https://steamcommunity.com/id/{}",
}

async def handle_user(update, context, value):
    username = value.split()[0].lstrip("@")
    if not username:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>Invalid username.</b>", parse_mode=ParseMode.HTML)
        return
    user, allowed, reason = search_gate(update, module="user", target=username)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    status = await safe_reply(update.effective_message, f"{ce('search', '•')} <b>Scanning platforms...</b>", parse_mode=ParseMode.HTML)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"}
    found = []
    async def check(name, url):
        try:
            t = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=t, headers=headers) as s:
                async with s.head(url, allow_redirects=True, ssl=False) as resp:
                    if resp.status == 200:
                        return {"platform": name, "url": url}
        except Exception:
            return None
        return None
    tasks = [check(name, url.format(username)) for name, url in PLATFORM_MAP.items()]
    results = await asyncio.gather(*tasks)
    for r in results:
        if r:
            found.append(r)
    lines = [
        f"{ce('user', '•')} <b>USERNAME RECON</b>",
        "",
        f"{ce('target', '•')} <b>Target:</b> <code>{esc(username)}</code>",
        f"{ce('search', '•')} <b>Scanned:</b> {len(PLATFORM_MAP)}",
        f"{ce('check', '•')} <b>Found:</b> {len(found)}",
        "",
    ]
    for p in found:
        lines.append(f"{ce('check', '•')} <a href=\"{esc(p['url'])}\">{esc(p['platform'])}</a>")
    if not found:
        lines.append(f"{ce('lock', '•')} No public profiles found.")
    await safe_edit_message(status, "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True, auto_delete_after=result_delete_seconds())

# =============================================================================
# NETWORK INTEL
# =============================================================================
COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP",
    110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB", 3306: "MySQL",
    3389: "RDP", 5432: "PostgreSQL", 5900: "VNC", 8080: "HTTP-Alt",
    8443: "HTTPS-Alt", 9200: "Elasticsearch", 27017: "MongoDB",
}

async def handle_target(update, context, value):
    target = value.split()[0]
    user, allowed, reason = search_gate(update, module="target", target=target)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    status = await safe_reply(update.effective_message, f"{ce('search', '•')} <b>Analyzing network...</b>", parse_mode=ParseMode.HTML)
    lines = [f"{ce('network', '•')} <b>NETWORK INTEL</b>", "", f"{ce('target', '•')} <b>Target:</b> <code>{esc(target)}</code>"]
    try:
        loop = asyncio.get_running_loop()
        ip = await loop.run_in_executor(None, socket.gethostbyname, target)
        lines.append(f"{ce('globe', '•')} <b>IP:</b> <code>{esc(ip)}</code>")
    except Exception:
        await safe_edit_message(status, f"• Could not resolve <code>{esc(target)}</code>", parse_mode=ParseMode.HTML)
        return
    try:
        t = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get(f"http://ip-api.com/json/{ip}") as resp:
                geo = await resp.json()
        if geo.get("status") == "success":
            lines += [
                "",
                f"{ce('global', '•')} <b>GEOLOCATION</b>",
                f"{ce('global', '•')} <b>Country:</b> {esc(geo.get('country'))}",
                f"{ce('network', '•')} <b>City:</b> {esc(geo.get('city'))}",
                f"{ce('network', '•')} <b>ISP:</b> {esc(geo.get('isp'))}",
                f"{ce('analytics', '•')} <b>ASN:</b> {esc(geo.get('as'))}",
            ]
    except Exception:
        pass
    if not re.match(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$", target):
        lines.append("")
        lines.append(f"{ce('database', '•')} <b>DNS RECORDS</b>")
        for rtype in ["A", "MX", "NS", "TXT"]:
            try:
                answers = dns.resolver.resolve(target, rtype)
                lines.append(f"{ce('check', '•')} <b>{rtype}:</b> <code>{', '.join(str(r) for r in answers)[:100]}</code>")
            except Exception:
                pass
    lines.append("")
    lines.append(f"{ce('tools', '•')} <b>PORT SCAN</b>")
    top = dict(list(COMMON_PORTS.items())[:10])
    async def scan(port, svc):
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=2.0)
            writer.close()
            await writer.wait_closed()
            return {"port": port, "service": svc}
        except Exception:
            return None
    results = await asyncio.gather(*[scan(p, s) for p, s in top.items()])
    open_ports = [r for r in results if r]
    for r in open_ports:
        lines.append(f"{ce('check', '•')} <b>Port {r['port']}</b> ({r['service']}) — OPEN")
    if not open_ports:
        lines.append(f"{ce('lock', '•')} No open ports detected")
    await safe_edit_message(status, "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True, auto_delete_after=result_delete_seconds())

# =============================================================================
# EMAIL & PHONE
# =============================================================================
DISPOSABLE = ["tempmail.com", "throwaway.com", "guerrillamail.com", "mailinator.com",
              "yopmail.com", "10minutemail.com", "temp-mail.org", "sharklasers.com"]

async def handle_email(update, context, value):
    email = value.split()[0]
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>Invalid email.</b>", parse_mode=ParseMode.HTML)
        return
    user, allowed, reason = search_gate(update, module="email", target=email)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    status = await safe_reply(update.effective_message, f"{ce('search', '•')} <b>Analyzing email...</b>", parse_mode=ParseMode.HTML)
    domain = email.split("@")[1]
    disposable = any(d in domain.lower() for d in DISPOSABLE)
    mx = []
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx = [str(r.exchange) for r in answers]
    except Exception:
        pass
    lines = [
        f"{ce('verified', '•')} <b>EMAIL INTEL</b>",
        "",
        f"{ce('verified', '•')} <b>Email:</b> <code>{esc(email)}</code>",
        f"{ce('analytics', '•')} <b>Disposable:</b> {'•• Yes' if disposable else '• No'}",
        f"{ce('database', '•')} <b>MX Records:</b> {esc(', '.join(mx)) if mx else '• None'}",
    ]
    await safe_edit_message(status, "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True, auto_delete_after=result_delete_seconds())

# =============================================================================
# DARK WEB DEMO
# =============================================================================
async def handle_darkweb(update, context, value):
    user, allowed, reason = search_gate(update, module="darkweb", target=value)
    if not allowed:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} <b>{'Banned.' if reason == 'banned' else 'Daily limit reached.'}</b>", parse_mode=ParseMode.HTML)
        return
    text = (
        f"{ce('security', '•')} <b>DARK WEB DEMO</b>\n\n"
        f"{ce('target', '•')} <b>Query:</b> <code>{esc(value)}</code>\n\n"
        f"{ce('shield', '•')} This is a simulated demo only.\n"
        f"{ce('lock', '•')} No Tor crawling or credential/breach-dump access."
    )
    result = await safe_reply(update.effective_message, text, parse_mode=ParseMode.HTML)
    schedule_message_delete(result, result_delete_seconds())

# =============================================================================
# IMAGE FORENSICS
# =============================================================================
async def image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_search_message(update)
    if await enforce_force_join(update):
        return
    if not update.message.photo:
        return
    user, allowed, reason = search_gate(update, module="image", target="photo")
    if not allowed:
        await safe_reply(update.message, f"{ce('lock', '•')} <b>Limit reached.</b>", parse_mode=ParseMode.HTML)
        return
    photo = update.message.photo[-1]
    status = await safe_reply(update.message, f"{ce('search', '•')} <b>Analyzing image...</b>", parse_mode=ParseMode.HTML)
    try:
        photo_file = await photo.get_file()
        image_bytes = await photo_file.download_as_bytearray()
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, Image.open, io.BytesIO(bytes(image_bytes)))
        exif_data = image.getexif()
        exif = {ExifTags.TAGS.get(tag, tag): value for tag, value in exif_data.items()} if exif_data else {}
        md5 = hashlib.md5(bytes(image_bytes)).hexdigest()
        sha256 = hashlib.sha256(bytes(image_bytes)).hexdigest()
        lines = [
            f"{ce('tools', '•')} <b>IMAGE FORENSICS</b>",
            "",
            f"{ce('analytics', '•')} <b>Format:</b> {image.format}",
            f"{ce('network', '•')} <b>Dimensions:</b> {image.size[0]}x{image.size[1]}",
            f"{ce('database', '•')} <b>EXIF entries:</b> {len(exif_data)}",
            f"{ce('lock', '•')} <b>GPS:</b> {'•• Present' if 'GPSInfo' in exif else '• Not present'}",
            f"{ce('verified', '•')} <b>MD5:</b> <code>{md5}</code>",
            f"{ce('verified', '•')} <b>SHA-256:</b> <code>{sha256}</code>",
        ]
        if "Make" in exif or "Model" in exif:
            lines.append(f"{ce('phone', '•')} <b>Device:</b> {esc(exif.get('Make', ''))} {esc(exif.get('Model', ''))}")
        await safe_edit_message(status, "\n".join(lines), parse_mode=ParseMode.HTML, auto_delete_after=result_delete_seconds())
    except Exception as e:
        await safe_edit_message(status, f"• <b>Failed:</b> <code>{esc(str(e))}</code>", parse_mode=ParseMode.HTML, auto_delete_after=result_delete_seconds())

# =============================================================================
# ADMIN PANEL
# =============================================================================
ADMIN_PAGE_SIZE = 8

def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [
            modern_button("Dashboard", "admin_dashboard", style="primary", emoji_name="analytics"),
            modern_button("All Users", "admin_users:0", style="primary", emoji_name="users"),
        ],
        [
            modern_button("Banned Users", "admin_banned:0", style="danger", emoji_name="lock"),
            modern_button("Premium", "admin_premium:0", style="success", emoji_name="premium"),
        ],
        [
            modern_button("Broadcast", "admin_broadcast", style="primary", emoji_name="rocket"),
            modern_button("Reset Limits", "admin_reset_all", style="primary", emoji_name="bolt"),
        ],
        [
            modern_button("Premium Manager", "admin_premium_add_custom", style="success", emoji_name="premium"),
            modern_button("Maintenance", "admin_maintenance", style="danger", emoji_name="tools"),
        ],
        [
            modern_button("Delete Timer", "admin_delete_timer", style="primary", emoji_name="lock"),
        ],
        [
            modern_button("Find User", "admin_find", style="primary", emoji_name="search"),
            modern_button("System Info", "admin_system", style="primary", emoji_name="tools"),
        ],
        [
            modern_button("Update & Restart", "admin_update_restart", style="success", emoji_name="tools"),
        ],
        [
            modern_button("Force Join", "admin_forcejoin", style="primary", emoji_name="shield"),
        ],
        [
            modern_button("Close", "home", style="danger", emoji_name="lock"),
        ],
    ])

def admin_back_keyboard():
    return InlineKeyboardMarkup([
        [modern_button("Admin Panel", "admin_panel", style="primary", emoji_name="crown")],
        [modern_button("Home", "home", style="danger", emoji_name="star")],
    ])

def admin_dashboard_text() -> str:
    users = list(DB["users"].values())
    banned = sum(1 for u in users if u.get("is_banned"))
    premium = sum(1 for u in users if is_premium_user(u))
    today = today_key()
    today_searches = sum(1 for x in DB.get("searches", []) if str(x.get("created_at", "")).startswith(today))
    return (
        f"{ce('crown', '•')} <b>ADMIN CONTROL CENTER</b>\n\n"
        f"{ce('users', '•')} <b>Total users:</b> <code>{len(users)}</code>\n"
        f"{ce('premium', '•')} <b>Premium:</b> <code>{premium}</code>\n"
        f"{ce('lock', '•')} <b>Banned:</b> <code>{banned}</code>\n"
        f"{ce('search', '•')} <b>Searches:</b> <code>{len(DB.get('searches', []))}</code>\n"
        f"{ce('bolt', '•')} <b>Today:</b> <code>{today_searches}</code>\n"
        f"{ce('gift', '•')} <b>Referrals:</b> <code>{len(DB.get('referrals', []))}</code>\n"
        f"{ce('shield', '•')} <b>Force-join:</b> <code>{len(get_force_join_channels())}</code>\n"
        f"{ce('tools', '•')} <b>Maintenance:</b> <code>{'ON' if maintenance_enabled() else 'OFF'}</code>\n"
        f"{ce('lock', '•')} <b>Input delete:</b> <code>{user_delete_seconds()}s</code>\n"
        f"{ce('lock', '•')} <b>Result delete:</b> <code>{result_delete_seconds()}s</code>"
    )

def _user_display(user) -> str:
    name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x).strip()
    username = f"@{user['username']}" if user.get("username") else "no username"
    return f"{name or username} • {user.get('id')}"

def _paged_users(kind: str, page: int):
    users = sorted(DB["users"].values(), key=lambda u: u.get("created_at", ""), reverse=True)
    if kind == "banned":
        users = [u for u in users if u.get("is_banned")]
    elif kind == "premium":
        users = [u for u in users if is_premium_user(u)]
    page = max(0, int(page))
    total_pages = max(1, math.ceil(len(users) / ADMIN_PAGE_SIZE))
    page = min(page, total_pages - 1)
    return users[page * ADMIN_PAGE_SIZE:(page + 1) * ADMIN_PAGE_SIZE], page, total_pages, len(users)

def _users_page_keyboard(kind: str, page: int, total_pages: int, users: list):
    rows = []
    for u in users:
        uid = u.get("id")
        icon = "lock" if u.get("is_banned") else "premium" if is_premium_user(u) else "user"
        rows.append([modern_button(_user_display(u)[:48], f"admin_user:{uid}", style="danger" if u.get("is_banned") else "primary", emoji_name=icon)])
    nav = []
    if page > 0:
        nav.append(modern_button("Prev", f"admin_{kind}:{page-1}", style="primary", emoji_name="link"))
    if page + 1 < total_pages:
        nav.append(modern_button("Next", f"admin_{kind}:{page+1}", style="primary", emoji_name="link"))
    if nav:
        rows.append(nav)
    rows.append([modern_button("Admin Panel", "admin_panel", style="primary", emoji_name="crown")])
    return InlineKeyboardMarkup(rows)

async def show_admin_panel(update, edit=True):
    if not is_admin(update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("Admin only", show_alert=True)
        return
    text = admin_dashboard_text()
    markup = admin_panel_keyboard()
    if edit and update.callback_query:
        await safe_edit(update.callback_query, text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await safe_reply(update.effective_message, text, parse_mode=ParseMode.HTML, reply_markup=markup)

async def admin_users_page(update, kind: str, page: int):
    users, page, total_pages, total = _paged_users(kind, page)
    title = {"users": "ALL USERS", "banned": "BANNED", "premium": "PREMIUM"}.get(kind, "USERS")
    lines = [
        f"{ce('users', '•')} <b>{title}</b>",
        f"{ce('analytics', '•')} Page <code>{page+1}/{total_pages}</code> • Total <code>{total}</code>",
        "",
    ]
    for idx, u in enumerate(users, start=page * ADMIN_PAGE_SIZE + 1):
        status = ce('lock', '•') if u.get('is_banned') else ce('premium', '•') if is_premium_user(u) else ce('check', '•')
        lines.append(f"{status} <b>{idx}.</b> {_user_display(u)}")
    if not users:
        lines.append(f"{ce('shield', '•')} No users found.")
    await safe_edit(update.callback_query, "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_users_page_keyboard(kind, page, total_pages, users))

async def admin_user_detail(update, user_id: int):
    user = get_user(user_id)
    if not user:
        await safe_edit(update.callback_query, f"{ce('lock', '•')} <b>User not found.</b>", parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
        return
    banned = bool(user.get("is_banned"))
    premium = is_premium_user(user)
    text = (
        f"{ce('user', '•')} <b>USER DETAILS</b>\n\n"
        f"{ce('database', '•')} <b>ID:</b> <code>{user.get('id')}</code>\n"
        f"{ce('link', '•')} <b>Username:</b> {esc('@'+user['username'] if user.get('username') else 'not set')}\n"
        f"{ce('verified', '•')} <b>Name:</b> {esc(' '.join(x for x in [user.get('first_name'), user.get('last_name')] if x) or 'Unknown')}\n"
        f"{ce('shield', '•')} <b>Status:</b> {'BANNED' if banned else 'ACTIVE'}\n"
        f"{ce('premium', '•')} <b>Plan:</b> {esc(premium_label(user))}\n"
        f"{ce('search', '•')} <b>Total searches:</b> {user.get('total_searches', 0)}\n"
        f"{ce('bolt', '•')} <b>Daily used:</b> {user.get('daily_searches', 0)}\n"
        f"{ce('gift', '•')} <b>Bonus:</b> {user.get('bonus_searches', 0)}\n"
        f"{ce('users', '•')} <b>Referrals:</b> {len(user.get('referrals', []))}"
    )
    rows = []
    if banned:
        rows.append([modern_button("Unban User", f"admin_unban:{user_id}", style="success", emoji_name="check")])
    else:
        if user_id not in ADMIN_USER_IDS:
            rows.append([modern_button("Ban User", f"admin_ban:{user_id}", style="danger", emoji_name="lock")])
    if premium:
        rows.append([modern_button("Remove Premium", f"admin_premium_remove:{user_id}", style="danger", emoji_name="lock")])
    else:
        rows.append([
            modern_button("Premium 7d", f"admin_premium_add:{user_id}:7", style="success", emoji_name="premium"),
            modern_button("Premium 30d", f"admin_premium_add:{user_id}:30", style="success", emoji_name="crown"),
        ])
    rows.append([modern_button("Reset Limits", f"admin_reset:{user_id}", style="primary", emoji_name="bolt")])
    rows.append([modern_button("Admin Panel", "admin_panel", style="primary", emoji_name="crown")])
    await safe_edit(update.callback_query, text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))

def force_join_admin_text() -> str:
    channels = get_force_join_channels()
    lines = [f"{ce('shield', '•')} <b>FORCE JOIN MANAGER</b>", ""]
    if channels:
        lines.append(f"{ce('users', '•')} <b>{len(channels)} configured:</b>")
        for idx, c in enumerate(channels, 1):
            status = "ON" if c.get("enabled") else "OFF"
            lines.append(f"{idx}. <b>{esc(c.get('title') or c.get('chat'))}</b> [{status}]")
    else:
        lines.append(f"{ce('lock', '•')} No channels configured.")
    lines.extend(["", f"{ce('tools', '•')} Format: <code>chat | url | title</code>"])
    return "\n".join(lines)

def force_join_admin_keyboard():
    channels = get_force_join_channels()
    rows = []
    for c in channels:
        label = (c.get("title") or c.get("chat") or "Channel")[:26]
        toggle_label = f"{'Turn Off' if c.get('enabled') else 'Turn On'}: {label}"
        rows.append([
            modern_button(toggle_label, f"admin_fj_toggle:{c['id']}", style="success" if c.get("enabled") else "danger", emoji_name="shield"),
            modern_button("Remove", f"admin_fj_remove:{c['id']}", style="danger", emoji_name="lock"),
        ])
    rows.append([modern_button("Add Channel / Group", "admin_forcejoin_add", style="primary", emoji_name="link")])
    rows.append([modern_button("Back to Admin", "admin_panel", style="primary", emoji_name="crown")])
    return InlineKeyboardMarkup(rows)

async def admin_forcejoin_view(update: Update):
    await safe_edit(update.callback_query, force_join_admin_text(), parse_mode=ParseMode.HTML, reply_markup=force_join_admin_keyboard())

async def admin_forcejoin_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.application.bot_data.setdefault("force_join_pending_admin", {})[str(update.effective_user.id)] = True
    await safe_edit(
        update.callback_query,
        f"{ce('link', '•')} <b>ADD CHANNEL / GROUP</b>\n\n"
        f"Send in this format:\n\n"
        f"<code>chat | join_url | title</code>\n\n"
        f"Example:\n"
        f"<code>@yourchannel | https://t.me/yourchannel | My Channel</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[modern_button("Cancel", "admin_forcejoin", style="danger", emoji_name="lock")]]))

async def admin_forcejoin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not is_admin(update.effective_user.id):
        return False
    pending = context.application.bot_data.get("force_join_pending_admin", {})
    if not pending.get(str(update.effective_user.id)):
        return False
    raw = (update.effective_message.text or "").strip()
    if raw.lower() == "/cancel":
        pending.pop(str(update.effective_user.id), None)
        await safe_reply(update.effective_message, f"{ce('lock', '•')} Cancelled.", parse_mode=ParseMode.HTML)
        return True
    parts = [p.strip() for p in raw.split("|", 2)]
    if len(parts) < 2:
        await safe_reply(update.effective_message, f"{ce('lock', '•')} Format: <code>chat | url | title</code>", parse_mode=ParseMode.HTML)
        return True
    chat = parts[0]
    url = parts[1]
    title = parts[2] if len(parts) == 3 and parts[2] else chat
    channels = get_force_join_channels()
    channels.append({
        "id": secrets.token_hex(4),
        "enabled": True,
        "chat": chat,
        "url": url,
        "title": title[:100],
    })
    pending.pop(str(update.effective_user.id), None)
    save_db(DB)
    await safe_reply(
        update.effective_message,
        f"{ce('check', '•')} <b>Channel added.</b>\n\n{force_join_admin_text()}",
        parse_mode=ParseMode.HTML,
        reply_markup=force_join_admin_keyboard())
    return True

# =============================================================================
# CALLBACK HANDLER
# =============================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    await query.answer()
    if await enforce_force_join(update):
        return
    # Number Info button
    if data.startswith("numinfo:"):
        number = re.sub(r"\D", "", data.split(":", 1)[1])

        if len(number) < 10:
            await query.answer("Invalid number.", show_alert=True)
            return

        # Fetch Number Info
        result = await lookup_number(number)
        results = _number_results(result)

        if not results:
            await safe_edit(
                query,
                fmt_number(result, number),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [
                        modern_button(
                            "Back",
                            "deep_back",
                            style="primary",
                            emoji_name="search"
                        ),
                        modern_button(
                            "Home",
                            "home",
                            style="primary",
                            emoji_name="star"
                        )
                    ]
                ])
            )
            return

        # Save all results for pagination
        context.user_data["number_info"] = {
            "number": number,
            "results": results,
        }

        # First page
        await safe_edit(
            query,
            _format_number_detail(
                results[0],
                number,
                0,
                len(results)
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=_number_detail_keyboard(
                0,
                len(results),
                number,
                results
            )
        )
        return

        # Back -> restore the previous Telegram lookup result.
        if data == "back_tg":
            previous = context.user_data.get("last_tg_result")
        if previous:
            await safe_edit(
                query,
                previous["text"],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=deep_analysis_keyboard(previous["number"]),
            )
        else:
            user = ensure_user(query.from_user)
            await safe_edit(
                query,
                home_text(user),
                parse_mode=ParseMode.HTML,
                reply_markup=main_keyboard(user),
            )
        return

    if data == "help":
        user = ensure_user(query.from_user)
        await safe_edit(
            query,
            help_text(user),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=back_keyboard(),
        )
        return
    
    # -------------------------------------------------------------------------
    # NUMBER INFO PAGINATION / DOWNLOAD / BACK
    # -------------------------------------------------------------------------
    if data == "num_back":
        user = ensure_user(query.from_user)
        await safe_edit(
            query,
            home_text(user),
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(user)
        )
        return

    if data.startswith("num_page:"):
        try:
            index = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("Invalid page.", show_alert=True)
            return

        state = context.user_data.get("number_info") or {}
        results = state.get("results") or []
        number = state.get("number") or ""

        if not results or not number or index < 0 or index >= len(results):
            await query.answer("Number Info session expired.", show_alert=True)
            return

        await safe_edit(
            query,
            f"{ce('search', '🔎')} <b>Loading result {index + 1}/{len(results)}...</b>",
            parse_mode=ParseMode.HTML,
        )

        await asyncio.sleep(0.12)

        await safe_edit(
            query,
            _format_number_detail(results[index], number, index, len(results)),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=_number_detail_keyboard(index, len(results), number, results)
        )
        schedule_message_delete(query.message, result_delete_seconds())
        return

    if data.startswith("num_json:"):
        state = context.user_data.get("number_info") or {}
        results = state.get("results") or []
        number = state.get("number") or ""

        if not results or not number:
            await query.answer(
                "Number Info session expired.",
                show_alert=True
            )
            return

        # Download ALL Number Info results
        payload = _number_download_payload(
            results,
            number
        )

        filename = (
            f"number_info_"
            f"{re.sub(r'\\D', '', number)}"
            f"_all.json"
        )

        content = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        from io import BytesIO

        document = BytesIO(content)
        document.name = filename

        await query.answer("Preparing complete JSON...")

        await query.message.reply_document(
            document=document,
            caption=(
                f"{ce('database', '🗄️')} "
                f"<b>Number Info JSON</b>\n"
                f"{ce('premium', '⭐')} "
                f"<b>Total Results:</b> "
                f"<code>{len(results)}</code>\n"
                f"{ce('phone', '📱')} "
                f"<b>Number:</b> "
                f"<code>{esc(number)}</code>"
            ),
            parse_mode=ParseMode.HTML
        )

        return

    # Deep Analysis → Number Info
    if data.startswith("deepnum:"):
        number = data.split(":", 1)[1].strip()
        if not number:
            await query.answer("Invalid number.", show_alert=True)
            return

        # Preserve the Telegram lookup message so Back can return to it.
        context.user_data["deep_analysis_back"] = {
            "text": query.message.text_html or query.message.text or "",
            "reply_markup": query.message.reply_markup,
        }

        await safe_edit(
            query,
            f"{ce('analytics', '🔎')} <b>DEEP ANALYSIS</b>\n\n"
            f"{ce('search', '🔎')} <b>Initializing...</b>",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(0.35)

        await safe_edit(
            query,
            f"{ce('analytics', '🔎')} <b>DEEP ANALYSIS</b>\n\n"
            f"{ce('search', '🔎')} <b>Querying Number Info...</b>\n"
            f"{ce('speed', '💨')} <b>Analyzing:</b> <code>{esc(number)}</code>",
            parse_mode=ParseMode.HTML
        )

        result = await lookup_number(number)
        results = _number_results(result)

        if not results:
            await safe_edit(
                query,
                fmt_number(result, number),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [
                        modern_button("Back", "deep_back", style="primary", emoji_name="search"),
                        modern_button("Home", "home", style="primary", emoji_name="star"),
                    ]
                ])
            )
            return

        context.user_data["number_info"] = {
            "number": number,
            "results": results,
        }

        await safe_edit(
            query,
            f"{ce('analytics', '🔎')} <b>DEEP ANALYSIS</b>\n\n"
            f"{ce('search', '🔎')} <b>Processing response...</b>",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(0.25)

        await safe_edit(
            query,
            f"{ce('analytics', '🔎')} <b>DEEP ANALYSIS</b>\n\n"
            f"{ce('check', '✅')} <b>Analysis completed.</b>\n\n"
            f"{ce('phone', '📱')} <b>Number:</b> <code>{esc(number)}</code>\n"
            f"{ce('database', '🗄️')} <b>Records found:</b> <code>{len(results)}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [
                    modern_button(
                        "Number Info",
                        f"numinfo:{number}",
                        style="success",
                        emoji_name="phone"
                    )
                ],
                [
                    modern_button(
                        "Back",
                        "deep_back",
                        style="primary",
                        emoji_name="search"
                    ),
                    modern_button(
                        "Home",
                        "home",
                        style="primary",
                        emoji_name="star"
                    )
                ]
            ])
        )
        return
        

    if data == "deep_back":
        saved = context.user_data.get("deep_analysis_back")
        if saved and saved.get("text"):
            await safe_edit(
                query,
                saved["text"],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=saved.get("reply_markup")
            )
        else:
            user = ensure_user(query.from_user)
            await safe_edit(
                query,
                home_text(user),
                parse_mode=ParseMode.HTML,
                reply_markup=main_keyboard(user)
            )
        return

    # Force join check
    if data == "forcejoin_check":
        missing = await force_join_required(update)
        if missing:
            await enforce_force_join(update)
        else:
            user = ensure_user(query.from_user)
            await safe_edit(query, home_text(user), parse_mode=ParseMode.HTML, reply_markup=main_keyboard(user))
        return

    # Admin
    if data.startswith("admin_") or data == "admin_panel":
        await admin_callback(update, context, data)
        return

    # Home
    if data == "home":
        user = ensure_user(query.from_user)
        await safe_edit(query, home_text(user), parse_mode=ParseMode.HTML, reply_markup=main_keyboard(user))
        return

    if data == "profile":
        await show_profile(update)
        return

    if data == "refer":
        await show_referral(update)
        return

    if data == "stats":
        user = ensure_user(query.from_user)
        text = (
            f"{ce('analytics', '•')} <b>STATISTICS</b>\n\n"
            f"{ce('users', '•')} <b>Users:</b> {len(DB['users'])}\n"
            f"{ce('search', '•')} <b>Total searches:</b> {len(DB['searches'])}\n"
            f"{ce('gift', '•')} <b>Referrals:</b> {len(DB['referrals'])}\n\n"
            f"{ce('speed', '•')} <b>Your searches:</b> {user.get('total_searches',0)}\n"
            f"{ce('target', '•')} <b>Your referrals:</b> {len(user.get('referrals',[]))}"
        )
        await safe_edit(query, text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
        return

    if data.startswith("mod_"):
        module = data.split("_", 1)[1]
        if module not in MODULE_NAMES:
            await safe_edit(query, "• Module unavailable", parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
            return
        context.user_data["pending_module"] = module
        await safe_edit(
            query,
            _pending_prompt(module),
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_keyboard()
        )
        return

# =============================================================================
# ADMIN CALLBACK
# =============================================================================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    q = update.callback_query
    if not is_admin(update.effective_user.id):
        await q.answer("Admin only", show_alert=True)
        return
    try:
        if data == "admin_panel":
            await show_admin_panel(update)
        elif data == "admin_dashboard":
            await safe_edit(q, admin_dashboard_text(), parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        elif data.startswith("admin_users:"):
            await admin_users_page(update, "users", int(data.split(":", 1)[1]))
        elif data.startswith("admin_banned:"):
            await admin_users_page(update, "banned", int(data.split(":", 1)[1]))
        elif data.startswith("admin_premium:"):
            await admin_users_page(update, "premium", int(data.split(":", 1)[1]))
        elif data.startswith("admin_user:"):
            await admin_user_detail(update, int(data.split(":", 1)[1]))
        elif data.startswith("admin_ban:"):
            uid = int(data.split(":", 1)[1])
            u = get_user(uid)
            if u:
                u["is_banned"] = True
                save_db(DB)
            await admin_user_detail(update, uid)
        elif data.startswith("admin_unban:"):
            uid = int(data.split(":", 1)[1])
            u = get_user(uid)
            if u:
                u["is_banned"] = False
                save_db(DB)
            await admin_user_detail(update, uid)
        elif data.startswith("admin_premium_add:"):
            _, uid, days = data.split(":")
            uid, days = int(uid), int(days)
            u = get_user(uid)
            if u:
                grant_premium(u, days)
            await admin_user_detail(update, uid)
        elif data.startswith("admin_premium_remove:"):
            uid = int(data.split(":", 1)[1])
            u = get_user(uid)
            if u:
                revoke_premium(u)
            await admin_user_detail(update, uid)
        elif data.startswith("admin_reset:"):
            uid = int(data.split(":", 1)[1])
            u = get_user(uid)
            if u:
                reset_user_limits(u)
            await admin_user_detail(update, uid)
        elif data == "admin_reset_all":
            count = 0
            for u in DB["users"].values():
                reset_user_limits(u)
                count += 1
            await safe_edit(q, f"{ce('check', '•')} <b>Reset {count} users.</b>", parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
        elif data == "admin_broadcast":
            context.user_data["admin_broadcast_mode"] = True
            await safe_edit(
                q,
                f"{ce('rocket', '•')} <b>BROADCAST MODE</b>\n\nSend the message to broadcast.\nSend /cancel to abort.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[modern_button("Cancel", "admin_panel", style="danger", emoji_name="lock")]]))
        elif data == "admin_find":
            context.user_data["admin_find_mode"] = True
            await safe_edit(
                q,
                f"{ce('search', '•')} <b>FIND USER</b>\n\nSend user ID or @username.\nSend /cancel to abort.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[modern_button("Cancel", "admin_panel", style="danger", emoji_name="lock")]]))
        elif data == "admin_update_restart":
            started = launch_update_restart()
            if started:
                await safe_edit(
                    q,
                    f"{ce('tools', '•')} <b>UPDATE &amp; RESTART</b>\n\n"
                    f"GitHub update has started.\n"
                    f"The bot will restart automatically after the update.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=admin_back_keyboard(),
                )
            else:
                await q.answer("Update script not found or could not start.", show_alert=True)

        elif data == "admin_system":
            import platform
            text = (
                f"{ce('tools', '•')} <b>SYSTEM INFO</b>\n\n"
                f"{ce('verified', '•')} <b>Python:</b> {platform.python_version()}\n"
                f"{ce('network', '•')} <b>Platform:</b> {esc(platform.system())} {esc(platform.release())}\n"
                f"{ce('users', '•')} <b>Users:</b> {len(DB['users'])}\n"
                f"{ce('search', '•')} <b>Searches:</b> {len(DB['searches'])}\n"
                f"{ce('shield', '•')} <b>Force-join:</b> {len(get_force_join_channels())}"
            )
            await safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
        elif data == "admin_delete_timer":
            context.user_data["admin_delete_timer_mode"] = True
            await safe_edit(
                q,
                f"{ce('lock', '•')} <b>DELETE TIMER</b>\\n\\n"
                f"Send: <code>INPUT_SECONDS RESULT_SECONDS</code>\\n"
                f"Example: <code>1 120</code>\\n\\n"
                f"Set <code>0</code> to disable either timer.\\n"
                f"Input messages are normally deleted after 1 second.\\n"
                f"Bot results are normally deleted after 120 seconds.\\n\\n"
                f"Send /cancel to abort.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[modern_button("Cancel", "admin_panel", style="danger", emoji_name="lock")]])
            )
        elif data == "admin_premium_add_custom":
            context.user_data["admin_premium_custom_mode"] = True
            await safe_edit(
                q,
                f"{ce('premium', '•')} <b>CUSTOM PREMIUM</b>\\n\\n"
                f"Send: <code>USER_ID DAYS</code>\\n"
                f"Example: <code>123456789 30</code>\\n\\n"
                f"Existing premium time is extended from its current expiry.\\n"
                f"Send /cancel to abort.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[modern_button("Cancel", "admin_panel", style="danger", emoji_name="lock")]])
            )
        elif data == "admin_maintenance":
            enabled = not maintenance_enabled()
            DB.setdefault("settings", {})["maintenance_mode"] = enabled
            save_db(DB)
            await safe_edit(
                q,
                f"{ce('tools', '•')} <b>MAINTENANCE MODE</b>\n\n"
                f"Status: <b>{'ON' if enabled else 'OFF'}</b>\n\n"
                f"Non-admin users are {'blocked' if enabled else 'allowed'} while maintenance is {'active' if enabled else 'disabled'}.",
                parse_mode=ParseMode.HTML,
                reply_markup=admin_panel_keyboard()
            )
        elif data == "admin_forcejoin":
            await admin_forcejoin_view(update)
        elif data == "admin_forcejoin_add":
            await admin_forcejoin_add_prompt(update, context)
        elif data.startswith("admin_fj_toggle:"):
            cid = data.split(":", 1)[1]
            for c in get_force_join_channels():
                if c.get("id") == cid:
                    c["enabled"] = not c.get("enabled", True)
                    break
            save_db(DB)
            await admin_forcejoin_view(update)
        elif data.startswith("admin_fj_remove:"):
            cid = data.split(":", 1)[1]
            DB["settings"]["force_join"] = [c for c in get_force_join_channels() if c.get("id") != cid]
            save_db(DB)
            await admin_forcejoin_view(update)
    except Exception as e:
        logger.exception(f"Admin callback error: {e}")
        try:
            await q.answer("Error", show_alert=True)
        except Exception:
            pass

# =============================================================================
# TEXT HANDLER
# =============================================================================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text:
        return
    text = update.effective_message.text.strip()

    # Only active module/search input is ephemeral. Normal messages stay untouched.
    pending_module = context.user_data.get("pending_module")
    if pending_module and not is_admin(update.effective_user.id):
        await delete_user_search_message(update)

    # Admin delete timer mode
    if context.user_data.get("admin_delete_timer_mode"):
        if text.lower() == "/cancel":
            context.user_data.pop("admin_delete_timer_mode", None)
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Cancelled.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        parts = text.split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Format: <code>INPUT_SECONDS RESULT_SECONDS</code>", parse_mode=ParseMode.HTML)
            return
        input_seconds, result_seconds = map(int, parts)
        if input_seconds > 86400 or result_seconds > 86400:
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Maximum timer is 86400 seconds.", parse_mode=ParseMode.HTML)
            return
        DB.setdefault("settings", {})["user_delete_seconds"] = input_seconds
        DB["settings"]["result_delete_seconds"] = result_seconds
        save_db(DB)
        context.user_data.pop("admin_delete_timer_mode", None)
        await safe_reply(
            update.effective_message,
            f"{ce('check', '•')} <b>Delete timers updated.</b>\\n\\n"
            f"Input messages: <code>{input_seconds}s</code>\\n"
            f"Bot results: <code>{result_seconds}s</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard()
        )
        return

    # Admin custom premium mode
    if context.user_data.get("admin_premium_custom_mode"):
        if text.lower() == "/cancel":
            context.user_data.pop("admin_premium_custom_mode", None)
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Cancelled.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        parts = text.split()
        if len(parts) != 2 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit() or int(parts[1]) < 1:
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Format: <code>USER_ID DAYS</code>", parse_mode=ParseMode.HTML)
            return
        uid, days = int(parts[0]), int(parts[1])
        target = get_user(uid)
        if not target:
            context.user_data.pop("admin_premium_custom_mode", None)
            await safe_reply(update.effective_message, f"{ce('lock', '•')} User not found.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        grant_premium(target, days)
        context.user_data.pop("admin_premium_custom_mode", None)
        await safe_reply(update.effective_message, f"{ce('check', '•')} <b>Premium added.</b>\\n\\nUser: <code>{uid}</code>\\nDuration: <code>{days} days</code>\\nPlan: {esc(premium_label(target))}", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        return

    # Admin broadcast mode
    if context.user_data.get("admin_broadcast_mode"):
        if text.lower() == "/cancel":
            context.user_data.pop("admin_broadcast_mode", None)
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Cancelled.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        context.user_data.pop("admin_broadcast_mode", None)
        users = [u for u in DB["users"].values() if not u.get("is_banned")]
        sent = failed = 0
        status = await safe_reply(update.effective_message, f"{ce('rocket', '•')} Broadcasting to {len(users)} users...", parse_mode=ParseMode.HTML)
        for u in users:
            try:
                await context.bot.send_message(chat_id=int(u["id"]), text=text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await safe_edit_message(status,
            f"{ce('check', '•')} <b>Broadcast complete</b>\n\n"
            f"{ce('verified', '•')} Sent: <code>{sent}</code>\n"
            f"{ce('lock', '•')} Failed: <code>{failed}</code>",
            parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        return

    # Admin find mode
    if context.user_data.get("admin_find_mode"):
        if text.lower() == "/cancel":
            context.user_data.pop("admin_find_mode", None)
            await safe_reply(update.effective_message, f"{ce('lock', '•')} Cancelled.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        context.user_data.pop("admin_find_mode", None)
        target = None
        if text.lstrip("-").isdigit():
            target = get_user(int(text))
        else:
            username = text.lstrip("@").lower()
            target = next((u for u in DB["users"].values() if (u.get("username") or "").lower() == username), None)
        if not target:
            await safe_reply(update.effective_message, f"{ce('lock', '•')} User not found.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        await admin_user_detail(update, target["id"])
        return

    # Admin force join mode
    if context.application.bot_data.get("force_join_pending_admin", {}).get(str(update.effective_user.id)):
        await admin_forcejoin_text_handler(update, context)
        return

    # Pending module
    module = context.user_data.get("pending_module")
    if not module:
        return
    context.user_data.pop("pending_module", None)

    if await enforce_force_join(update):
        return

    if module == "tg":
        await handle_tg(update, context, text)
    elif module == "aadhar":
        await handle_aadhar(update, context, text)
    elif module == "num":
        await handle_num(update, context, text)
    elif module == "veh":
        await handle_veh(update, context, text)
    elif module == "imei":
        await handle_imei(update, context, text)
    elif module == "user":
        await handle_user(update, context, text)
    elif module == "target":
        await handle_target(update, context, text)
    elif module == "email":
        await handle_email(update, context, text)
    elif module == "darkweb":
        await handle_darkweb(update, context, text)

# =============================================================================
# COMMANDS
# =============================================================================
async def process_start_referral(context: ContextTypes.DEFAULT_TYPE, user: dict):
    if not context.args:
        return
    code = str(context.args[0]).strip()
    if not code.startswith("ref_") or user.get("referred_by") or code == user.get("ref_code"):
        return
    referrer = next((u for u in DB["users"].values() if u.get("ref_code") == code), None)
    if not referrer or referrer.get("id") == user.get("id"):
        return
    user["referred_by"] = referrer.get("id")
    referrer.setdefault("referrals", [])
    if user.get("id") not in referrer["referrals"]:
        referrer["referrals"].append(user.get("id"))
        referrer["bonus_searches"] = int(referrer.get("bonus_searches", 0)) + REFERRAL_BONUS
        DB.setdefault("referrals", []).append({
            "referrer_id": referrer.get("id"),
            "referred_id": user.get("id"),
            "created_at": now_iso(),
        })
        save_db(DB)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    user = ensure_user(update.effective_user)
    await process_start_referral(context, user)
    if user.get("is_banned"):
        await safe_reply(update.message, f"{ce('lock', '•')} <b>Access restricted.</b>", parse_mode=ParseMode.HTML)
        return
    if await enforce_force_join(update):
        return
    context.user_data.pop("pending_module", None)
    await safe_reply(update.message, home_text(user), parse_mode=ParseMode.HTML, reply_markup=main_keyboard(user))

async def cmd_tg(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/tg 9876543210</code> or <code>/tg @username</code>", parse_mode=ParseMode.HTML)
        return
    await handle_tg(update, context, " ".join(context.args))

async def cmd_aadhar(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/aadhar 123456789012</code>", parse_mode=ParseMode.HTML)
        return
    await handle_aadhar(update, context, " ".join(context.args))

async def cmd_num(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/num 9876543210</code>", parse_mode=ParseMode.HTML)
        return
    await handle_num(update, context, " ".join(context.args))

async def cmd_veh(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/veh UP63AS0001</code>", parse_mode=ParseMode.HTML)
        return
    await handle_veh(update, context, " ".join(context.args))

async def cmd_user(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/user username</code>", parse_mode=ParseMode.HTML)
        return
    await handle_user(update, context, " ".join(context.args))

async def cmd_target(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/target domain.com</code>", parse_mode=ParseMode.HTML)
        return
    await handle_target(update, context, " ".join(context.args))

async def cmd_email(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/email name@example.com</code>", parse_mode=ParseMode.HTML)
        return
    await handle_email(update, context, " ".join(context.args))

async def cmd_darkweb(update, context):
    await delete_user_search_message(update)
    if await enforce_force_join(update): return
    if not context.args:
        await safe_reply(update.message, f"{ce('lock', '•')} Usage: <code>/darkweb query</code>", parse_mode=ParseMode.HTML)
        return
    await handle_darkweb(update, context, " ".join(context.args))

async def cmd_profile(update, context):
    if await enforce_force_join(update): return
    await show_profile(update, edit=False)

async def cmd_refer(update, context):
    if await enforce_force_join(update): return
    await show_referral(update, edit=False)

async def cmd_admin(update, context):
    await show_admin_panel(update, edit=False)

async def cmd_cancel(update, context):
    context.user_data.pop("pending_module", None)
    context.user_data.pop("admin_broadcast_mode", None)
    context.user_data.pop("admin_find_mode", None)
    context.user_data.pop("admin_premium_custom_mode", None)
    context.user_data.pop("admin_delete_timer_mode", None)
    context.application.bot_data.setdefault("force_join_pending_admin", {}).pop(str(update.effective_user.id), None)
    await safe_reply(update.message, f"{ce('check', '•')} <b>Cancelled.</b>", parse_mode=ParseMode.HTML, reply_markup=main_keyboard(ensure_user(update.effective_user)))

# =============================================================================
# ERROR HANDLER
# =============================================================================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update caused error: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("• <b>An error occurred.</b>", parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await update.effective_message.reply_text("• An error occurred.")
            except Exception:
                pass

# =============================================================================
# MAIN
# =============================================================================
def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN missing")
        sys.exit(1)
    logger.info("• DEMON OSINT BOT v5.1 starting...")
    logger.info(f"Platforms: {len(PLATFORM_MAP)} | Ports: {len(COMMON_PORTS)}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("tg", cmd_tg))
    app.add_handler(CommandHandler("aadhar", cmd_aadhar))
    app.add_handler(CommandHandler("num", cmd_num))
    app.add_handler(CommandHandler("veh", cmd_veh))
    app.add_handler(CommandHandler("user", cmd_user))
    app.add_handler(CommandHandler("target", cmd_target))
    app.add_handler(CommandHandler("email", cmd_email))
    app.add_handler(CommandHandler("darkweb", cmd_darkweb))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("refer", cmd_refer))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, image_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    app.add_error_handler(error_handler)
    logger.info("• Bot operational.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
