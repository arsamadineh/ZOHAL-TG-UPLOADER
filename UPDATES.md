# Zohal Uploader - Major Updates

**Updated:** July 2026  
**Focus:** Modern Telegram bot commands, polished CLI experience, real-time updates

---

## 🎯 Telegram Bot Updates

### New Command Structure
- **Modern slash commands** with descriptions for Telegram's command menu:
  - `/start` - Boot menu
  - `/help` - Feature guide
  - `/upload` - File/link upload
  - `/s3` - S3 file management
  - `/settings` - Bot settings
  - `/stats` - Server & S3 status

### Enhanced Keyboards
- **Persistent reply keyboard** with compact labels
- Shorter, clearer button text (e.g., `📤 آپلود` → `📤 Upload`)
- Admin-only buttons appear only for owners
- Auto-setup of command menu on bot start

### Cleaner Handler Organization
- Separate handlers for commands (`/cmd`) and text buttons
- Modern callback patterns with better state management
- Short ID registry for long S3 keys (Telegram 64-byte callback limit)
- Unified auth checking across all handlers

### Updated Keyboards (`bot/keyboards.py`)
```python
COMMANDS_LIST = [
    BotCommand("start", "🪐 Start and main menu"),
    BotCommand("help", "📚 Full guide"),
    BotCommand("settings", "⚙️ Bot settings"),
    BotCommand("s3", "📁 Manage S3 files"),
    BotCommand("stats", "📊 Server & S3 status"),
    BotCommand("upload", "📤 Upload file or link"),
]
```

---

## 💻 CLI Experience Overhaul

### Modern UI Framework
- **Color-coded status** with ANSI styling
- Professional header/section formatting
- Clean, scannable menu items
- No Persian text (compatibility with SSH, remote terminals)

### Features

#### 🔔 Real-Time Update Checks
- Automatic version check on **every CLI launch**
- Fetches latest release from GitHub API
- Displays current vs. latest version
- **Auto-notification via Telegram** to owner if update available

#### 🚀 One-Command Update
```bash
zohal update
```
- Downloads latest from GitHub
- Safely updates source (preserves config, DB, sessions)
- Auto-restarts service
- Includes Python dependency updates

#### 📊 Dashboard Status
- Live CPU, RAM, disk usage (via `psutil`)
- Service status (active/inactive)
- S3 connection health with latency
- Timestamp of last check

#### 👥 User Management
- List all authorized users with roles
- Add users by ID
- Revoke access
- Shows join dates and user info

#### 🔧 Setup Wizard
- Interactive guided setup (clean English prompts)
- Inline connection testing (Telegram + S3)
- Secure password/token input
- Retry on failed tests or force continue
- Saves all to `config.json`

#### 📝 Service Control
- `Restart`, `Stop`, `Start` bot
- View recent logs via `journalctl`
- Configuration backup with timestamp

### Code Structure
```
cli.py
├── Colors - ANSI styling
├── UI - Header, status, menu formatting
├── System - Service control (systemctl)
├── Updater - Version checks & GitHub API
├── Tester - Connection validation
├── SetupWizard - Interactive setup
├── UpdateManager - Auto-update flow
├── UserManager - User CRUD
└── Menu - Main CLI menu
```

---

## 🔧 Technical Improvements

### Handlers (`bot/handlers.py`)
- **Modular structure:** Clear sections for commands, buttons, callbacks
- **Better error handling:** All handlers validate auth
- **State management:** Global `user_states` dict for multi-step operations
- **Short key registry:** Handles long S3 keys in callbacks
- **Async/await patterns:** Full async throughout

### Bot Init (`bot/bot.py`)
- Calls `setup_commands()` after client start to register command menu
- Proper proxy support
- Logging throughout

### Config Management
- Lazy-loaded, cached config
- Automatic migrations (new fields added safely)
- Backup before updates

---

## 📋 CLI Menu Flow

```
┌─────────────────────────────┐
│   Zohal Uploader CLI        │
│ Service: ACTIVE             │
│ Version: v1.0.0             │
└─────────────────────────────┘
  1. View Status
  2. Manage Users
  3. Bot Control
  4. Configuration
  5. Update
  6. View Logs
  0. Exit

Select: █
```

### Submenus
- **Status:** CPU, RAM, disk, S3 latency
- **Users:** List, add, remove authorized users
- **Bot Control:** Restart, stop, start service
- **Config:** View current config, reconfigure, backup
- **Update:** Check GitHub, download, install, restart
- **Logs:** Last 50 lines from journalctl

---

## 🚀 Usage Examples

### First Run
```bash
$ ./cli.py
# Auto-checks for updates
# Shows main menu
```

### Setup
```
Select: 1
> Initial Setup
  Telegram API ID: 12345678
  Telegram API Hash: [***]
  Bot Token: [***]
  Owner User ID: 987654321
  Use proxy? (y/n): n
  S3 Provider: cloudflare
  S3 Endpoint: https://...
  ...
✓ Setup completed!
```

### Manage Users
```
Select: 2
  1. List Users
  2. Add User
  3. Remove User
  
Select: 1
  ID    Username         Name                 Role
  ──────────────────────────────────────────────────
  123   @john            John Doe             User
  456   @owner           Bot Owner            OWNER
```

### Check Updates
```
Select: 5
  Current: v1.0.0
  Latest: v1.1.0
  Download and install update? (y/N): y
✓ Downloaded.
✓ Installed.
✓ Updated to v1.1.0
```

---

## 📦 What's New (Summary)

| Component | Before | After |
|-----------|--------|-------|
| Bot Commands | Buttons only | Slash commands + buttons |
| CLI Menu | Persian text | Clean English |
| Update Check | Manual | Auto on every run |
| Update Notification | None | Telegram alert to owner |
| UI/UX | Basic text | Modern colored status |
| Service Control | Manual systemctl | CLI buttons |
| User Management | CLI-only | Dashboard view + CRUD |
| Setup Flow | Step-by-step | Guided wizard with tests |

---

## 🔐 Security & Optimization

- **No secrets in logs:** Passwords use `getpass`
- **Safe S3 key handling:** Short IDs for callbacks
- **Auth validation:** Every handler checks permissions
- **Config backups:** Timestamp-based backup
- **Clean updates:** Preserves DB, config, sessions
- **Connection pooling:** `httpx.AsyncClient` with timeouts
- **Resource limits:** Callback registry auto-cleanup (5000 max)

---

## 📝 Files Modified/Created

```
bot/
  ├── handlers.py       (REWRITTEN - modern commands & patterns)
  ├── keyboards.py      (UPDATED - new command list, cleaner buttons)
  └── bot.py            (PATCHED - setup_commands call)

cli.py                  (COMPLETE REWRITE - professional CLI)

UPDATES.md              (NEW - this file)
```

---

## 🎯 Next Steps

1. **Test CLI:** Run `./cli.py` and go through setup
2. **Deploy:** Copy to production
3. **Monitor:** Watch for auto-update notifications via Telegram
4. **Feedback:** Commands feel snappier? Let me know

---

## 💡 Design Philosophy

- **User-first:** Clean, scannable UI
- **Optimized:** Async throughout, connection pooling
- **Reliable:** Tests before actions, backups before changes
- **Professional:** No fluff, all substance
- **Scalable:** State management, registry cleanup, resource limits

---

**Questions?** Check `/help` in Telegram or `Select: 1` in CLI.
