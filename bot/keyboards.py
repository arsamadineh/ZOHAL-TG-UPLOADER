"""
Professional UI Keyboards - Button-driven, no commands needed.
Each keyboard is self-contained and well-documented.
"""

from pyrogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)

# Minimal commands (only for menu access)
COMMANDS_LIST = [
    BotCommand("start", "🪐 شروع"),
]

# ============================================================================
# PERSISTENT KEYBOARDS (Always visible at bottom)
# ============================================================================

def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Main persistent keyboard - all actions here."""
    keyboard = [
        [KeyboardButton("📤 آپلود"), KeyboardButton("📁 مرور فایل‌ها")],
        [KeyboardButton("⚙️ تنظیمات"), KeyboardButton("📊 وضعیت")],
    ]
    if is_admin:
        keyboard.append([KeyboardButton("👥 کاربران"), KeyboardButton("🔧 ادمین")])
    
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, is_persistent=True, one_time_keyboard=False
    )


# ============================================================================
# UPLOAD FLOW
# ============================================================================

def upload_type_keyboard() -> InlineKeyboardMarkup:
    """Choose upload method."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📎 فایل", callback_data="upload_file_direct")],
        [InlineKeyboardButton("🔗 لینک", callback_data="upload_url_direct")],
        [InlineKeyboardButton("❌ انصراف", callback_data="close")],
    ])


def upload_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirm before upload starts."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data="upload_start")],
        [InlineKeyboardButton("❌ انصراف", callback_data="close")],
    ])


def upload_progress_keyboard(task_id: str) -> InlineKeyboardMarkup:
    """Show during upload (cancel option)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏸ لغو", callback_data=f"upload_cancel:{task_id}")],
    ])


# ============================================================================
# FILE BROWSER - HIERARCHICAL WITH PAGINATION
# ============================================================================

def browser_folder_keyboard(
    path: str,
    items: list,
    page: int = 1,
    total_pages: int = 1
) -> InlineKeyboardMarkup:
    """
    Browse folder contents with pagination.
    items: [{'type': 'folder'|'file', 'name': str, 'size': int}]
    """
    buttons = []
    
    # Parent folder button (if not root)
    if path and path != "/":
        parent_path = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
        buttons.append([
            InlineKeyboardButton("📁 ⬆️ بالا", callback_data=f"browser_folder:{parent_path}")
        ])
    
    # Items for this page (5 per page)
    items_per_page = 5
    start = (page - 1) * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    for item in page_items:
        if item["type"] == "folder":
            folder_path = f"{path.rstrip('/')}/{item['name']}" if path != "/" else f"/{item['name']}"
            btn = InlineKeyboardButton(
                f"📁 {item['name']}",
                callback_data=f"browser_folder:{folder_path}"
            )
        else:
            size_str = f" ({item.get('size', 0) / 1024 / 1024:.1f}MB)"
            file_path = f"{path.rstrip('/')}/{item['name']}" if path != "/" else f"/{item['name']}"
            btn = InlineKeyboardButton(
                f"📄 {item['name']}{size_str}",
                callback_data=f"file_select:{file_path}"
            )
        buttons.append([btn])
    
    # Pagination
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(
                "◀️ قبل",
                callback_data=f"browser_page:{path}:{page-1}"
            ))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(
                "بعد ▶️",
                callback_data=f"browser_page:{path}:{page+1}"
            ))
        buttons.append(nav)
    
    # Navigation footer
    footer = [
        InlineKeyboardButton("🔍 جستجو", callback_data="search_init"),
        InlineKeyboardButton("🏠 صفحه اول", callback_data="browser_folder:/"),
    ]
    buttons.append(footer)
    
    buttons.append([InlineKeyboardButton("❌ بستن", callback_data="close")])
    
    return InlineKeyboardMarkup(buttons)


# ============================================================================
# FILE ACTIONS
# ============================================================================

def file_actions_keyboard(file_path: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Actions for a selected file."""
    buttons = [
        [InlineKeyboardButton("📥 دانلود", callback_data=f"file_download:{file_path}")],
        [InlineKeyboardButton("🔗 لینک موقت", callback_data=f"file_share:{file_path}")],
        [InlineKeyboardButton("📋 کپی نام", callback_data=f"file_copy:{file_path}")],
    ]
    
    if is_admin:
        buttons.extend([
            [InlineKeyboardButton("✏️ تغییر نام", callback_data=f"file_rename:{file_path}")],
            [InlineKeyboardButton("❌ حذف", callback_data=f"file_delete:{file_path}")],
        ])
    
    buttons.extend([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="browser_back")],
        [InlineKeyboardButton("❌ بستن", callback_data="close")],
    ])
    
    return InlineKeyboardMarkup(buttons)


def share_expiry_keyboard(file_path: str) -> InlineKeyboardMarkup:
    """Choose link expiry time."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 ساعت", callback_data=f"share_expiry:{file_path}:3600")],
        [InlineKeyboardButton("1 روز", callback_data=f"share_expiry:{file_path}:86400")],
        [InlineKeyboardButton("7 روز", callback_data=f"share_expiry:{file_path}:604800")],
        [InlineKeyboardButton("30 روز", callback_data=f"share_expiry:{file_path}:2592000")],
        [InlineKeyboardButton("بدون انقضا", callback_data=f"share_expiry:{file_path}:0")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="browser_back")],
    ])


# ============================================================================
# SEARCH
# ============================================================================

def search_results_keyboard(
    results: list,
    query: str,
    page: int = 1,
    total_pages: int = 1
) -> InlineKeyboardMarkup:
    """Paginated search results."""
    buttons = []
    
    results_per_page = 5
    start = (page - 1) * results_per_page
    end = start + results_per_page
    page_results = results[start:end]
    
    for result in page_results:
        size_str = f" ({result.get('size', 0) / 1024 / 1024:.1f}MB)"
        btn = InlineKeyboardButton(
            f"📄 {result['name']}{size_str}",
            callback_data=f"file_select:{result['path']}"
        )
        buttons.append([btn])
    
    # Pagination
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(
                "◀️ قبل",
                callback_data=f"search_page:{query}:{page-1}"
            ))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(
                "بعد ▶️",
                callback_data=f"search_page:{query}:{page+1}"
            ))
        buttons.append(nav)
    
    buttons.extend([
        [InlineKeyboardButton("🔄 جستجوی جدید", callback_data="search_init")],
        [InlineKeyboardButton("🏠 صفحه اول", callback_data="browser_folder:/")],
        [InlineKeyboardButton("❌ بستن", callback_data="close")],
    ])
    
    return InlineKeyboardMarkup(buttons)


# ============================================================================
# SETTINGS
# ============================================================================

def settings_keyboard() -> InlineKeyboardMarkup:
    """Settings menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 پروکسی‌ها", callback_data="settings_proxy")],
        [InlineKeyboardButton("📤 حجم آپلود", callback_data="settings_chunk")],
        [InlineKeyboardButton("ℹ️ اطلاعات", callback_data="settings_info")],
        [InlineKeyboardButton("❌ بستن", callback_data="close")],
    ])


def chunk_size_keyboard() -> InlineKeyboardMarkup:
    """Select chunk size."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("5MB", callback_data="chunk_set:5"),
            InlineKeyboardButton("10MB", callback_data="chunk_set:10"),
            InlineKeyboardButton("20MB", callback_data="chunk_set:20"),
        ],
        [
            InlineKeyboardButton("50MB", callback_data="chunk_set:50"),
            InlineKeyboardButton("100MB", callback_data="chunk_set:100"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="settings")],
    ])


# ============================================================================
# ADMIN
# ============================================================================

def admin_keyboard() -> InlineKeyboardMarkup:
    """Admin panel."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],
        [InlineKeyboardButton("❌ بستن", callback_data="close")],
    ])


def user_list_keyboard(users: list, page: int = 1) -> InlineKeyboardMarkup:
    """Paginated user list."""
    buttons = []
    
    users_per_page = 5
    start = (page - 1) * users_per_page
    end = start + users_per_page
    page_users = users[start:end]
    
    for u in page_users:
        role = "👑" if u.get("is_admin") else "👤"
        name = u.get("first_name", "Unknown")[:15]
        btn = InlineKeyboardButton(
            f"{role} {name}",
            callback_data=f"user_select:{u['user_id']}"
        )
        buttons.append([btn])
    
    # Pagination
    total_pages = (len(users) + users_per_page - 1) // users_per_page
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"users_page:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"users_page:{page+1}"))
        buttons.append(nav)
    
    buttons.extend([
        [InlineKeyboardButton("➕ افزودن", callback_data="user_add")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin")],
    ])
    
    return InlineKeyboardMarkup(buttons)


def user_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Actions on a user."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ حذف", callback_data=f"user_remove:{user_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")],
    ])


# ============================================================================
# GENERIC
# ============================================================================

def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Generic confirm/cancel."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"confirm:{action}"),
            InlineKeyboardButton("❌ انصراف", callback_data="close"),
        ]
    ])


def close_button() -> InlineKeyboardMarkup:
    """Just a close button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ بستن", callback_data="close")]])
