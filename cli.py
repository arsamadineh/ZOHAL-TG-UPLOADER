#!/usr/bin/env python3
import os
import sys
import json
import shutil
import asyncio
import subprocess
from typing import Dict, Any, Optional

# Ensure we can import modules from the parent/root directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.config import ConfigManager
from database.db import Database

# ANSI Color Codes
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
BOLD = "\033[1m"
NC = "\033[0m" # No Color

def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")

def print_header():
    print(f"{CYAN}=========================================================={NC}")
    print(f"{BOLD}{MAGENTA}         🪐  Z O H A L   U P L O A D E R   C L I  🪐{NC}")
    print(f"{CYAN}=========================================================={NC}")

def run_cmd(cmd: str) -> str:
    try:
        res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        return res.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

def get_service_status() -> str:
    status = run_cmd("systemctl is-active zohal")
    if status == "active":
        return f"{GREEN}ACTIVE (Running){NC}"
    elif status == "activating":
        return f"{YELLOW}ACTIVATING{NC}"
    else:
        return f"{RED}INACTIVE (Stopped){NC}"

def show_detailed_status():
    clear_screen()
    print_header()
    print(f"{BOLD}--- SYSTEMD SERVICE STATUS ---{NC}")
    status_output = run_cmd("systemctl status zohal")
    print(status_output)
    
    input(f"\nPress Enter to return to main menu...")

def manage_service(action: str):
    clear_screen()
    print_header()
    print(f"Executing: systemctl {action} zohal ...")
    
    res = subprocess.run(f"systemctl {action} zohal", shell=True)
    if res.returncode == 0:
        print(f"\n{GREEN}Service {action}ed successfully!{NC}")
    else:
        print(f"\n{RED}Failed to {action} service. Make sure you run as root or have sudo privileges.{NC}")
    
    time_sleep(2)

def view_logs():
    clear_screen()
    print_header()
    print(f"{YELLOW}Opening live logs. Press Ctrl+C to exit log view.{NC}\n")
    try:
        subprocess.run("journalctl -u zohal -f -n 50", shell=True)
    except KeyboardInterrupt:
        pass

def time_sleep(sec: float):
    import time
    time.sleep(sec)

# Async database bridge for user management
async def list_users_db():
    config = ConfigManager.load()
    if not config.get("setup_completed"):
        print(f"{RED}Error: Setup not completed yet. Run option 7 in CLI first.{NC}")
        return
        
    await Database.init_db()
    users = await Database.get_users()
    if not users:
        print("No authorized users registered.")
        return
        
    print(f"\n{BOLD}{'User ID':<15} | {'Username':<20} | {'Display Name':<20} | {'Role':<10}{NC}")
    print("-" * 75)
    for u in users:
        role = "Owner" if u["is_admin"] == 1 else "Authorized"
        name = u["first_name"] or "N/A"
        username = f"@{u['username']}" if u['username'] else "N/A"
        print(f"{u['user_id']:<15} | {username:<20} | {name:<20} | {role:<10}")

async def add_user_db(uid: int, username: str, name: str):
    await Database.init_db()
    success = await Database.add_user(uid, username, name, is_admin=False)
    if success:
        print(f"\n{GREEN}User {uid} authorized successfully!{NC}")
    else:
        print(f"\n{RED}Failed to add user to database.{NC}")

async def remove_user_db(uid: int):
    await Database.init_db()
    
    config = ConfigManager.load()
    if uid == int(config.get("owner_id", 0)):
        print(f"\n{RED}Error: Cannot remove the main owner!{NC}")
        return
        
    success = await Database.remove_user(uid)
    if success:
        print(f"\n{GREEN}User {uid} access revoked successfully!{NC}")
    else:
        print(f"\n{RED}User not found or database error.{NC}")

def manage_users():
    while True:
        clear_screen()
        print_header()
        print(f"{BOLD}--- MANAGE AUTHORIZED USERS ---{NC}\n")
        
        try:
            asyncio.run(list_users_db())
        except Exception as e:
            print(f"{RED}Database error: {e}{NC}")
            
        print("\nOptions:")
        print("1. Authorize New User")
        print("2. Revoke User Access")
        print("3. Back to Main Menu")
        
        choice = input("\nEnter choice (1-3): ").strip()
        if choice == "1":
            try:
                uid = int(input("Enter Telegram User ID: ").strip())
                username = input("Enter Username (optional, without @): ").strip()
                name = input("Enter Display Name: ").strip()
                asyncio.run(add_user_db(uid, username, name))
            except ValueError:
                print(f"{RED}Invalid User ID!{NC}")
            time_sleep(2)
        elif choice == "2":
            try:
                uid = int(input("Enter User ID to revoke: ").strip())
                asyncio.run(remove_user_db(uid))
            except ValueError:
                print(f"{RED}Invalid User ID!{NC}")
            time_sleep(2)
        elif choice == "3":
            break

async def test_telegram_connection(bot_token: Optional[str] = None, proxy: Optional[dict] = None) -> bool:
    config = ConfigManager.load()
    if not bot_token:
        bot_token = config.get("telegram_bot_token")
    if not bot_token:
        print(f"{RED}خطا: توکن ربات تلگرام مشخص نشده است.{NC}")
        return False
        
    import httpx
    if proxy is None:
        proxy = ConfigManager.get_pyrogram_proxy()
        
    proxies = None
    if proxy:
        auth = f"{proxy['username']}:{proxy['password']}@" if proxy.get("username") else ""
        proxies = f"{proxy['scheme']}://{auth}{proxy['hostname']}:{proxy['port']}"
        
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    print(f"در حال تست اتصال به تلگرام (پروکسی: {'فعال' if proxy else 'غیرفعال'})...")
    
    try:
        async with httpx.AsyncClient(proxy=proxies, timeout=10.0, trust_env=False) as client:
            res = await client.get(url)
            if res.status_code == 200 and res.json().get("ok"):
                bot_name = res.json()["result"]["first_name"]
                print(f"{GREEN}✔ موفقیت‌آمیز! نام ربات: {bot_name}{NC}")
                return True
            print(f"{RED}❌ ناموفق! پاسخ سرور تلگرام: {res.text}{NC}")
            return False
    except Exception as e:
        print(f"{RED}❌ خطای اتصال به تلگرام: {e}{NC}")
        return False

async def test_s3_connection(s3_config: Optional[dict] = None) -> bool:
    if not s3_config:
        s3_config = ConfigManager.load()
        
    if not s3_config.get("s3_endpoint") or not s3_config.get("s3_access_key"):
        print(f"{RED}خطا: مشخصات اتصال S3 تعریف نشده است.{NC}")
        return False
        
    try:
        from core.s3 import S3Client
    except ImportError as e:
        print(f"{RED}خطا در فراخوانی ماژول S3: {e}. مطمئن شوید پیش‌نیازها به درستی نصب شده باشند.{NC}")
        return False
        
    print("در حال تست اتصال به فضای ابری S3...")
    s3 = S3Client(s3_config)
    success = await s3.test_connection()
    if success:
        print(f"{GREEN}✔ موفقیت‌آمیز! اتصال با موفقیت به باکت {s3_config.get('s3_bucket')} برقرار شد.{NC}")
        return True
    print(f"{RED}❌ ناموفق! خطای اهراز هویت یا دسترسی به S3. لطفاً پارامترها را چک کنید.{NC}")
    return False

def test_connections():
    clear_screen()
    print_header()
    print(f"{BOLD}--- TESTING API CONNECTIONS ---{NC}\n")
    
    try:
        asyncio.run(test_telegram_connection())
        print()
        asyncio.run(test_s3_connection())
    except Exception as e:
        print(f"{RED}Connection Test Error: {e}{NC}")
        
    input("\nPress Enter to return to main menu...")

def run_setup_wizard():
    clear_screen()
    print_header()
    print(f"{BOLD}{CYAN}🪐 راهنمای راه‌اندازی اولیه و پیکربندی ربات زحل 🪐{NC}\n")
    print("در هر مرحله با زدن کلید Enter، مقدار قبلی/پیش‌فرض حفظ خواهد شد.\n")
    
    config = ConfigManager.load()
    
    # 1. Telegram configuration
    print(f"{BOLD}1. تنظیمات تلگرام (ربات و اتصال){NC}")
    api_id = input(f"  Telegram API ID [{config.get('telegram_api_id', '')}]: ").strip() or config.get('telegram_api_id', '')
    api_hash = input(f"  Telegram API Hash [{config.get('telegram_api_hash', '')}]: ").strip() or config.get('telegram_api_hash', '')
    bot_token = input(f"  Telegram Bot Token [{config.get('telegram_bot_token', '')}]: ").strip() or config.get('telegram_bot_token', '')
    
    owner_str = input(f"  شناسه عددی تلگرام مدیر ربات (Owner ID) [{config.get('owner_id', '')}]: ").strip() or str(config.get('owner_id', ''))
    try:
        owner_id = int(owner_str) if owner_str else 0
    except ValueError:
        owner_id = 0
        
    # Proxy Settings
    print(f"\n{BOLD}2. تنظیمات پروکسی تلگرام (جهت سرورهای فیلترشده/ایران){NC}")
    has_proxy = input("  آیا مایل به استفاده از پروکسی هستید؟ (y/n) [n]: ").strip().lower() == 'y'
    proxy_type = "none"
    proxy_host = ""
    proxy_port = 0
    proxy_username = ""
    proxy_password = ""
    
    if has_proxy:
        proxy_type = input("    نوع پروکسی (socks5/http) [socks5]: ").strip().lower() or "socks5"
        proxy_host = input("    آدرس IP یا دامنه پروکسی: ").strip()
        try:
            proxy_port = int(input("    پورت پروکسی [1080]: ").strip() or "1080")
        except ValueError:
            proxy_port = 1080
        proxy_username = input("    نام کاربری پروکسی (اختیاری): ").strip()
        proxy_password = input("    رمز عبور پروکسی (اختیاری): ").strip()
        
    # Telegram proposed verification
    proposed_proxy = None
    if has_proxy and proxy_host:
        proposed_proxy = {
            "scheme": proxy_type,
            "hostname": proxy_host,
            "port": proxy_port,
            "username": proxy_username,
            "password": proxy_password
        }
        
    print()
    tg_check = asyncio.run(test_telegram_connection(bot_token, proposed_proxy))
    if not tg_check:
        cont = input(f"{YELLOW}  ⚠️ تست اتصال تلگرام با خطا مواجه شد. آیا همچنان مایل به ثبت هستید؟ (y/n) [n]: {NC}").strip().lower() == 'y'
        if not cont:
            print("راه‌اندازی متوقف شد.")
            time_sleep(2)
            return

    # 2. S3 Storage configuration
    print(f"\n{BOLD}3. تنظیمات فضای ذخیره‌سازی ابری S3{NC}")
    print("ارائه‌دهندگان: aws, cloudflare, minio, arvan, custom")
    s3_provider = input(f"  ارائه‌دهنده S3 [{config.get('s3_provider', 'custom')}]: ").strip().lower() or config.get('s3_provider', 'custom')
    s3_endpoint = input(f"  S3 Endpoint (لینک اتصال) [{config.get('s3_endpoint', '')}]: ").strip() or config.get('s3_endpoint', '')
    s3_access_key = input(f"  S3 Access Key [{config.get('s3_access_key', '')}]: ").strip() or config.get('s3_access_key', '')
    s3_secret_key = input(f"  S3 Secret Key [{config.get('s3_secret_key', '')}]: ").strip() or config.get('s3_secret_key', '')
    s3_bucket = input(f"  S3 Bucket Name (نام باکت) [{config.get('s3_bucket', '')}]: ").strip() or config.get('s3_bucket', '')
    s3_region = input(f"  S3 Region [{config.get('s3_region', 'us-east-1')}]: ").strip() or config.get('s3_region', 'us-east-1')
    
    proposed_s3 = {
        "s3_provider": s3_provider,
        "s3_endpoint": s3_endpoint,
        "s3_access_key": s3_access_key,
        "s3_secret_key": s3_secret_key,
        "s3_bucket": s3_bucket,
        "s3_region": s3_region
    }
    
    print()
    s3_check = asyncio.run(test_s3_connection(proposed_s3))
    if not s3_check:
        cont = input(f"{YELLOW}  ⚠️ تست اتصال به S3 با خطا مواجه شد. آیا مایل به ثبت اطلاعات هستید؟ (y/n) [n]: {NC}").strip().lower() == 'y'
        if not cont:
            print("راه‌اندازی متوقف شد.")
            time_sleep(2)
            return

    # Update config.json
    config_updates = {
        "telegram_api_id": api_id,
        "telegram_api_hash": api_hash,
        "telegram_bot_token": bot_token,
        "owner_id": owner_id,
        "proxy_type": proxy_type,
        "proxy_host": proxy_host,
        "proxy_port": proxy_port,
        "proxy_username": proxy_username,
        "proxy_password": proxy_password,
        "s3_provider": s3_provider,
        "s3_endpoint": s3_endpoint,
        "s3_access_key": s3_access_key,
        "s3_secret_key": s3_secret_key,
        "s3_bucket": s3_bucket,
        "s3_region": s3_region,
        "setup_completed": True
    }
    
    for key, val in config_updates.items():
        config[key] = val
        
    ConfigManager.save_sync(config)
    
    # Initialize DB (since setup completed)
    asyncio.run(Database.init_db())
    # Add owner ID as admin if set
    if owner_id > 0:
        async def add_owner():
            await Database.add_user(owner_id, "owner", "مدیر ربات", is_admin=True)
        asyncio.run(add_owner())
        
    print(f"\n{GREEN}✔ پیکربندی اولیه با موفقیت ثبت شد!{NC}")
    print("در حال راه‌اندازی مجدد ربات زحل...")
    subprocess.run("systemctl restart zohal", shell=True)
    print(f"{GREEN}سرویس با موفقیت استارت شد.{NC}")
    time_sleep(3)

def check_and_install_updates():
    clear_screen()
    print_header()
    print(f"{BOLD}🪐 بروزرسانی هوشمند ربات زحل (Zohal TG Uploader) 🪐{NC}\n")
    
    import urllib.request
    import zipfile
    import io
    
    repo_owner = "arsamadineh"
    repo_name = "ZOHAL-TG-UPLOADER"
    releases_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
    archive_url = f"https://github.com/{repo_owner}/{repo_name}/archive/refs/heads/main.zip"
    
    print("در حال استعلام آخرین تغییرات از گیت‌هاب...")
    req = urllib.request.Request(
        releases_url, 
        headers={"User-Agent": "Mozilla/5.0"}
    )
    
    latest_tag = None
    download_url = None
    
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode())
            latest_tag = data.get("tag_name")
            download_url = data.get("zipball_url")
            print(f"آخرین انتشار رسمی یافت شد: {latest_tag}")
    except Exception:
        # Fallback to main branch archive
        print("انتشار رسمی یافت نشد. دریافت از آخرین کدهای شاخه main...")
        download_url = archive_url
        latest_tag = "Latest Commit (main branch)"
        
    confirm = input(f"\nآیا مایل هستید ربات را به نسخه [{latest_tag}] بروزرسانی کنید؟ (y/n) [n]: ").strip().lower()
    if confirm != 'y':
        return
        
    print("\nدر حال دانلود بسته‌ی بروزرسانی...")
    try:
        req_dl = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req_dl, timeout=30) as response:
            zip_data = response.read()
            
        print("بسته دانلود شد. در حال استخراج و آماده‌سازی فایل‌ها...")
        z = zipfile.ZipFile(io.BytesIO(zip_data))
        
        # Temp dir for extraction
        temp_dir = "/tmp/zohal_patch_update"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)
        z.extractall(temp_dir)
        
        # Discover extracted directory
        extracted = os.listdir(temp_dir)
        if not extracted:
            print(f"{RED}خطا: فایل استخراج شده خالی است.{NC}")
            return
            
        src_path = os.path.join(temp_dir, extracted[0])
        dest_path = "/root/zohal-uploader"
        if not os.path.exists(dest_path):
            dest_path = os.path.dirname(os.path.abspath(__file__))
            
        print("توقف موقت سرویس زحل...")
        subprocess.run("systemctl stop zohal", shell=True)
        
        # Copy elements selectively (skip config, database, sessions)
        print("در حال بروزرسانی سورس‌کد پروژه...")
        for root, dirs, files in os.walk(src_path):
            rel = os.path.relpath(root, src_path)
            target = os.path.normpath(os.path.join(dest_path, rel))
            
            # Skip web folder since webui is removed
            if rel.startswith("web") or rel == "web":
                continue
                
            os.makedirs(target, exist_ok=True)
            
            for file in files:
                # Do not overwrite credentials/db/sessions
                if file in ["config.json", "zohal.db", "zohal.session", "zohal.session-journal"]:
                    continue
                    
                src_file = os.path.join(root, file)
                dest_file = os.path.normpath(os.path.join(target, file))
                shutil.copy2(src_file, dest_file)
                
        shutil.rmtree(temp_dir)
        
        # Update dependencies inside venv
        print("بروزرسانی ماژول‌های پایتون...")
        venv_pip = os.path.join(dest_path, "venv/bin/pip")
        reqs = os.path.join(dest_path, "requirements.txt")
        if os.path.exists(venv_pip) and os.path.exists(reqs):
            res_pip = subprocess.run(f"{venv_pip} install -r {reqs} --upgrade", shell=True)
            if res_pip.returncode != 0:
                print("خطا در دانلود با میرور پیش‌فرض. در حال تلاش با سرور رسمی PyPI...")
                subprocess.run(f"{venv_pip} install -r {reqs} --upgrade --index-url https://pypi.org/simple", shell=True)
            
        # Correct permissions
        cli_filepath = os.path.join(dest_path, "cli.py")
        subprocess.run(f"chmod +x {cli_filepath}", shell=True)
        
        print("راه‌اندازی مجدد سرویس زحل...")
        subprocess.run("systemctl daemon-reload && systemctl start zohal", shell=True)
        print(f"\n{GREEN}✔ بروزرسانی با موفقیت انجام شد! نسخه فعلی: {latest_tag}{NC}")
    except Exception as e:
        print(f"\n{RED}خطا در عملیات بروزرسانی: {e}{NC}")
        print("در حال راه‌اندازی مجدد سرویس قبلی...")
        subprocess.run("systemctl start zohal", shell=True)
        
    time_sleep(4)

def backup_config():
    clear_screen()
    print_header()
    print(f"{BOLD}--- BACKUP CONFIGURATION ---{NC}\n")
    
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zohal.db")
    
    backup_dir = input("Enter backup directory path (Default: /root/zohal_backups): ").strip()
    if not backup_dir:
        backup_dir = "/root/zohal_backups"
        
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = run_cmd("date +%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"zohal_backup_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)
    
    success = True
    if os.path.exists(config_file):
        shutil.copy(config_file, os.path.join(backup_path, "config.json"))
        print(f"Backed up: config.json")
    else:
        print("config.json does not exist yet (no setup).")
        
    if os.path.exists(db_file):
        shutil.copy(db_file, os.path.join(backup_path, "zohal.db"))
        print(f"Backed up: zohal.db")
    else:
        print("zohal.db does not exist yet.")
        
    if success:
        print(f"\n{GREEN}Backup successfully saved at: {backup_path}{NC}")
    else:
        print(f"\n{RED}Failed to create backup.{NC}")
        
    time_sleep(3)

def restore_config():
    clear_screen()
    print_header()
    print(f"{BOLD}--- RESTORE CONFIGURATION ---{NC}\n")
    
    backup_path = input("Enter absolute path to backup folder: ").strip()
    if not backup_path or not os.path.exists(backup_path):
        print(f"{RED}Invalid path or path does not exist.{NC}")
        time_sleep(2)
        return
        
    config_src = os.path.join(backup_path, "config.json")
    db_src = os.path.join(backup_path, "zohal.db")
    
    dest_dir = os.path.dirname(os.path.abspath(__file__))
    
    restored = False
    if os.path.exists(config_src):
        shutil.copy(config_src, os.path.join(dest_dir, "config.json"))
        print("Restored: config.json")
        restored = True
        
    if os.path.exists(db_src):
        shutil.copy(db_src, os.path.join(dest_dir, "zohal.db"))
        print("Restored: zohal.db")
        restored = True
        
    if restored:
        print(f"\n{GREEN}Configuration successfully restored!{NC}")
        print("Restarting Zohal service to load restored configs...")
        subprocess.run("systemctl restart zohal", shell=True)
    else:
        print(f"\n{RED}No configuration or database files found in the specified path.{NC}")
        
    time_sleep(3)

def uninstall_system():
    clear_screen()
    print_header()
    print(f"{RED}{BOLD}🚨🚨🚨 WARNING: UNINSTALLING ZOHAL UPLOADER 🚨🚨🚨{NC}")
    print("This will stop and remove the systemd service, delete all application files, config, and database!")
    confirm = input("\nType 'UNINSTALL' to confirm: ").strip()
    if confirm == "UNINSTALL":
        print("\nStopping service...")
        subprocess.run("systemctl stop zohal", shell=True)
        print("Disabling service...")
        subprocess.run("systemctl disable zohal", shell=True)
        
        service_file = "/etc/systemd/system/zohal.service"
        if os.path.exists(service_file):
            os.remove(service_file)
            subprocess.run("systemctl daemon-reload", shell=True)
            print("Removed systemd service file.")
            
        cli_symlink = "/usr/local/bin/zohal-up"
        if os.path.exists(cli_symlink):
            os.remove(cli_symlink)
            print("Removed zohal-up command.")
            
        app_dir = os.path.dirname(os.path.abspath(__file__))
        print(f"Deleting app folder {app_dir} ...")
        time_sleep(2)
        shutil.rmtree(app_dir)
        print(f"\n{GREEN}Zohal Uploader fully uninstalled.{NC}")
        sys.exit(0)
    else:
        print("\nUninstall cancelled.")
        time_sleep(2)

def main_menu():
    while True:
        clear_screen()
        print_header()
        
        print(f"{BOLD}Status:{NC} {get_service_status()}")
        print("-" * 58)
        
        print("1.  Show Detailed Status")
        print("2.  Start Zohal Service")
        print("3.  Stop Zohal Service")
        print("4.  Restart Zohal Service")
        print("5.  View Live Logs (journalctl)")
        print("6.  Manage Authorized Users")
        print("7.  Run Setup Wizard (پیکربندی ربات)")
        print("8.  Test API Connections")
        print("9.  Check & Install Updates (بروزرسانی)")
        print("10. Backup Configuration")
        print("11. Restore Configuration")
        print("12. Uninstall Zohal Uploader")
        print("13. Exit CLI")
        
        choice = input("\nEnter choice (1-13): ").strip()
        
        if choice == "1":
            show_detailed_status()
        elif choice == "2":
            manage_service("start")
        elif choice == "3":
            manage_service("stop")
        elif choice == "4":
            manage_service("restart")
        elif choice == "5":
            view_logs()
        elif choice == "6":
            manage_users()
        elif choice == "7":
            run_setup_wizard()
        elif choice == "8":
            test_connections()
        elif choice == "9":
            check_and_install_updates()
        elif choice == "10":
            backup_config()
        elif choice == "11":
            restore_config()
        elif choice == "12":
            uninstall_system()
        elif choice == "13":
            print("\nGoodbye!")
            break

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nExiting CLI...")
