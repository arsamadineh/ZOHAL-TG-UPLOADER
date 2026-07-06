from pyrogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from core.config import ConfigManager

# Bot Commands List for /help
COMMANDS_LIST = [
    BotCommand("start", "🪐 شروع و نمایش منوی اصلی"),
    BotCommand("help", "📚 راهنمای جامع"),
    BotCommand("settings", "⚙️ تنظیمات ربات"),
    BotCommand("s3", "📁 مدیریت فایل‌های S3"),
    BotCommand("stats", "📊 وضعیت سرور و S3"),
    BotCommand("upload", "📤 آپلود فایل یا لینک"),
]

def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Generate the persistent bottom keyboard for primary actions."""
    keyboard = [
        [
            KeyboardButton("📤 آپلود"),
            KeyboardButton("📁 فایل‌های S3")
        ],
        [
            KeyboardButton("⚙️ تنظیمات"),
            KeyboardButton("📚 راهنما")
        ]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("👥 کاربران"), KeyboardButton("📊 وضعیت")])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True, one_time_keyboard=False)

def get_help_keyboard() -> InlineKeyboardMarkup:
    """Help inline markup to link to docs/features."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 لیست ۵۰+ ویژگی ربات", callback_data="show_features")]
    ])

def get_settings_keyboard(config: dict) -> InlineKeyboardMarkup:
    """Inline keyboard for modifying bot preferences."""
    chunk_size = f"{config.get('chunk_size_mb', 10)} MB"
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 مدیریت پروکسی‌ها (شبکه)", callback_data="manage_proxies"),
        ],
        [
            InlineKeyboardButton(f"حجم پارت‌ها: {chunk_size}", callback_data="change_chunk_size"),
        ],
        [
            InlineKeyboardButton("📊 وضعیت منابع سرور (VPS)", callback_data="server_stats"),
            InlineKeyboardButton("💼 وضعیت S3", callback_data="s3_stats")
        ],
        [
            InlineKeyboardButton("❌ بستن منو", callback_data="close_menu")
        ]
    ])

def get_chunk_size_keyboard() -> InlineKeyboardMarkup:
    """Choose upload chunk size."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("5 MB", callback_data="set_chunk_5"),
            InlineKeyboardButton("10 MB", callback_data="set_chunk_10"),
            InlineKeyboardButton("20 MB", callback_data="set_chunk_20")
        ],
        [
            InlineKeyboardButton("50 MB (پیشنهادی سرور قوی)", callback_data="set_chunk_50"),
            InlineKeyboardButton("100 MB", callback_data="set_chunk_100")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_settings")
        ]
    ])

def get_s3_file_options_keyboard(key: str) -> InlineKeyboardMarkup:
    """Actions for a specific S3 file."""
    # To keep payload under 64 bytes for Pyrogram CallbackQuery limit, we can use indices or hashes.
    # We will compress the key or pass a truncated reference, or use state-based operations.
    # A safe way is to send key with actions. If key is too long, it can error.
    # So we'll pass action with file index, or keep the callback data short.
    # Let's write short callback strings. For safety, we can use helper storage in handlers,
    # or keep keys short. Here we assume file key is encoded/passed.
    # Wait, we can encode actions using prefixes: "f_dl:<key>", "f_del:<key>", "f_ren:<key>", "f_sh:<key>"
    # If the key exceeds callback limit, we can trim it or search it.
    # Let's structure callback_data safely:
    # Telegram max callback_data is 64 bytes. If key is long, we can store it in a temporary dict
    # and pass a UUID/short-hash, or just hope it fits for normal keys, or use a lookup.
    # Let's implement a clean short-hash lookup in the handlers or simply use short callback.
    # To be extremely robust, we'll write a simple callback registry in handlers.py.
    # For now, let's declare the structure:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 ارسال به تلگرام", callback_data=f"f_dl:{key[:30]}"),
            InlineKeyboardButton("🔗 ساخت لینک موقت", callback_data=f"f_sh:{key[:30]}")
        ],
        [
            InlineKeyboardButton("✏️ تغییر نام", callback_data=f"f_ren:{key[:30]}"),
            InlineKeyboardButton("❌ حذف فایل", callback_data=f"f_del:{key[:30]}")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_to_s3_files")
        ]
    ])

def get_share_expiry_keyboard(key: str) -> InlineKeyboardMarkup:
    """Select duration for secure URL signature."""
    short_key = key[:30]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("۱ ساعت", callback_data=f"exp:3600:{short_key}"),
            InlineKeyboardButton("۶ ساعت", callback_data=f"exp:21600:{short_key}"),
            InlineKeyboardButton("۲۴ ساعت (۱ روز)", callback_data=f"exp:86400:{short_key}")
        ],
        [
            InlineKeyboardButton("۷ روز", callback_data=f"exp:604800:{short_key}"),
            InlineKeyboardButton("۳۰ روز", callback_data=f"exp:2592000:{short_key}")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت", callback_data=f"file_detail:{short_key}")
        ]
    ])



def get_user_manage_keyboard(users: list) -> InlineKeyboardMarkup:
    """Manage authorized users list."""
    buttons = []
    # Add button to register new user
    buttons.append([InlineKeyboardButton("➕ افزودن کاربر جدید", callback_data="usr_add")])
    
    # List current users (show username or ID)
    for u in users[:10]: # limit to 10 for view length
        uid = u["user_id"]
        name = u["first_name"] or u["username"] or str(uid)
        is_owner = u["is_admin"] == 1
        indicator = "⭐ (مدیر)" if is_owner else "👤"
        buttons.append([
            InlineKeyboardButton(f"{indicator} {name}", callback_data=f"usr_view:{uid}")
        ])
        
    buttons.append([InlineKeyboardButton("❌ بستن", callback_data="close_menu")])
    return InlineKeyboardMarkup(buttons)
