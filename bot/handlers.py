import io
import os
import time
import uuid
import math
import asyncio
import logging
import urllib.parse
from typing import Dict, Any, Optional
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from core.config import ConfigManager
from core.s3 import S3Client
from core.downloader import HTTPDownloader
from core.manager import TaskManager, TaskProgress
from database.db import Database
from bot.keyboards import (
    get_main_keyboard, get_help_keyboard, get_settings_keyboard,
    get_chunk_size_keyboard, get_s3_file_options_keyboard,
    get_share_expiry_keyboard, get_user_manage_keyboard, COMMANDS_LIST
)

logger = logging.getLogger("ZohalHandlers")

# Global state management
user_states: Dict[int, Dict[str, Any]] = {}
callback_registry: Dict[str, str] = {}
media_upload_states: Dict[str, Dict[str, Any]] = {}


def parse_proxy_string(proxy_str: str) -> Optional[dict]:
    """Parse proxy string into structured format."""
    try:
        if "://" not in proxy_str:
            proxy_str = "socks5://" + proxy_str
        parsed = urllib.parse.urlparse(proxy_str)
        scheme = parsed.scheme.lower()
        if scheme not in ["socks5", "http", "https"]:
            return None
        
        netloc = parsed.netloc
        if "@" in netloc:
            auth, host_port = netloc.split("@", 1)
            username, password = auth.split(":", 1) if ":" in auth else (auth, "")
        else:
            host_port = netloc
            username, password = "", ""
            
        host, port = host_port.split(":", 1) if ":" in host_port else (host_port, 1080)
        return {
            "name": f"پروکسی {host}",
            "scheme": scheme,
            "host": host,
            "port": int(port),
            "username": username,
            "password": password
        }
    except Exception:
        return None


def register_short_key(key: str) -> str:
    """Register S3 key under short ID for Telegram callback limits (<64 bytes)."""
    short_id = f"s_{uuid.uuid4().hex[:8]}"
    callback_registry[short_id] = key
    if len(callback_registry) > 5000:
        keys_to_remove = list(callback_registry.keys())[:1000]
        for k in keys_to_remove:
            callback_registry.pop(k, None)
    return short_id


def resolve_short_key(short_id: str) -> Optional[str]:
    """Resolve short key back to original S3 key."""
    return callback_registry.get(short_id)


async def check_auth(client: Client, message_or_query) -> bool:
    """Verify user authorization."""
    if isinstance(message_or_query, CallbackQuery):
        user_id = message_or_query.from_user.id
        msg = message_or_query.message
        is_cb = True
    else:
        user_id = message_or_query.from_user.id
        msg = message_or_query
        is_cb = False
        
    config = await ConfigManager.get_config()
    owner_id = int(config.get("owner_id", 0))
    
    if user_id == owner_id:
        return True
        
    authorized = await Database.is_user_authorized(user_id)
    if not authorized:
        if is_cb:
            await message_or_query.answer(
                f"❌ شما مجاز به استفاده از این ربات نیستید.\nشناسه شما: {user_id}",
                show_alert=True
            )
        else:
            await msg.reply(
                f"❌ **شما مجاز به استفاده از این ربات نیستید.**\n\n"
                f"🆔 شناسه کاربری شما: `{user_id}`\n"
                f"لطفاً جهت دسترسی این شناسه را به مدیر ربات ارسال کنید.",
                quote=True
            )
        return False
    return True


def register_all_handlers(app: Client):
    """Register all bot command and callback handlers."""
    
    # ==================== CORE COMMANDS ====================
    
    @app.on_message(filters.command("start") & filters.private)
    async def cmd_start(client: Client, message: Message):
        """Bot start command."""
        user_id = message.from_user.id
        config = await ConfigManager.get_config()
        owner_id = int(config.get("owner_id", 0))
        
        is_admin = (user_id == owner_id)
        if is_admin:
            await Database.add_user(user_id, message.from_user.username, message.from_user.first_name, is_admin=True)
            
        authorized = is_admin or await Database.is_user_authorized(user_id)
        
        if not authorized:
            await message.reply(
                f"⚠️ **ربات آپلودر زحل**\n\n"
                f"دسترسی شما مجاز نمی‌باشد.\n"
                f"🆔 شناسه شما: `{user_id}`"
            )
            return

        welcome_text = (
            f"🪐 **به ربات هوشمند آپلودر زحل خوش آمدید!**\n\n"
            f"این ربات بدون پر کردن سرور، فایل‌ها را بین تلگرام و S3 منتقل می‌کند.\n\n"
            f"**برای شروع:**\n"
            f"• `📤 آپلود` برای ارسال فایل یا لینک\n"
            f"• `📁 فایل‌های S3` برای مدیریت فایل‌ها\n"
            f"• `📚 راهنما` برای جزئیات کامل\n"
        )
        await message.reply(welcome_text, reply_markup=get_main_keyboard(is_admin))

    @app.on_message(filters.command("help") & filters.private)
    async def cmd_help(client: Client, message: Message):
        """Help command with feature list."""
        if not await check_auth(client, message):
            return
        
        help_text = (
            f"📚 **راهنمای ربات آپلودر زحل**\n\n"
            f"**🔹 ویژگی‌های اصلی:**\n"
            f"1️⃣ **URL → S3:** لینک دانلود را بفرستید، بدون مصرف دیسک در S3 ذخیره می‌شود\n"
            f"2️⃣ **تلگرام → S3:** فایل تا ۲GB را مستقیم به S3 منتقل کنید\n"
            f"3️⃣ **S3 → تلگرام:** فایل‌های S3 را دانلود کنید\n"
            f"4️⃣ **دور زدن فیلترینگ:** پروکسی SOCKS5/HTTP برای ایران\n"
            f"5️⃣ **لینک‌های موقت:** ساخت لینک‌های زمان‌دار\n\n"
            f"**⚙️ دستورات:**\n"
            f"/upload - آپلود فایل یا لینک\n"
            f"/s3 - مدیریت فایل‌های S3\n"
            f"/settings - تنظیمات\n"
            f"/stats - وضعیت سرور\n"
        )
        await message.reply(help_text, reply_markup=get_help_keyboard())

    @app.on_message(filters.command("settings") & filters.private)
    async def cmd_settings(client: Client, message: Message):
        """Settings command."""
        if not await check_auth(client, message):
            return
        config = await ConfigManager.get_config()
        await message.reply(
            "⚙️ **تنظیمات ربات زحل**",
            reply_markup=get_settings_keyboard(config)
        )

    @app.on_message(filters.command("stats") & filters.private)
    async def cmd_stats(client: Client, message: Message):
        """Server and S3 stats."""
        if not await check_auth(client, message):
            return
        
        import psutil
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        start = time.time()
        s3_ok = await s3.test_connection()
        latency = (time.time() - start) * 1000
        
        stats_text = (
            f"📊 **وضعیت سرور و S3**\n\n"
            f"**سرور:**\n"
            f"🖥 CPU: {cpu}%\n"
            f"💾 RAM: {ram}%\n"
            f"💽 دیسک: {disk}%\n\n"
            f"**S3:**\n"
            f"{'✅ متصل' if s3_ok else '❌ قطع‌شده'}\n"
            f"⚡️ تاخیر: {latency:.0f}ms\n"
            f"📦 باکت: `{config.get('s3_bucket')}`"
        )
        await message.reply(stats_text)

    @app.on_message(filters.command("upload") & filters.private)
    async def cmd_upload(client: Client, message: Message):
        """Upload command."""
        if not await check_auth(client, message):
            return
        await message.reply(
            "📤 **آپلود فایل یا لینک**\n\n"
            "گزینه‌های زیر را انتخاب کنید:\n"
            "• یک **فایل** را بفرستید\n"
            "• یک **لینک مستقیم** برای دانلود کنید\n"
            "• یا از دکمه `📤 آپلود` استفاده کنید"
        )

    @app.on_message(filters.command("s3") & filters.private)
    async def cmd_s3(client: Client, message: Message):
        """S3 file management command."""
        if not await check_auth(client, message):
            return
        
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        try:
            files = await s3.list_files()
            if not files:
                await message.reply("📁 **فایل‌های S3**\n\nهیچ فایلی موجود نیست.")
                return
                
            text = f"📁 **فایل‌های S3** ({len(files)} فایل)\n\n"
            for i, f in enumerate(files[:10], 1):
                size_mb = f.get('size', 0) / (1024 * 1024)
                text += f"{i}. `{f['key']}` ({size_mb:.2f}MB)\n"
            
            if len(files) > 10:
                text += f"\n... و {len(files) - 10} فایل دیگر"
            
            await message.reply(text)
        except Exception as e:
            await message.reply(f"❌ خطا در دریافت لیست: {str(e)}")

    # ==================== TEXT BUTTON HANDLERS ====================
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^📤 آپلود$"))
    async def btn_upload(client: Client, message: Message):
        """Upload button handler."""
        if not await check_auth(client, message):
            return
        await cmd_upload(client, message)

    @app.on_message(filters.text & filters.private & filters.regex(r"^📁 فایل‌های S3$"))
    async def btn_s3_files(client: Client, message: Message):
        """S3 files button handler."""
        if not await check_auth(client, message):
            return
        await cmd_s3(client, message)

    @app.on_message(filters.text & filters.private & filters.regex(r"^⚙️ تنظیمات$"))
    async def btn_settings(client: Client, message: Message):
        """Settings button handler."""
        if not await check_auth(client, message):
            return
        await cmd_settings(client, message)

    @app.on_message(filters.text & filters.private & filters.regex(r"^📚 راهنما$"))
    async def btn_help(client: Client, message: Message):
        """Help button handler."""
        if not await check_auth(client, message):
            return
        await cmd_help(client, message)

    @app.on_message(filters.text & filters.private & filters.regex(r"^👥 کاربران$"))
    async def btn_users(client: Client, message: Message):
        """User management button (admin only)."""
        user_id = message.from_user.id
        config = await ConfigManager.get_config()
        owner_id = int(config.get("owner_id", 0))
        
        if user_id != owner_id:
            return
            
        users = await Database.get_users()
        await message.reply(
            "👥 **مدیریت کاربران**",
            reply_markup=get_user_manage_keyboard(users)
        )

    @app.on_message(filters.text & filters.private & filters.regex(r"^📊 وضعیت$"))
    async def btn_stats(client: Client, message: Message):
        """Stats button handler."""
        if not await check_auth(client, message):
            return
        await cmd_stats(client, message)

    # ==================== CALLBACK HANDLERS ====================
    
    @app.on_callback_query(filters.regex(r"^change_chunk_size$"))
    async def cb_chunk_size(client: Client, callback_query: CallbackQuery):
        """Chunk size selector."""
        await callback_query.message.edit_text(
            "📂 **حجم پارت‌های آپلود:**",
            reply_markup=get_chunk_size_keyboard()
        )

    @app.on_callback_query(filters.regex(r"^set_chunk_(\d+)$"))
    async def cb_set_chunk(client: Client, callback_query: CallbackQuery):
        """Set chunk size."""
        chunk_size = int(callback_query.matches[0].group(1))
        await ConfigManager.update({"chunk_size_mb": chunk_size})
        await callback_query.answer(f"✅ حجم پارت‌ها به {chunk_size}MB تغییر یافت")
        config = await ConfigManager.get_config()
        await callback_query.message.edit_text(
            "⚙️ **تنظیمات ربات**",
            reply_markup=get_settings_keyboard(config)
        )

    @app.on_callback_query(filters.regex(r"^back_to_settings$"))
    async def cb_back_settings(client: Client, callback_query: CallbackQuery):
        """Back to settings."""
        config = await ConfigManager.get_config()
        await callback_query.message.edit_text(
            "⚙️ **تنظیمات ربات**",
            reply_markup=get_settings_keyboard(config)
        )

    @app.on_callback_query(filters.regex(r"^close_menu$"))
    async def cb_close(client: Client, callback_query: CallbackQuery):
        """Close menu."""
        await callback_query.message.delete()

    # ==================== USER MANAGEMENT ====================
    
    @app.on_callback_query(filters.regex(r"^usr_add$"))
    async def cb_usr_add(client: Client, callback_query: CallbackQuery):
        """Add user."""
        user_id = callback_query.from_user.id
        user_states[user_id] = {"action": "wait_for_new_user_id"}
        await callback_query.message.reply(
            "✍️ **شناسه عددی کاربر جدید:**",
            reply_markup=ForceReply(True)
        )
        await callback_query.answer()


async def setup_commands(client: Client):
    """Set up bot commands menu."""
    try:
        await client.set_bot_commands(COMMANDS_LIST)
        logger.info("Bot commands registered successfully.")
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")
