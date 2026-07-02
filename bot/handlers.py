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
    get_share_expiry_keyboard, get_user_manage_keyboard
)

logger = logging.getLogger("ZohalHandlers")

# Global registries for state and short callback lookups
user_states: Dict[int, Dict[str, Any]] = {}
callback_registry: Dict[str, str] = {} # maps short_id -> long_s3_key
media_upload_states: Dict[str, Dict[str, Any]] = {}

def parse_proxy_string(proxy_str: str) -> Optional[dict]:
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

def get_media_upload_keyboard(short_id: str, naming_mode: str, routing: str, active_proxy_name: Optional[str]) -> InlineKeyboardMarkup:
    naming_text = "🏷 نام: پیش‌فرض" if naming_mode == "default" else "✏️ نام: سفارشی"
    routing_text = "🌐 شبکه: مستقیم" if routing == "direct" else f"🌐 شبکه: پروکسی ({active_proxy_name or 'فعال'})"
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(naming_text, callback_data=f"med_name:{short_id}"),
            InlineKeyboardButton(routing_text, callback_data=f"med_net:{short_id}")
        ],
        [
            InlineKeyboardButton("🚀 شروع انتقال به S3", callback_data=f"med_start:{short_id}")
        ],
        [
            InlineKeyboardButton("❌ لغو عملیات", callback_data=f"med_cancel:{short_id}")
        ]
    ])

def get_media_menu_text(state_data: dict, active_proxy: Optional[dict]) -> str:
    size_mb = state_data["size"] / (1024 * 1024)
    routing_text = "مستقیم" if state_data["routing"] == "direct" else f"پروکسی ({active_proxy['name'] if active_proxy else 'فعال'})"
    naming_text = "پیش‌فرض" if state_data["naming_mode"] == "default" else "سفارشی"
    
    return (
        f"🪐 **آماده‌سازی انتقال فایل به S3**\n\n"
        f"📂 **فایل اصلی:** `{state_data['original_filename']}`\n"
        f"💾 **حجم:** {size_mb:.2f} MB\n\n"
        f"⚙️ **تنظیمات انتقال:**\n"
        f"🏷 **نام فایل در S3:** `{state_data['filename']}` ({naming_text})\n"
        f"🌐 **مسیر انتقال:** {routing_text}\n\n"
        f"لطفاً در صورت نیاز تغییرات را اعمال کرده و دکمه شروع انتقال را فشار دهید."
    )

class AsyncToSyncStream(io.RawIOBase):
    """
    Bridges an async generator (e.g. S3 download stream) into a synchronous read stream.
    Used to upload directly to Telegram via Pyrogram with 0 disk and constant memory usage.
    Pyrogram calls save_file which reads this stream from a thread pool executor.

    IMPORTANT: Prefetch is lazy (started on first readinto call) so that Pyrogram's
    initial seek(0, SEEK_END)/seek(0) probing does NOT consume any stream data.
    """
    def __init__(self, async_generator, size: int, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.async_generator = async_generator
        self.size = size
        self.loop = loop or asyncio.get_event_loop()
        self.buffer = bytearray()
        self.closed_gen = False
        self.position = 0
        # Lazy: initialized on first actual read
        self._queue = None
        self._prefetch_started = False

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self.position + offset
        elif whence == io.SEEK_END:
            # SEEK_END: used by Pyrogram to probe file size. Do NOT consume stream!
            new_pos = self.size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")

        if not self._prefetch_started:
            # Prefetch not started yet, we can seek freely without consuming data
            self.position = new_pos
            return self.position

        if new_pos > self.position:
            # Discard bytes to advance forward
            diff = new_pos - self.position
            discarded = 0
            while discarded < diff:
                to_read = min(diff - discarded, 128 * 1024)
                chunk = self.read(to_read)
                if not chunk:
                    break
                discarded += len(chunk)

        self.position = new_pos
        return self.position

    def tell(self) -> int:
        return self.position

    async def _prefetch_loop(self):
        try:
            async for chunk in self.async_generator:
                if chunk:
                    await self._queue.put(chunk)
            await self._queue.put(None)  # EOF sentinel
        except Exception as e:
            logger.error(f"AsyncToSyncStream prefetch error: {e}")
            try:
                await self._queue.put(None)
            except Exception:
                pass

    def _ensure_prefetch_started(self):
        """Lazy-start the prefetch coroutine on the event loop (called from thread context)."""
        if self._prefetch_started or self.closed_gen:
            return

        async def _create_and_start():
            self._queue = asyncio.Queue(maxsize=32)  # ~4MB buffer at 128KB/chunk
            asyncio.ensure_future(self._prefetch_loop())

        # Run setup coroutine in the event loop and wait for it
        fut = asyncio.run_coroutine_threadsafe(_create_and_start(), self.loop)
        fut.result(timeout=15)
        self._prefetch_started = True

    def readinto(self, b) -> int:
        required = len(b)

        # Lazy-start prefetch on first actual read call
        self._ensure_prefetch_started()

        while len(self.buffer) < required and not self.closed_gen:
            future = asyncio.run_coroutine_threadsafe(self._queue.get(), self.loop)
            try:
                chunk = future.result(timeout=120)  # 2-min timeout per chunk
                if chunk is None:  # EOF
                    self.closed_gen = True
                else:
                    self.buffer.extend(chunk)
            except Exception as e:
                logger.error(f"AsyncToSyncStream read error: {e}")
                self.closed_gen = True
                break

        if not self.buffer:
            return 0

        take = min(len(self.buffer), required)
        chunk_to_return = bytes(self.buffer[:take])
        del self.buffer[:take]
        b[:take] = chunk_to_return
        self.position += take
        return take

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            res = bytearray()
            while True:
                chunk = self.read(128 * 1024)
                if not chunk:
                    break
                res.extend(chunk)
            return bytes(res)

        b = bytearray(size)
        n = self.readinto(b)
        return bytes(b[:n])

    def close(self):
        super().close()
        self.closed_gen = True
        # Signal the prefetch loop to stop by draining it with a done marker
        if self._prefetch_started and self._queue is not None:
            try:
                # Non-blocking drain attempt
                while not self._queue.empty():
                    self._queue.get_nowait()
            except Exception:
                pass

def register_short_key(key: str) -> str:
    """Register S3 key under a short key to keep telegram callback data size <= 64 bytes."""
    short_id = f"s_{uuid.uuid4().hex[:8]}"
    callback_registry[short_id] = key
    # Keep registry clean
    if len(callback_registry) > 5000:
        # Remove first 1000 items
        keys_to_remove = list(callback_registry.keys())[:1000]
        for k in keys_to_remove:
            callback_registry.pop(k, None)
    return short_id

def resolve_short_key(short_id: str) -> Optional[str]:
    return callback_registry.get(short_id)

from pyrogram.types import CallbackQuery, Message
from typing import Union

async def check_auth(client: Client, message_or_query: Union[Message, CallbackQuery]) -> bool:
    """Helper to verify if a user is authorized to interact with the bot."""
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
    # Start command
    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client: Client, message: Message):
        user_id = message.from_user.id
        config = await ConfigManager.get_config()
        owner_id = int(config.get("owner_id", 0))
        
        is_admin = (user_id == owner_id)
        
        # Ensure owner is registered
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
            f"🪐 **به ربات هوشمند آپلودر زحل (Zohal Uploader) خوش آمدید!**\n\n"
            f"این ربات به صورت مستقیم و بدون پر کردن هارد سرور، فایل‌ها را بین تلگرام و فضای ابری S3 منتقل می‌کند.\n\n"
            f"📂 برای شروع، یک **لینک مستقیم** یا یک **فایل تلگرامی** ارسال کنید.\n"
            f"همچنین می‌توانید از منوی زیر برای مدیریت و تنظیمات استفاده کنید."
        )
        await message.reply(
            welcome_text,
            reply_markup=get_main_keyboard(is_admin)
        )

    # Help handler
    @app.on_message(filters.text & filters.private & filters.regex(r"^ℹ️ راهنما و ویژگی‌ها$"))
    async def help_handler_text(client: Client, message: Message):
        if not await check_auth(client, message):
            return
        help_text = (
            f"📚 **راهنمای جامع ربات آپلودر زحل**\n\n"
            f"ربات زحل دارای بیش از ۵۰ ویژگی قدرتمند و بهینه‌سازی شده است:\n\n"
            f"1️⃣ **انتقال مستقیم URL به S3:** لینک دانلود را بفرستید، ربات بدون مصرف دیسک آن را در S3 ذخیره می‌کند.\n"
            f"2️⃣ **انتقال فایل تلگرام به S3:** فایل یا ویدیو تا حجم ۲ گیگابایت بفرستید تا مستقیم به فضای ابری منتقل شود.\n"
            f"3️⃣ **انتقال S3 به تلگرام:** فایل‌های ابری را دانلود و به صورت فایل تلگرامی دریافت کنید.\n"
            f"4️⃣ **دور زدن فیلترینگ تلگرام:** پشتیبانی کامل از پروکسی‌های SOCKS5/HTTP جهت کارکرد در سرورهای ایران.\n"
            f"5️⃣ **وب‌آی‌یو (WebUI) اختصاصی:** مدیریت کاربران، آمار زنده منابع سیستم، مدیریت فایل و تنظیمات پیشرفته در مرورگر.\n\n"
            f"💡 **نحوه استفاده:** کافیست لینک دانلود مستقیم یا فایل دلخواه خود را به ربات بفرستید."
        )
        await message.reply(help_text, reply_markup=get_help_keyboard())

    # WebUI Info Callback
    @app.on_callback_query(filters.regex(r"^show_features$"))
    async def show_features_cb(client: Client, callback_query: CallbackQuery):
        features_list = (
            f"📝 **برخی از ۵۰+ ویژگی پیشرفته زحل:**\n\n"
            f"🔹 آپلود مولتی‌پارت همزمان (Multipart parallel upload)\n"
            f"🔹 دانلود و آپلود استریم (بدون ذخیره حتی ۱ بایت روی دیسک)\n"
            f"🔹 پروکسی اختصاصی فقط برای اتصالات تلگرام\n"
            f"🔹 مدیریت پیشرفته سشن‌های S3 و پشتیبانی از Arvan, Cloudflare R2, MinIO\n"
            f"🔹 ساخت لینک‌های موقت با زمان انقضا\n"
            f"🔹 پنل وب و مانیتورینگ منابع سرور\n"
            f"🔹 اضافه کردن آسان کاربران مجاز توسط ادمین\n"
            f"🔹 دریافت و تحلیل متادیتای ویدیوها (توسط FFmpeg)\n"
            f"🔹 استخراج صدا از ویدیوها به صورت آنلاین\n"
            f"🔹 ساخت عکس نمونه (Thumbnail) از ویدیوها"
        )
        await callback_query.answer()
        await callback_query.message.reply(features_list)

    # Settings handler
    @app.on_message(filters.text & filters.private & filters.regex(r"^⚙️ تنظیمات ربات$"))
    async def settings_handler_text(client: Client, message: Message):
        if not await check_auth(client, message):
            return
        config = await ConfigManager.get_config()
        await message.reply(
            "⚙️ **تنظیمات ربات زحل**\n\n"
            "از گزینه‌های زیر برای پیکربندی استفاده کنید:",
            reply_markup=get_settings_keyboard(config)
        )

    # Callback Query handlers for settings
    @app.on_callback_query(filters.regex(r"^change_chunk_size$"))
    async def change_chunk_size_cb(client: Client, callback_query: CallbackQuery):
        await callback_query.message.edit_text(
            "📂 **حجم پارت‌های آپلود S3 را انتخاب کنید:**\n\n"
            "فایل‌ها به صورت تکه تکه آپلود می‌شوند. مقادیر بزرگتر سرعت را افزایش می‌دهند ولی رم بیشتری مصرف می‌کنند.",
            reply_markup=get_chunk_size_keyboard()
        )

    @app.on_callback_query(filters.regex(r"^set_chunk_(\d+)$"))
    async def set_chunk_cb(client: Client, callback_query: CallbackQuery):
        chunk_size = int(callback_query.matches[0].group(1))
        await ConfigManager.update({"chunk_size_mb": chunk_size})
        config = await ConfigManager.get_config()
        await callback_query.answer(f"حجم پارت‌ها به {chunk_size} مگابایت تغییر یافت.", show_alert=True)
        await callback_query.message.edit_text(
            "⚙️ **تنظیمات ربات زحل**\n\n"
            "تنظیمات با موفقیت ذخیره شد.",
            reply_markup=get_settings_keyboard(config)
        )

    @app.on_callback_query(filters.regex(r"^back_to_settings$"))
    async def back_to_settings_cb(client: Client, callback_query: CallbackQuery):
        config = await ConfigManager.get_config()
        await callback_query.message.edit_text(
            "⚙️ **تنظیمات ربات زحل**\n\n"
            "از گزینه‌های زیر برای پیکربندی استفاده کنید:",
            reply_markup=get_settings_keyboard(config)
        )

    @app.on_callback_query(filters.regex(r"^server_stats$"))
    async def server_stats_cb(client: Client, callback_query: CallbackQuery):
        import psutil
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        
        stats_text = (
            f"📊 **وضعیت منابع سرور (VPS):**\n\n"
            f"🖥 CPU: {cpu}%\n"
            f"💾 Virtual Memory: {ram}%\n"
            f"💽 Disk Usage: {disk}%\n"
            f"⏰ زمان سرور: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await callback_query.answer()
        await callback_query.message.reply(stats_text)

    @app.on_callback_query(filters.regex(r"^s3_stats$"))
    async def s3_stats_cb(client: Client, callback_query: CallbackQuery):
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        await callback_query.answer("در حال ارتباط با S3...")
        
        start = time.time()
        connected = await s3.test_connection()
        latency = (time.time() - start) * 1000
        
        if connected:
            s3_text = (
                f"💼 **وضعیت اتصال به S3:**\n\n"
                f"✅ وضعیت: متصل\n"
                f"🌐 ارائه‌دهنده: {config.get('s3_provider')}\n"
                f"📦 باکت: `{config.get('s3_bucket')}`\n"
                f"⚡️ تاخیر اتصال: {latency:.1f} میلی‌ثانیه"
            )
        else:
            s3_text = "❌ **خطا در برقراری ارتباط با فضای ذخیره‌سازی S3!**\n\nلطفاً تنظیمات خود را در WebUI بررسی کنید."
            
        await callback_query.message.reply(s3_text)

    @app.on_callback_query(filters.regex(r"^close_menu$"))
    async def close_menu_cb(client: Client, callback_query: CallbackQuery):
        await callback_query.message.delete()

    # User Management handler
    @app.on_message(filters.text & filters.private & filters.regex(r"^👥 مدیریت کاربران$"))
    async def user_manager_handler_text(client: Client, message: Message):
        user_id = message.from_user.id
        config = await ConfigManager.get_config()
        owner_id = int(config.get("owner_id", 0))
        
        if user_id != owner_id:
            return
            
        users = await Database.get_users()
        await message.reply(
            "👥 **مدیریت کاربران مجاز ربات**\n\n"
            "کاربرانی که در این بخش ثبت شده باشند می‌توانند از ربات استفاده کنند.",
            reply_markup=get_user_manage_keyboard(users)
        )

    # Callback User Management Actions
    @app.on_callback_query(filters.regex(r"^usr_add$"))
    async def user_add_cb(client: Client, callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        user_states[user_id] = {"action": "wait_for_new_user_id"}
        await callback_query.message.reply(
            "✍️ **لطفاً شناسه عددی تلگرام کاربر جدید را ارسال کنید:**\n"
            "یا پیام او را به اینجا فوروارد کنید تا شناسه استخراج شود.",
            reply_markup=ForceReply(True)
        )
        await callback_query.answer()

    @app.on_callback_query(filters.regex(r"^usr_view:(\d+)$"))
    async def user_view_cb(client: Client, callback_query: CallbackQuery):
        target_uid = int(callback_query.matches[0].group(1))
        # Find user details
        users = await Database.get_users()
        user_details = next((u for u in users if u["user_id"] == target_uid), None)
        
        if not user_details:
            await callback_query.answer("کاربر یافت نشد", show_alert=True)
            return
            
        name = user_details["first_name"] or user_details["username"] or "بدون نام"
        joined_time = time.strftime('%Y-%m-%d %H:%M', time.localtime(user_details["created_at"]))
        
        # Action button to remove user
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ حذف دسترسی کاربر", callback_data=f"usr_rem:{target_uid}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="usr_refresh")]
        ])
        
        await callback_query.message.edit_text(
            f"👤 **جزئیات کاربر:**\n\n"
            f"🆔 شناسه: `{target_uid}`\n"
            f"📛 نام: {name}\n"
            f"🌐 نام کاربری: @{user_details['username'] or 'ندارد'}\n"
            f"📅 تاریخ افزودن: {joined_time}",
            reply_markup=kb
        )
        await callback_query.answer()

    @app.on_callback_query(filters.regex(r"^usr_rem:(\d+)$"))
    async def user_rem_cb(client: Client, callback_query: CallbackQuery):
        target_uid = int(callback_query.matches[0].group(1))
        config = await ConfigManager.get_config()
        owner_id = int(config.get("owner_id", 0))
        
        if target_uid == owner_id:
            await callback_query.answer("شما نمی‌توانید دسترسی مدیر اصلی را حذف کنید!", show_alert=True)
            return
            
        await Database.remove_user(target_uid)
        await callback_query.answer("دسترسی کاربر با موفقیت حذف شد.", show_alert=True)
        
        # Refresh screen
        users = await Database.get_users()
        await callback_query.message.edit_text(
            "👥 **مدیریت کاربران مجاز ربات**\n\n"
            "کاربرانی که در این بخش ثبت شده باشند می‌توانند از ربات استفاده کنند.",
            reply_markup=get_user_manage_keyboard(users)
        )

    @app.on_callback_query(filters.regex(r"^usr_refresh$"))
    async def user_refresh_cb(client: Client, callback_query: CallbackQuery):
        users = await Database.get_users()
        await callback_query.message.edit_text(
            "👥 **مدیریت کاربران مجاز ربات**\n\n"
            "کاربرانی که در این بخش ثبت شده باشند می‌توانند از ربات استفاده کنند.",
            reply_markup=get_user_manage_keyboard(users)
        )
        await callback_query.answer()

    # User States Message Handler
    @app.on_message(filters.private & filters.reply)
    async def state_reply_handler(client: Client, message: Message):
        if not await check_auth(client, message):
            return
            
        user_id = message.from_user.id
        state = user_states.get(user_id)
        if not state:
            return
            
        action = state.get("action")
        
        if action == "wait_for_new_user_id":
            # Extract ID
            raw_id = ""
            if message.forward_date and message.forward_from:
                raw_id = str(message.forward_from.id)
            else:
                raw_id = message.text.strip()
                
            try:
                new_uid = int(raw_id)
                await Database.add_user(new_uid, "added_via_bot", "کاربر جدید")
                user_states.pop(user_id, None)
                await message.reply(f"✅ دسترسی کاربر `{new_uid}` فعال شد.")
            except ValueError:
                await message.reply("❌ خطا! لطفاً یک شناسه عددی معتبر ارسال کنید.")
        
        elif action == "wait_for_proxy_string":
            proxy_str = message.text.strip()
            parsed = parse_proxy_string(proxy_str)
            if parsed:
                success = await Database.add_proxy(
                    name=parsed["name"],
                    scheme=parsed["scheme"],
                    host=parsed["host"],
                    port=parsed["port"],
                    username=parsed["username"],
                    password=parsed["password"]
                )
                user_states.pop(user_id, None)
                if success:
                    await message.reply(
                        f"✅ **پروکسی جدید با موفقیت اضافه شد!**\n\n"
                        f"📛 نام: `{parsed['name']}`\n"
                        f"🌐 نوع: {parsed['scheme'].upper()}\n"
                        f"🔌 آدرس: `{parsed['host']}:{parsed['port']}`\n\n"
                        f"جهت فعال‌سازی یا تست اتصال، به منوی پروکسی‌ها بروید."
                    )
                else:
                    await message.reply("❌ خطا در ذخیره پروکسی در دیتابیس.")
            else:
                await message.reply("❌ فرمت پروکسی نامعتبر است. لطفاً راهنما را بخوانید و دوباره تلاش کنید.")
                
        elif action == "wait_for_custom_filename":
            new_name = message.text.strip()
            media_short_id = state["media_short_id"]
            menu_msg_id = state["menu_message_id"]
            
            user_states.pop(user_id, None)
            
            if media_short_id in media_upload_states:
                state_data = media_upload_states[media_short_id]
                state_data["filename"] = new_name
                state_data["naming_mode"] = "custom"
                
                active_proxy = await Database.get_active_proxy()
                active_proxy_name = active_proxy["name"] if active_proxy else None
                
                kb = get_media_upload_keyboard(
                    media_short_id,
                    state_data["naming_mode"],
                    state_data["routing"],
                    active_proxy_name
                )
                
                try:
                    await client.edit_message_text(
                        chat_id=user_id,
                        message_id=menu_msg_id,
                        text=get_media_menu_text(state_data, active_proxy),
                        reply_markup=kb
                    )
                except Exception as e:
                    logger.error(f"Error editing menu: {e}")

    # Helper to render S3 Browser with folders and pagination
    async def render_s3_browser(client: Client, chat_id: int, message_id: Optional[int], prefix: str, page: int):
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        # Display temporary loading text if it's a new message
        if not message_id:
            msg = await client.send_message(chat_id, "⏳ در حال دریافت لیست فایل‌های S3...")
            message_id = msg.id
            
        result = await s3.list_dir_contents(prefix)
        folders = result.get("folders", [])
        files = result.get("files", [])
        
        # Combine directories and files (directories first)
        items = []
        for fld in folders:
            # Get relative folder name
            rel_name = fld[len(prefix):]
            items.append({
                "type": "folder",
                "name": f"📁 {rel_name}",
                "path": fld
            })
            
        for fl in files:
            # Get relative file name
            rel_name = fl["key"][len(prefix):]
            size_mb = fl["size"] / (1024 * 1024)
            items.append({
                "type": "file",
                "name": f"📄 {rel_name} ({size_mb:.2f} MB)",
                "key": fl["key"]
            })
            
        total_items = len(items)
        items_per_page = 10
        total_pages = max(1, math.ceil(total_items / items_per_page))
        
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
            
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_items = items[start_idx:end_idx]
        
        path_display = f"Root/{prefix}" if prefix else "Root"
        text = (
            f"📁 **مدیریت فایل‌های S3**\n\n"
            f"📂 **مسیر فعلی:** `{path_display}`\n"
            f"📊 تعداد آیتم‌های این پوشه: {total_items}\n"
            f"📄 صفحه {page} از {total_pages}\n\n"
            f"👇 برای مدیریت فایل یا ورود به پوشه کلیک کنید:"
        )
        
        buttons = []
        for item in page_items:
            if item["type"] == "folder":
                short_id = register_short_key(item["path"])
                buttons.append([InlineKeyboardButton(item["name"], callback_data=f"s3list:{short_id}:1")])
            else:
                short_id = register_short_key(item["key"])
                buttons.append([InlineKeyboardButton(item["name"], callback_data=f"opt:{short_id}")])
                
        # Navigation row
        nav_row = []
        current_prefix_short = "root" if not prefix else register_short_key(prefix)
        
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"s3list:{current_prefix_short}:{page-1}"))
        else:
            nav_row.append(InlineKeyboardButton("▫️", callback_data="noop"))
            
        nav_row.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="noop"))
        
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"s3list:{current_prefix_short}:{page+1}"))
        else:
            nav_row.append(InlineKeyboardButton("▫️", callback_data="noop"))
            
        buttons.append(nav_row)
        
        # Controls row (Up, Refresh, Close)
        control_row = []
        if prefix:
            parts = prefix.rstrip("/").split("/")
            if len(parts) > 1:
                parent_prefix = "/".join(parts[:-1]) + "/"
            else:
                parent_prefix = ""
            parent_short = "root" if not parent_prefix else register_short_key(parent_prefix)
            control_row.append(InlineKeyboardButton("⬆️ پوشه قبلی", callback_data=f"s3list:{parent_short}:1"))
            
        control_row.append(InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"s3list:{current_prefix_short}:{page}"))
        control_row.append(InlineKeyboardButton("❌ بستن", callback_data="close_menu"))
        buttons.append(control_row)
        
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            if "MESSAGE_NOT_MODIFIED" not in str(e):
                logger.error(f"Error updating S3 browser: {e}")

    # S3 Files List handler
    @app.on_message(filters.text & filters.private & filters.regex(r"^📁 مدیریت فایل‌های S3$"))
    async def list_s3_files_handler_text(client: Client, message: Message):
        if not await check_auth(client, message):
            return
        await render_s3_browser(client, message.chat.id, None, "", 1)

    # S3 Browser Callback query handler
    @app.on_callback_query(filters.regex(r"^s3list:(root|s_[a-f0-9]+):(\d+)$"))
    async def s3_browser_callback(client: Client, callback_query: CallbackQuery):
        if not await check_auth(client, callback_query):
            return
            
        short_id = callback_query.matches[0].group(1)
        page = int(callback_query.matches[0].group(2))
        
        prefix = resolve_short_key(short_id)
        if prefix is None:
            if short_id == "root":
                prefix = ""
            else:
                await callback_query.answer("مسیر یافت نشد یا منقضی شده است.", show_alert=True)
                return
                
        await callback_query.answer()
        await render_s3_browser(client, callback_query.message.chat.id, callback_query.message.id, prefix, page)

    # No-op callback handler to answer dummy buttons
    @app.on_callback_query(filters.regex(r"^noop$"))
    async def noop_callback(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()

    # File Options callback handler
    @app.on_callback_query(filters.regex(r"^opt:(s_[a-f0-9]+)$"))
    async def s3_file_options_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد یا منقضی شده است.", show_alert=True)
            return
            
        # Display file options
        await callback_query.message.edit_text(
            f"📄 **مدیریت فایل ابری:**\n\n"
            f"📁 مسیر: `{key}`\n\n"
            f"لطفاً عملیات مورد نظر را انتخاب کنید:",
            reply_markup=get_s3_file_options_keyboard(short_id)
        )
        await callback_query.answer()

    # Share file / pre-signed URL generator
    @app.on_callback_query(filters.regex(r"^f_sh:(s_[a-f0-9]+)$"))
    async def s3_file_share_expiry_menu_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد.", show_alert=True)
            return
            
        await callback_query.message.edit_text(
            f"🔗 **ساخت لینک موقت (Pre-signed URL)**\n\n"
            f"مدت زمان انقضای لینک را انتخاب کنید:",
            reply_markup=get_share_expiry_keyboard(short_id)
        )
        await callback_query.answer()

    @app.on_callback_query(filters.regex(r"^exp:(\d+):(s_[a-f0-9]+)$"))
    async def s3_file_generate_share_link_cb(client: Client, callback_query: CallbackQuery):
        expiry = int(callback_query.matches[0].group(1))
        short_id = callback_query.matches[0].group(2)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد.", show_alert=True)
            return
            
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        await callback_query.answer("در حال ساخت لینک...")
        link = await s3.generate_share_link(key, expires_in_seconds=expiry)
        
        if link:
            expiry_hours = expiry // 3600
            await callback_query.message.reply(
                f"✅ **لینک دانلود امن ساخته شد:**\n\n"
                f"📂 نام فایل: `{key}`\n"
                f"⏰ اعتبار: {expiry_hours} ساعت\n\n"
                f"🔗 `{link}`",
                disable_web_page_preview=True
            )
        else:
            await callback_query.message.reply("❌ خطا در ساخت لینک دانلود.")
            
        await callback_query.message.delete()

    # Delete File S3
    @app.on_callback_query(filters.regex(r"^f_del:(s_[a-f0-9]+)$"))
    async def s3_file_delete_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد.", show_alert=True)
            return
            
        # Quick confirmation
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("بله، کاملاً مطمئنم", callback_data=f"f_del_confirm:{short_id}"),
                InlineKeyboardButton("خیر، لغو", callback_data=f"opt:{short_id}")
            ]
        ])
        await callback_query.message.edit_text(
            f"🚨 **آیا مطمئن هستید که می‌خواهید فایل زیر را حذف کنید؟**\n"
            f"`{key}`\n\n"
            f"این عمل غیر قابل بازگشت است!",
            reply_markup=kb
        )
        await callback_query.answer()

    @app.on_callback_query(filters.regex(r"^f_del_confirm:(s_[a-f0-9]+)$"))
    async def s3_file_delete_confirmed_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد.", show_alert=True)
            return
            
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        await callback_query.answer("در حال حذف فایل...")
        success = await s3.delete_file(key)
        
        if success:
            await callback_query.message.edit_text(f"✅ فایل با موفقیت حذف شد:\n`{key}`")
        else:
            await callback_query.message.edit_text(f"❌ خطا در حذف فایل:\n`{key}`")

    # Rename File S3
    @app.on_callback_query(filters.regex(r"^f_ren:(s_[a-f0-9]+)$"))
    async def s3_file_rename_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد.", show_alert=True)
            return
            
        user_id = callback_query.from_user.id
        user_states[user_id] = {"action": "wait_for_new_name", "key": key}
        
        await callback_query.message.reply(
            f"✏️ **تغییر نام فایل:**\n"
            f"نام قبلی: `{key}`\n\n"
            f"لطفاً نام یا مسیر جدید فایل را ارسال کنید:",
            reply_markup=ForceReply(True)
        )
        await callback_query.message.delete()
        await callback_query.answer()

    # Wait for rename reply message handler
    @app.on_message(filters.private & filters.reply)
    async def rename_reply_handler(client: Client, message: Message):
        if not await check_auth(client, message):
            return
        user_id = message.from_user.id
        state = user_states.get(user_id)
        if not state or state.get("action") != "wait_for_new_name":
            return
            
        old_key = state["key"]
        new_key = message.text.strip()
        
        if not new_key:
            await message.reply("❌ نام جدید نمی‌تواند خالی باشد.")
            return
            
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        msg = await message.reply("⏳ در حال تغییر نام فایل...")
        success = await s3.rename_file(old_key, new_key)
        
        user_states.pop(user_id, None)
        
        if success:
            await msg.edit_text(f"✅ فایل با موفقیت تغییر نام یافت:\n`{old_key}` ➡️ `{new_key}`")
        else:
            await msg.edit_text("❌ خطا در تغییر نام فایل.")

    # Send S3 file to Telegram (MTProto streaming download)
    @app.on_callback_query(filters.regex(r"^f_dl:(s_[a-f0-9]+)$"))
    async def s3_to_tg_stream_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        key = resolve_short_key(short_id)
        
        if not key:
            await callback_query.answer("فایل یافت نشد.", show_alert=True)
            return
            
        user_id = callback_query.from_user.id
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        # Optimized: Get file metadata via head_object instead of listing all files
        file_info = await s3.get_file_info(key)
        size = file_info["size"] if file_info else 0
        
        if size == 0:
            await callback_query.answer("حجم فایل یافت نشد.", show_alert=True)
            return
            
        await callback_query.answer("در حال شروع انتقال...")
        status_msg = await callback_query.message.reply(f"⏳ شروع ارسال فایل `{key}` به تلگرام...")
        
        task_id = f"s3tg_{uuid.uuid4().hex[:6]}"
        task = await TaskManager.create_task(
            task_id=task_id,
            file_name=key,
            total_size=size,
            task_type="s3_to_tg",
            user_id=user_id
        )
        
        # Build the progress updater wrapper
        async def progress_update(bytes_completed):
            task.update(bytes_completed)
            if task.should_update_telegram():
                try:
                    await status_msg.edit_text(task.get_persian_status_message())
                except Exception:
                    pass

        try:
            # We create an async generator for the S3 file download stream
            s3_stream = s3.download_stream(key)
            
            # Use our AsyncToSyncStream bridge
            # Pyrogram expects a file-like object
            loop = asyncio.get_running_loop()
            
            # Since Pyrogram's send_document runs in executor, it reads from stream.
            # We must wrap our generator in a bridge that tracks bytes read.
            async def tracked_gen():
                total = 0
                async for chunk in s3_stream:
                    total += len(chunk)
                    await progress_update(total)
                    yield chunk
                    
            bridge = AsyncToSyncStream(tracked_gen(), size, loop=loop)
            # Give it a filename representation
            bridge.name = os.path.basename(key)
            
            # Upload stream directly to Telegram!
            await client.send_document(
                chat_id=user_id,
                document=bridge,
                file_name=os.path.basename(key),
                caption=f"🪐 فایل دانلود شده از S3:\n`{key}`"
            )
            
            await TaskManager.complete_task(task_id, key, "", time.time() - task.start_time, task.speed)
            await status_msg.edit_text(f"✅ فایل با موفقیت به تلگرام ارسال شد:\n`{key}`")
        except Exception as e:
            logger.error(f"S3 to TG transfer failed: {e}")
            await TaskManager.fail_task(task_id, str(e))
            await status_msg.edit_text(f"❌ خطا در ارسال فایل به تلگرام:\n`{str(e)}`")

    # Direct URL to S3 stream handler
    @app.on_message(filters.text & filters.private)
    async def url_handler(client: Client, message: Message):
        if not await check_auth(client, message):
            return
            
        text = message.text.strip()
        if not (text.startswith("http://") or text.startswith("https://")):
            # If not a link, reply with guidance
            await message.reply(
                "💬 برای آپلود فایل به S3، لطفا **لینک مستقیم** یا یک **فایل تلگرامی** ارسال کنید.\n"
                "برای دیدن راهنما، دکمه `ℹ️ راهنما و ویژگی‌ها` را بفشارید."
            )
            return

        config = await ConfigManager.get_config()
        proxy_config = ConfigManager.get_pyrogram_proxy() # Use bot proxy if config says so or optionally
        
        status_msg = await message.reply("⏳ در حال بررسی لینک...")
        
        try:
            # Try to get metadata first
            info = await HTTPDownloader.get_file_info(text, proxy_config=proxy_config)
            filename = info["filename"]
            size = info["size"]
            content_type = info["content_type"]
        except Exception as e:
            await status_msg.edit_text(f"❌ خطا در دریافت اطلاعات لینک:\n`{e}`")
            return
            
        user_id = message.from_user.id
        task_id = f"url_{uuid.uuid4().hex[:6]}"
        task = await TaskManager.create_task(
            task_id=task_id,
            file_name=filename,
            total_size=size,
            task_type="url_to_s3",
            user_id=user_id
        )
        
        async def progress_update(bytes_completed):
            task.update(bytes_completed)
            if task.should_update_telegram():
                try:
                    await status_msg.edit_text(task.get_persian_status_message())
                except Exception:
                    pass

        try:
            # Setup S3 Client
            s3 = S3Client(config)
            
            # Start stream from URL
            url_stream = HTTPDownloader.get_stream(text, proxy_config=proxy_config)
            
            # Map url_stream generator to yield only bytes for S3
            async def bytes_only_stream():
                async for chunk, _, _ in url_stream:
                    if task.is_cancelled:
                        raise Exception("توسط کاربر لغو شد")
                    yield chunk
                    
            # Direct Stream upload to S3!
            start_time = time.time()
            upload_result = await s3.upload_stream(
                stream=bytes_only_stream(),
                key=filename,
                content_type=content_type,
                chunk_size_mb=config.get("chunk_size_mb", 10),
                progress_callback=progress_update
            )
            
            duration = time.time() - start_time
            speed = size / duration if duration > 0 else 0
            
            await TaskManager.complete_task(task_id, upload_result["key"], upload_result["s3_url"], duration, speed)
            
            # Success reply
            await status_msg.edit_text(
                f"✅ **آپـلود با موفقیت انجام شد!**\n\n"
                f"📂 نام فایل: `{upload_result['key']}`\n"
                f"💾 حجم: {task.format_size(size)}\n"
                f"⚡️ سرعت میانگین: {task.format_size(int(speed))}/s\n"
                f"⏰ مدت زمان: {duration:.1f} ثانیه\n\n"
                f"🔗 لینک مستقیم S3:\n`{upload_result['s3_url']}`"
            )
        except Exception as e:
            logger.error(f"URL upload failed: {e}")
            await TaskManager.fail_task(task_id, str(e))
            await status_msg.edit_text(f"❌ خطا در آپلود به S3:\n`{e}`")

    # Telegram Media to S3 stream handler
    @app.on_message(filters.media & filters.private)
    async def media_handler(client: Client, message: Message):
        if not await check_auth(client, message):
            return
            
        media = message.document or message.video or message.audio or message.photo or message.animation or message.voice or message.video_note
        if not media:
            return
            
        # Get filename and size
        if hasattr(media, "file_name") and media.file_name:
            filename = media.file_name
        else:
            ext = ".jpg" if message.photo else ".mp4" if message.video else ".bin"
            filename = f"file_{int(time.time())}{ext}"
            
        size = media.file_size if hasattr(media, "file_size") else 0
        if size == 0:
            if isinstance(media, list): # For photos it returns sizes list
                media = media[-1] # take largest
                size = media.file_size
                filename = f"photo_{media.file_unique_id}.jpg"
                
        content_type = media.mime_type if hasattr(media, "mime_type") else "application/octet-stream"
        user_id = message.from_user.id
        
        # Save choices in state
        short_id = f"m_{uuid.uuid4().hex[:8]}"
        media_upload_states[short_id] = {
            "user_id": user_id,
            "message": message,
            "filename": filename,
            "original_filename": filename,
            "size": size,
            "content_type": content_type,
            "naming_mode": "default",
            "routing": "direct", # "direct" or "proxy"
        }
        
        active_proxy = await Database.get_active_proxy()
        active_proxy_name = active_proxy["name"] if active_proxy else None
        
        kb = get_media_upload_keyboard(short_id, "default", "direct", active_proxy_name)
        await message.reply(
            get_media_menu_text(media_upload_states[short_id], active_proxy),
            reply_markup=kb
        )

    # Callback handler to change name
    @app.on_callback_query(filters.regex(r"^med_name:(m_[a-f0-9]+)$"))
    async def media_change_name_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        if short_id not in media_upload_states:
            await callback_query.answer("سشن منقضی شده است.", show_alert=True)
            return
            
        user_id = callback_query.from_user.id
        user_states[user_id] = {
            "action": "wait_for_custom_filename",
            "media_short_id": short_id,
            "menu_message_id": callback_query.message.id
        }
        
        await callback_query.message.reply(
            "✏️ **نام جدید فایل را همراه با پسوند ارسال کنید:**",
            reply_markup=ForceReply(True)
        )
        await callback_query.answer()

    # Callback handler to toggle proxy/direct routing
    @app.on_callback_query(filters.regex(r"^med_net:(m_[a-f0-9]+)$"))
    async def media_toggle_routing_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        if short_id not in media_upload_states:
            await callback_query.answer("سشن منقضی شده است.", show_alert=True)
            return
            
        state_data = media_upload_states[short_id]
        active_proxy = await Database.get_active_proxy()
        
        if not active_proxy:
            await callback_query.answer("⚠️ هیچ پروکسی فعالی در دیتابیس تعریف نشده است. اتصال مستقیم استفاده خواهد شد.", show_alert=True)
            state_data["routing"] = "direct"
        else:
            state_data["routing"] = "proxy" if state_data["routing"] == "direct" else "direct"
            await callback_query.answer("مسیر شبکه تغییر یافت.")
            
        active_proxy_name = active_proxy["name"] if active_proxy else None
        kb = get_media_upload_keyboard(
            short_id,
            state_data["naming_mode"],
            state_data["routing"],
            active_proxy_name
        )
        await callback_query.message.edit_text(
            get_media_menu_text(state_data, active_proxy),
            reply_markup=kb
        )

    # Callback handler to start media upload
    @app.on_callback_query(filters.regex(r"^med_start:(m_[a-f0-9]+)$"))
    async def media_start_upload_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        if short_id not in media_upload_states:
            await callback_query.answer("سشن منقضی شده است.", show_alert=True)
            return
            
        state_data = media_upload_states.pop(short_id)
        message = state_data["message"]
        filename = state_data["filename"]
        size = state_data["size"]
        content_type = state_data["content_type"]
        routing = state_data["routing"]
        
        user_id = callback_query.from_user.id
        
        await callback_query.answer("🚀 شروع انتقال فایل...")
        status_msg = await callback_query.message.edit_text(f"⏳ شروع آپلود مستقیم `{filename}` به S3...")
        
        task_id = f"tg_{uuid.uuid4().hex[:6]}"
        task = await TaskManager.create_task(
            task_id=task_id,
            file_name=filename,
            total_size=size,
            task_type="tg_to_s3",
            user_id=user_id
        )
        
        async def progress_update(bytes_completed):
            task.update(bytes_completed)
            if task.should_update_telegram():
                try:
                    await status_msg.edit_text(task.get_persian_status_message())
                except Exception:
                    pass
                    
        try:
            tg_stream = client.stream_media(message)
            
            # Setup S3 Client (optionally with proxy)
            config = await ConfigManager.get_config()
            proxy_config = None
            if routing == "proxy":
                # Get the active proxy
                proxy_config = await ConfigManager.get_active_pyrogram_proxy()
                
            s3 = S3Client(config, proxy_config=proxy_config)
            
            async def tracked_tg_stream():
                total = 0
                async for chunk in tg_stream:
                    if task.is_cancelled:
                        raise Exception("توسط کاربر لغو شد")
                    total += len(chunk)
                    await progress_update(total)
                    yield chunk
                    
            start_time = time.time()
            upload_result = await s3.upload_stream(
                stream=tracked_tg_stream(),
                key=filename,
                content_type=content_type,
                chunk_size_mb=config.get("chunk_size_mb", 10),
                progress_callback=None
            )
            
            duration = time.time() - start_time
            speed = size / duration if duration > 0 else 0
            
            await TaskManager.complete_task(task_id, upload_result["key"], upload_result["s3_url"], duration, speed)
            
            await status_msg.edit_text(
                f"✅ **فایل با موفقیت در S3 ذخیره شد!**\n\n"
                f"📂 نام فایل: `{upload_result['key']}`\n"
                f"💾 حجم: {task.format_size(size)}\n"
                f"⚡️ سرعت میانگین: {task.format_size(int(speed))}/s\n"
                f"⏰ مدت زمان: {duration:.1f} ثانیه\n\n"
                f"🔗 لینک مستقیم S3:\n`{upload_result['s3_url']}`"
            )
        except Exception as e:
            logger.error(f"TG upload failed: {e}")
            await TaskManager.fail_task(task_id, str(e))
            await status_msg.edit_text(f"❌ خطا در آپلود فایل تلگرام به S3:\n`{e}`")

    # Callback handler to cancel media upload menu
    @app.on_callback_query(filters.regex(r"^med_cancel:(m_[a-f0-9]+)$"))
    async def media_cancel_cb(client: Client, callback_query: CallbackQuery):
        short_id = callback_query.matches[0].group(1)
        media_upload_states.pop(short_id, None)
        await callback_query.message.delete()
        await callback_query.answer("عملیات لغو شد.")

    # Proxies management callbacks
    @app.on_callback_query(filters.regex(r"^manage_proxies$"))
    async def manage_proxies_cb(client: Client, callback_query: CallbackQuery):
        await show_proxies_menu(callback_query.message)
        await callback_query.answer()

    @app.on_callback_query(filters.regex(r"^sel_prx:(\d+|direct)$"))
    async def select_proxy_cb(client: Client, callback_query: CallbackQuery):
        target = callback_query.matches[0].group(1)
        if target == "direct":
            await Database.set_active_proxy(None)
            await callback_query.answer("اتصال مستقیم فعال شد. ربات راه‌اندازی مجدد می‌شود.", show_alert=True)
        else:
            proxy_id = int(target)
            await Database.set_active_proxy(proxy_id)
            await callback_query.answer("پروکسی جدید فعال شد. ربات راه‌اندازی مجدد می‌شود.", show_alert=True)
            
        await show_proxies_menu(callback_query.message)
        asyncio.create_task(BotService.restart())

    @app.on_callback_query(filters.regex(r"^del_prx:(\d+)$"))
    async def delete_proxy_cb(client: Client, callback_query: CallbackQuery):
        proxy_id = int(callback_query.matches[0].group(1))
        proxy = await Database.get_proxy_by_id(proxy_id)
        if proxy and proxy.get("is_active") == 1:
            await Database.set_active_proxy(None)
            asyncio.create_task(BotService.restart())
            
        await Database.delete_proxy(proxy_id)
        await callback_query.answer("پروکسی با موفقیت حذف شد.", show_alert=True)
        await show_proxies_menu(callback_query.message)

    @app.on_callback_query(filters.regex(r"^test_prx:(\d+)$"))
    async def test_proxy_cb(client: Client, callback_query: CallbackQuery):
        proxy_id = int(callback_query.matches[0].group(1))
        await callback_query.answer("⏳ در حال تست اتصال پروکسی...")
        
        proxy = await Database.get_proxy_by_id(proxy_id)
        if not proxy:
            return
            
        from core.proxy import ProxyTester
        proxy_config = {
            "scheme": proxy["scheme"],
            "hostname": proxy["host"],
            "port": proxy["port"],
            "username": proxy["username"],
            "password": proxy["password"]
        }
        
        result = await ProxyTester.test_proxy(proxy_config)
        if result["status"] == "success":
            await Database.update_proxy_test_result(
                proxy_id=proxy_id,
                status="success",
                latency=result["latency_ms"],
                country=result["country"],
                country_code=result["country_code"]
            )
            await callback_query.message.reply(
                f"✅ **تست پروکسی موفقیت‌آمیز بود!**\n\n"
                f"📛 نام: `{proxy['name']}`\n"
                f"🌍 کشور: {result['country']}\n"
                f"⚡ تاخیر: {result['latency_ms']:.1f} میلی‌ثانیه\n"
                f"ℹ️ آی‌پی: `{result['ip']}`"
            )
        else:
            await Database.update_proxy_test_result(
                proxy_id=proxy_id,
                status="error",
                latency=-1,
                country="خطا",
                country_code="ERR"
            )
            await callback_query.message.reply(
                f"❌ **خطا در اتصال به پروکسی!**\n\n"
                f"📛 نام: `{proxy['name']}`\n"
                f"⚠️ خطا: `{result.get('message')}`"
            )
            
        await show_proxies_menu(callback_query.message)

    @app.on_callback_query(filters.regex(r"^test_all_prx$"))
    async def test_all_proxies_cb(client: Client, callback_query: CallbackQuery):
        await callback_query.answer("⏳ در حال تست همه پروکسی‌ها...")
        proxies = await Database.get_proxies()
        if not proxies:
            return
            
        from core.proxy import ProxyTester
        success_count = 0
        
        for p in proxies:
            proxy_config = {
                "scheme": p["scheme"],
                "hostname": p["host"],
                "port": p["port"],
                "username": p["username"],
                "password": p["password"]
            }
            res = await ProxyTester.test_proxy(proxy_config)
            if res["status"] == "success":
                success_count += 1
                await Database.update_proxy_test_result(
                    proxy_id=p["id"],
                    status="success",
                    latency=res["latency_ms"],
                    country=res["country"],
                    country_code=res["country_code"]
                )
            else:
                await Database.update_proxy_test_result(
                    proxy_id=p["id"],
                    status="error",
                    latency=-1,
                    country="خطا",
                    country_code="ERR"
                )
                
        await callback_query.message.reply(
            f"⚡ **تست همگانی به پایان رسید.**\n\n"
            f"مجموع پروکسی‌ها: {len(proxies)}\n"
            f"✅ پروکسی‌های سالم: {success_count}\n"
            f"❌ پروکسی‌های خراب: {len(proxies) - success_count}"
        )
        await show_proxies_menu(callback_query.message)

    @app.on_callback_query(filters.regex(r"^add_prx$"))
    async def add_proxy_prompt_cb(client: Client, callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        user_states[user_id] = {"action": "wait_for_proxy_string"}
        await callback_query.message.reply(
            "✍️ **لطفاً مشخصات پروکسی جدید را ارسال کنید:**\n\n"
            "فرمت‌ها:\n"
            "1️⃣ `socks5://host:port`\n"
            "2️⃣ `socks5://username:password@host:port`\n"
            "3️⃣ `http://host:port`\n\n"
            "یا به صورت ساده: `host:port` (پیش‌فرض socks5)",
            reply_markup=ForceReply(True)
        )
        await callback_query.answer()

    async def show_proxies_menu(message: Message):
        proxies = await Database.get_proxies()
        active_proxy = await Database.get_active_proxy()
        
        text = (
            "🌐 **مدیریت پروکسی‌های ربات**\n\n"
            "در این بخش می‌توانید پروکسی‌های شبکه را مدیریت کرده و وضعیت فعال بودن آن‌ها را مشخص کنید.\n\n"
            "📌 **پروکسی فعال فعلی:** "
        )
        if active_proxy:
            text += f"`{active_proxy['name']}` ({active_proxy['host']}:{active_proxy['port']})\n"
        else:
            text += "❌ اتصال مستقیم (بدون پروکسی)\n"
            
        buttons = []
        
        direct_indicator = "✅" if not active_proxy else "⚪"
        buttons.append([InlineKeyboardButton(f"{direct_indicator} اتصال مستقیم (DIRECT)", callback_data="sel_prx:direct")])
        
        for p in proxies:
            is_active = active_proxy and active_proxy["id"] == p["id"]
            indicator = "✅" if is_active else "⚪"
            country_flag = f" ({p['country']})" if p.get("country") and p.get("country") != "نامشخص" else ""
            latency_text = f" [{p['latency']:.1f}ms]" if p.get("latency", -1) >= 0 else ""
            
            buttons.append([
                InlineKeyboardButton(f"{indicator} {p['name']}{country_flag}{latency_text}", callback_data=f"sel_prx:{p['id']}"),
                InlineKeyboardButton("⚡ تست", callback_data=f"test_prx:{p['id']}"),
                InlineKeyboardButton("❌ حذف", callback_data=f"del_prx:{p['id']}")
            ])
            
        buttons.append([
            InlineKeyboardButton("➕ افزودن پروکسی", callback_data="add_prx"),
            InlineKeyboardButton("⚡ تست همگانی", callback_data="test_all_prx")
        ])
        
        buttons.append([InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="back_to_settings")])
        
        try:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass
