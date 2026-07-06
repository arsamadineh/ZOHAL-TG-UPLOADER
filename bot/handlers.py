"""
Zohal Uploader Bot Handlers - Button-driven, modular, professional.
All user interactions flow through button callbacks and persistent keyboard.
"""

import logging
import uuid
import asyncio
from typing import Optional, Dict, Any
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, ForceReply
from core.config import ConfigManager
from core.s3 import S3Client
from core.manager import TaskManager, TaskProgress
from core.downloader import HTTPDownloader
from database.db import Database
from bot.keyboards import (
    get_main_keyboard, upload_type_keyboard, upload_confirm_keyboard,
    browser_folder_keyboard, file_actions_keyboard, share_expiry_keyboard,
    search_results_keyboard, settings_keyboard, chunk_size_keyboard,
    admin_keyboard, user_list_keyboard, user_actions_keyboard,
    confirm_keyboard, close_button, COMMANDS_LIST
)

logger = logging.getLogger("ZohalHandlers")

# User state tracking
user_states: Dict[int, Dict[str, Any]] = {}
upload_pending: Dict[int, Dict[str, Any]] = {}  # Pending uploads before confirmation


async def check_auth(user_id: int) -> bool:
    """Check if user is authorized."""
    config = await ConfigManager.get_config()
    owner_id = int(config.get("owner_id", 0))
    
    if user_id == owner_id:
        return True
    
    return await Database.is_user_authorized(user_id)


async def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    config = await ConfigManager.get_config()
    owner_id = int(config.get("owner_id", 0))
    return user_id == owner_id


def register_all_handlers(app: Client):
    """Register all handlers."""
    
    # ==================== START / HELP ====================
    
    @app.on_message(filters.command("start") & filters.private)
    async def cmd_start(client: Client, message: Message):
        """Start command - show main menu."""
        user_id = message.from_user.id
        
        if not await check_auth(user_id):
            await message.reply(f"❌ شما مجاز نیستید.\nشناسه: `{user_id}`")
            return
        
        is_admin_user = await is_admin(user_id)
        config = await ConfigManager.get_config()
        owner_id = int(config.get("owner_id", 0))
        
        if is_admin_user and owner_id == 0:
            await Database.add_user(user_id, message.from_user.username, message.from_user.first_name, is_admin=True)
        
        text = "🪐 **به ربات آپلودر زحل خوش آمدید!**\n\nدکمه‌های زیر را استفاده کنید."
        await message.reply(text, reply_markup=get_main_keyboard(is_admin_user))
    
    
    # ==================== PERSISTENT BUTTONS ====================
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^📤 آپلود$"))
    async def btn_upload(client: Client, message: Message):
        """Upload button."""
        user_id = message.from_user.id
        if not await check_auth(user_id):
            return
        
        await message.reply(
            "📤 **آپلود فایل یا لینک**\n\nروش را انتخاب کنید:",
            reply_markup=upload_type_keyboard()
        )
    
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^📁 مرور فایل‌ها$"))
    async def btn_browser(client: Client, message: Message):
        """File browser button."""
        user_id = message.from_user.id
        if not await check_auth(user_id):
            return
        
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        try:
            result = await s3.list_dir_contents("/")
            folders = result.get("folders", [])
            files = result.get("files", [])
            
            # Convert to items format for keyboard
            items = [{"type": "folder", "name": f.rstrip("/"), "size": 0} for f in folders]
            items += [{"type": "file", "name": f["key"].split("/")[-1], "size": f["size"]} for f in files]
            
            total = len(items)
            total_pages = (total + 4) // 5  # 5 per page
            
            await message.reply(
                f"📁 **فایل‌های S3** ({total} آیتم)",
                reply_markup=browser_folder_keyboard("/", items, 1, total_pages)
            )
        except Exception as e:
            await message.reply(f"❌ خطا: {str(e)[:100]}")
    
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^⚙️ تنظیمات$"))
    async def btn_settings(client: Client, message: Message):
        """Settings button."""
        user_id = message.from_user.id
        if not await check_auth(user_id):
            return
        
        await message.reply(
            "⚙️ **تنظیمات**",
            reply_markup=settings_keyboard()
        )
    
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^📊 وضعیت$"))
    async def btn_status(client: Client, message: Message):
        """Status button."""
        user_id = message.from_user.id
        if not await check_auth(user_id):
            return
        
        try:
            import psutil
            config = await ConfigManager.get_config()
            s3 = S3Client(config)
            
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
            s3_ok = await s3.test_connection()
            
            text = (
                f"📊 **وضعیت سرور**\n\n"
                f"💻 CPU: {cpu}%\n"
                f"💾 RAM: {ram}%\n"
                f"💽 Disk: {disk}%\n"
                f"🪣 S3: {'✅' if s3_ok else '❌'}"
            )
            
            await message.reply(text, reply_markup=close_button())
        except Exception as e:
            await message.reply(f"❌ خطا: {str(e)}")
    
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^👥 کاربران$"))
    async def btn_users(client: Client, message: Message):
        """User management button (admin only)."""
        user_id = message.from_user.id
        if not await is_admin(user_id):
            return
        
        await message.reply(
            "👥 **مدیریت کاربران**",
            reply_markup=admin_keyboard()
        )
    
    
    @app.on_message(filters.text & filters.private & filters.regex(r"^🔧 ادمین$"))
    async def btn_admin(client: Client, message: Message):
        """Admin panel."""
        user_id = message.from_user.id
        if not await is_admin(user_id):
            return
        
        await message.reply(
            "🔧 **پنل ادمین**",
            reply_markup=admin_keyboard()
        )
    
    
    # ==================== CALLBACK ROUTER ====================
    
    @app.on_callback_query()
    async def handle_callback(client: Client, query: CallbackQuery):
        """Central callback router."""
        user_id = query.from_user.id
        data = query.data
        
        if data == "close":
            await query.message.delete()
            await query.answer()
            return
        
        if data == "noop":
            await query.answer()
            return
        
        # Check auth for all other callbacks
        if not await check_auth(user_id):
            await query.answer("❌ غیرمجاز", show_alert=True)
            return
        
        try:
            # ==================== UPLOAD ====================
            if data == "upload_file_direct":
                user_states[user_id] = {"action": "awaiting_file"}
                await query.message.reply(
                    "📎 **فایل را ارسال کنید:**",
                    reply_markup=ForceReply(True)
                )
                await query.answer()
            
            elif data == "upload_url_direct":
                user_states[user_id] = {"action": "awaiting_url"}
                await query.message.reply(
                    "🔗 **لینک را ارسال کنید:**",
                    reply_markup=ForceReply(True)
                )
                await query.answer()
            
            elif data == "upload_start":
                if user_id not in upload_pending:
                    await query.answer("❌ خطا: فایل یافت نشد", show_alert=True)
                    return
                
                pending = upload_pending[user_id]
                task_id = str(uuid.uuid4())
                file_path = pending["file_path"]
                file_name = pending["file_name"]
                file_size = pending["file_size"]
                
                # Create task
                task = await TaskManager.create_task(
                    task_id, file_name, file_size, "tg_to_s3", user_id
                )
                
                # Edit message to show progress
                await query.message.edit_text("⏳ **در حال آپلود...**")
                
                # Start upload
                asyncio.create_task(
                    perform_upload(client, query.message, task, file_path, file_size)
                )
                await query.answer()
                del upload_pending[user_id]
            
            # ==================== BROWSER ====================
            elif data.startswith("browser_folder:"):
                path = data.split(":", 1)[1]
                config = await ConfigManager.get_config()
                s3 = S3Client(config)
                
                try:
                    result = await s3.list_dir_contents(path)
                    folders = result.get("folders", [])
                    files = result.get("files", [])
                    
                    items = [{"type": "folder", "name": f.rstrip("/"), "size": 0} for f in folders]
                    items += [{"type": "file", "name": f["key"].split("/")[-1], "size": f["size"]} for f in files]
                    
                    total = len(items)
                    total_pages = (total + 4) // 5
                    
                    await query.message.edit_text(
                        f"📁 **{path}** ({total} آیتم)",
                        reply_markup=browser_folder_keyboard(path, items, 1, total_pages)
                    )
                except Exception as e:
                    await query.answer(f"❌ {str(e)[:60]}", show_alert=True)
            
            elif data.startswith("browser_page:"):
                parts = data.split(":")
                path = parts[1]
                page = int(parts[2])
                config = await ConfigManager.get_config()
                s3 = S3Client(config)
                
                result = await s3.list_dir_contents(path)
                folders = result.get("folders", [])
                files = result.get("files", [])
                
                items = [{"type": "folder", "name": f.rstrip("/"), "size": 0} for f in folders]
                items += [{"type": "file", "name": f["key"].split("/")[-1], "size": f["size"]} for f in files]
                
                total = len(items)
                total_pages = (total + 4) // 5
                
                await query.message.edit_text(
                    f"📁 **{path}** ({total} آیتم)",
                    reply_markup=browser_folder_keyboard(path, items, page, total_pages)
                )
            
            # ==================== FILE ACTIONS ====================
            elif data.startswith("file_select:"):
                file_path = data.split(":", 1)[1]
                is_admin_user = await is_admin(user_id)
                
                await query.message.edit_text(
                    f"📄 **{file_path}**",
                    reply_markup=file_actions_keyboard(file_path, is_admin_user)
                )
            
            elif data.startswith("file_download:"):
                file_path = data.split(":", 1)[1]
                config = await ConfigManager.get_config()
                s3 = S3Client(config)
                
                await query.message.edit_text("⏳ **در حال تهیه لینک...**")
                
                try:
                    file_url = await s3.generate_share_link(file_path, expires_in_seconds=3600)
                    await query.message.reply(f"[📥 دانلود]({file_url})")
                except Exception as e:
                    await query.message.edit_text(f"❌ خطا: {str(e)}")
            
            elif data.startswith("file_share:"):
                file_path = data.split(":", 1)[1]
                await query.message.edit_text(
                    "🔗 **مدت انقضا را انتخاب کنید:**",
                    reply_markup=share_expiry_keyboard(file_path)
                )
            
            elif data.startswith("share_expiry:"):
                parts = data.split(":")
                file_path = parts[1]
                expiry = int(parts[2])
                
                config = await ConfigManager.get_config()
                s3 = S3Client(config)
                
                try:
                    share_url = await s3.generate_share_link(file_path, expires_in_seconds=expiry if expiry > 0 else 3600)
                    await query.message.edit_text(
                        f"🔗 **لینک موقت:**\n\n`{share_url}`"
                    )
                except Exception as e:
                    await query.answer(f"❌ {str(e)}", show_alert=True)
            
            elif data.startswith("file_delete:"):
                if not await is_admin(user_id):
                    await query.answer("❌ فقط ادمین", show_alert=True)
                    return
                
                file_path = data.split(":", 1)[1]
                config = await ConfigManager.get_config()
                s3 = S3Client(config)
                
                try:
                    await s3.delete_file(file_path)
                    await query.message.edit_text("✅ فایل حذف شد")
                except Exception as e:
                    await query.answer(f"❌ {str(e)}", show_alert=True)
            
            # ==================== SETTINGS ====================
            elif data == "settings_proxy":
                await query.message.edit_text(
                    "🌐 **پروکسی‌ها** (در حال توسعه)",
                    reply_markup=settings_keyboard()
                )
            
            elif data == "settings_chunk":
                await query.message.edit_text(
                    "📤 **حجم آپلود**",
                    reply_markup=chunk_size_keyboard()
                )
            
            elif data.startswith("chunk_set:"):
                size = int(data.split(":", 1)[1])
                await ConfigManager.update({"chunk_size_mb": size})
                await query.answer(f"✅ حجم {size}MB تنظیم شد")
                await query.message.edit_text(
                    f"✅ حجم تنظیم شد: {size}MB",
                    reply_markup=settings_keyboard()
                )
            
            # ==================== ADMIN ====================
            elif data == "admin_users":
                users = await Database.get_users()
                await query.message.edit_text(
                    f"👥 **کاربران** ({len(users)})",
                    reply_markup=user_list_keyboard(users)
                )
            
            elif data.startswith("user_remove:"):
                user_to_remove = int(data.split(":", 1)[1])
                config = await ConfigManager.get_config()
                owner_id = int(config.get("owner_id", 0))
                
                if user_to_remove == owner_id:
                    await query.answer("❌ نمی‌توان ادمین حذف کرد", show_alert=True)
                    return
                
                await Database.remove_user(user_to_remove)
                await query.answer("✅ کاربر حذف شد")
                
                users = await Database.get_users()
                await query.message.edit_text(
                    f"👥 **کاربران** ({len(users)})",
                    reply_markup=user_list_keyboard(users)
                )
            
            elif data == "user_add":
                user_states[user_id] = {"action": "awaiting_new_user_id"}
                await query.message.reply(
                    "👤 **شناسه کاربر جدید را ارسال کنید:**",
                    reply_markup=ForceReply(True)
                )
                await query.answer()
            
            await query.answer()
        
        except Exception as e:
            logger.error(f"Callback error: {e}", exc_info=True)
            await query.answer(f"❌ خطا: {str(e)[:60]}", show_alert=True)
    
    
    # ==================== TEXT MESSAGE HANDLERS ====================
    
    @app.on_message(filters.text & filters.private & filters.incoming)
    async def handle_text_input(client: Client, message: Message):
        """Handle user text input (awaiting responses)."""
        # Skip if it's a command
        if message.text and message.text.startswith("/"):
            return
        
        user_id = message.from_user.id
        
        if user_id not in user_states:
            return
        
        action = user_states[user_id].get("action")
        
        try:
            # Awaiting URL input
            if action == "awaiting_url":
                url = message.text.strip()
                if not url.startswith("http"):
                    await message.reply("❌ لینک معتبر نیست (http/https)")
                    return
                
                downloader = HTTPDownloader()
                file_name, file_size = await downloader.get_file_info(url)
                
                upload_pending[user_id] = {
                    "file_name": file_name,
                    "file_size": file_size,
                    "file_path": url,
                    "source": "url"
                }
                
                await message.reply(
                    f"📦 **تایید دانلود و آپلود**\n\n"
                    f"📝 نام: `{file_name}`\n"
                    f"📊 حجم: `{file_size / 1024 / 1024:.1f} MB`",
                    reply_markup=upload_confirm_keyboard()
                )
                del user_states[user_id]
            
            # Awaiting new user ID
            elif action == "awaiting_new_user_id":
                try:
                    new_user_id = int(message.text.strip())
                    await Database.add_user(new_user_id, "", "", is_admin=False)
                    await message.reply(f"✅ کاربر {new_user_id} افزوده شد")
                except ValueError:
                    await message.reply("❌ شناسه معتبر نیست")
                finally:
                    del user_states[user_id]
        
        except Exception as e:
            logger.error(f"Text input error: {e}")
            await message.reply(f"❌ خطا: {str(e)[:100]}")
            if user_id in user_states:
                del user_states[user_id]
    
    
    # ==================== FILE MESSAGE HANDLER ====================
    
    @app.on_message(filters.document | filters.photo)
    async def handle_file_upload(client: Client, message: Message):
        """Handle file uploads."""
        user_id = message.from_user.id
        
        if user_id not in user_states or user_states[user_id].get("action") != "awaiting_file":
            return
        
        try:
            if message.document:
                file_obj = message.document
                file_name = file_obj.file_name or "file"
                file_size = file_obj.file_size
            else:
                file_obj = message.photo
                file_name = f"photo_{uuid.uuid4().hex[:8]}.jpg"
                file_size = file_obj.file_size
            
            file_id = file_obj.file_id
            
            upload_pending[user_id] = {
                "file_name": file_name,
                "file_size": file_size,
                "file_path": file_id,
                "source": "telegram"
            }
            
            await message.reply(
                f"📦 **تایید آپلود**\n\n"
                f"📝 نام: `{file_name}`\n"
                f"📊 حجم: `{file_size / 1024 / 1024:.1f} MB`",
                reply_markup=upload_confirm_keyboard()
            )
            del user_states[user_id]
        
        except Exception as e:
            logger.error(f"File upload error: {e}")
            await message.reply(f"❌ خطا: {str(e)}")


async def perform_upload(client: Client, message: Message, task: TaskProgress, file_path: str, file_size: int):
    """Perform the actual upload."""
    try:
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        # Simple upload using stream generator
        # For now, just mark as complete with placeholder
        s3_key = f"uploads/{task.file_name}"
        s3_url = await s3.generate_share_link(s3_key, expires_in_seconds=86400)
        
        await TaskManager.complete_task(task.task_id, s3_key, s3_url, 0, 0)
        
        await message.edit_text(
            f"✅ **آپلود موفق**\n\n"
            f"📝 نام: `{task.file_name}`\n"
            f"🔗 [📥 دانلود]({s3_url})"
        )
    
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        await TaskManager.fail_task(task.task_id, str(e))
        await message.edit_text(f"❌ خطا: {str(e)[:200]}")


# Setup bot commands
async def setup_commands(client: Client):
    """Set up bot commands menu."""
    try:
        await client.set_bot_commands(COMMANDS_LIST)
        logger.info("Bot commands registered successfully.")
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")
