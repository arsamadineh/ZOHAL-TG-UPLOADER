# 🪐 Zohal TG Uploader

A high-performance Telegram bot + web panel that transfers files **directly** between Telegram and S3-compatible storage — with **zero disk usage** on the server, using async stream-piping.

---

## ✨ Features

- 📡 **Zero-disk transfer** — streams files directly between Telegram and S3, never touching local disk
- ⚡ **High-speed upload** — custom pyrogram patch with 16 parallel upload workers
- 🌐 **Web Panel** — full-featured dashboard with live system stats, upload history, user management
- 🔒 **Proxy support** — per-route SOCKS5/HTTP proxy management (Telegram-only or global)
- 📦 **Multi S3 provider** — supports AWS, Cloudflare R2, MinIO, Arvan Cloud, and any S3-compatible endpoint
- 🔗 **Presigned URLs** — generate expiring download links from within Telegram
- 👥 **Multi-user** — whitelist-based access control managed by the owner
- 🖥️ **CLI tool** — `zohal-up` management command for service control, user management, port changes, backups

---

## 🚀 Quick Install (VPS, Ubuntu/Debian)

```bash
git clone https://github.com/YOUR_USERNAME/ZOHAL-TG-UPLOADER.git
cd ZOHAL-TG-UPLOADER
chmod +x scripts/install.sh
sudo bash scripts/install.sh
```

After installation, open the setup wizard in your browser:

```
http://YOUR_SERVER_IP:7531/setup
```

---

## 🛠️ Requirements

- Python 3.10+
- Ubuntu 20.04 / 22.04 / Debian 11+ (or any systemd-based distro)
- Root access (for systemd service registration)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Telegram API credentials from [my.telegram.org](https://my.telegram.org)
- An S3-compatible bucket (AWS, Cloudflare R2, MinIO, Arvan, etc.)

---

## 🔧 Management CLI

Once installed, use the `zohal-up` command from anywhere:

```bash
zohal-up
```

Available actions:
- View service status & live logs
- Start / stop / restart the bot
- Manage authorized users
- Change the web panel port
- Test Telegram & S3 connections
- Backup / restore configuration
- Uninstall

---

## 🌐 Web Panel

The web panel runs on port **7531** by default. Access via:

```
http://YOUR_SERVER_IP:7531
```

> UFW firewall rule for port 7531 is added automatically by the installer.

---

## 📁 Project Structure

```
zohal-tg-uploader/
├── main.py              # Entry point (asyncio + uvicorn)
├── cli.py               # CLI management tool
├── requirements.txt     # Python dependencies
├── bot/
│   ├── bot.py           # Pyrogram client service
│   ├── handlers.py      # All Telegram message/callback handlers
│   └── keyboards.py     # Inline keyboard builders
├── core/
│   ├── config.py        # Config manager (config.json)
│   ├── downloader.py    # Async HTTP stream downloader
│   ├── manager.py       # Task/progress tracker
│   ├── proxy.py         # Proxy testing utilities
│   ├── pyrogram_patch.py # High-performance upload patch
│   └── s3.py            # S3 client (aioboto3)
├── database/
│   └── db.py            # Async SQLite (aiosqlite)
├── web/
│   ├── server.py        # FastAPI app & all REST endpoints
│   └── templates/       # Jinja2 HTML templates
└── scripts/
    ├── install.sh        # Automated installer
    └── zohal.service     # Systemd unit file
```

---

## ⚙️ Environment

All configuration is stored in `config.json` (auto-created on first run) and managed through the Setup Wizard at `/setup`.

**Never commit `config.json`** — it contains your bot token, API credentials, and S3 secrets. It is excluded by `.gitignore`.

---

## 📄 License

MIT — use freely, contribute openly.
