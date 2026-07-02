#!/usr/bin/env python3
import os
import sys
import json
import shutil
import asyncio
import subprocess
from typing import Dict, Any

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
    
    print(f"\n{BOLD}--- PORT LISTENING STATS ---{NC}")
    config = ConfigManager.load()
    port = config.get("web_port", 7531)
    port_status = run_cmd(f"ss -tulpn | grep :{port}")
    if port_status:
        print(f"{GREEN}Port {port} is active and listening:{NC}\n{port_status}")
    else:
        print(f"{RED}Port {port} is not listening.{NC}")
        
    input(f"\nPress Enter to return to main menu...")

def manage_service(action: str):
    clear_screen()
    print_header()
    print(f"Executing: systemctl {action} zohal ...")
    
    # We run systemctl command (requires root or sudo, which install.sh configured)
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
        # Pass control directly to journalctl
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
        print(f"{RED}Error: Setup not completed yet. Database tables might not exist.{NC}")
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
    
    # Check if this is the owner
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

def change_port():
    clear_screen()
    print_header()
    config = ConfigManager.load()
    current_port = config.get("web_port", 3002)
    print(f"Current Web Panel Port: {current_port}")
    
    new_port_str = input("\nEnter new port number (1024-65535): ").strip()
    if not new_port_str:
        return
        
    try:
        new_port = int(new_port_str)
        if new_port < 1024 or new_port > 65535:
            print(f"{RED}Port must be between 1024 and 65535!{NC}")
            time_sleep(2)
            return
            
        # Update config
        # We can update config.json directly
        config["web_port"] = new_port
        ConfigManager.save_sync(config)
        
        print(f"\n{GREEN}Port updated to {new_port}!{NC}")
        print("Restarting Zohal service to apply changes...")
        subprocess.run("systemctl restart zohal", shell=True)
        print(f"{GREEN}Restart request sent.{NC}")
    except ValueError:
        print(f"{RED}Invalid port number!{NC}")
        
    time_sleep(2.5)

async def test_telegram_connection() -> bool:
    config = ConfigManager.load()
    bot_token = config.get("telegram_bot_token")
    if not bot_token:
        print(f"{RED}No Telegram bot token configured yet.{NC}")
        return False
        
    import httpx
    proxy = ConfigManager.get_pyrogram_proxy()
    proxies = None
    if proxy:
        auth = f"{proxy['username']}:{proxy['password']}@" if proxy.get("username") else ""
        proxies = f"{proxy['scheme']}://{auth}{proxy['hostname']}:{proxy['port']}"
        
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    print(f"Testing Telegram connection (Proxy: {'Enabled' if proxy else 'Disabled'})...")
    
    try:
        async with httpx.AsyncClient(proxy=proxies, timeout=10.0) as client:
            res = await client.get(url)
            if res.status_code == 200 and res.json().get("ok"):
                bot_name = res.json()["result"]["first_name"]
                print(f"{GREEN}SUCCESS! Telegram API reached. Bot: {bot_name}{NC}")
                return True
            print(f"{RED}FAILED! Telegram returned: {res.text}{NC}")
            return False
    except Exception as e:
        print(f"{RED}CONNECTION ERROR: {e}{NC}")
        return False

async def test_s3_connection() -> bool:
    config = ConfigManager.load()
    if not config.get("s3_endpoint") or not config.get("s3_access_key"):
        print(f"{RED}S3 storage not configured yet.{NC}")
        return False
        
    try:
        from core.s3 import S3Client
    except ImportError as e:
        print(f"{RED}Error importing S3 client: {e}. Ensure requirements are installed.{NC}")
        return False
        
    print("Testing S3 storage connection...")
    s3 = S3Client(config)
    success = await s3.test_connection()
    if success:
        print(f"{GREEN}SUCCESS! Connected to S3 bucket: {config.get('s3_bucket')}{NC}")
        return True
    print(f"{RED}FAILED! Could not connect to S3. Check endpoints and access keys.{NC}")
    return False

def test_connections():
    clear_screen()
    print_header()
    print(f"{BOLD}--- TESTING API CONNECTIONS ---{NC}\n")
    
    # We need to import S3Client from core.s3, which requires aioboto3
    # If aioboto3 is missing (e.g. venv failed), print warning
    try:
        from core.s3 import S3Client
        asyncio.run(test_telegram_connection())
        print()
        asyncio.run(test_s3_connection())
    except ImportError as e:
        print(f"{RED}Import Error: {e}. Please ensure python packages are installed via virtual env.{NC}")
        
    input("\nPress Enter to return to main menu...")

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
        # Delete app folder in 3 seconds
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
        
        config = ConfigManager.load()
        port = config.get("web_port", 7531)
        
        print(f"{BOLD}Status:{NC} {get_service_status()}     |  {BOLD}Port:{NC} {port}")
        print(f"{BOLD}WebUI URL:{NC} http://<your_server_ip>:{port}\n")
        
        print("1.  Show Detailed Status")
        print("2.  Start Zohal Service")
        print("3.  Stop Zohal Service")
        print("4.  Restart Zohal Service")
        print("5.  View Live Logs (journalctl)")
        print("6.  Manage Authorized Users")
        print("7.  Change Web Panel Port")
        print("8.  Test API Connections")
        print("9.  Backup Configuration")
        print("10. Restore Configuration")
        print("11. Uninstall Zohal Uploader")
        print("12. Exit CLI")
        
        choice = input("\nEnter choice (1-12): ").strip()
        
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
            change_port()
        elif choice == "8":
            test_connections()
        elif choice == "9":
            backup_config()
        elif choice == "10":
            restore_config()
        elif choice == "11":
            uninstall_system()
        elif choice == "12":
            print("\nGoodbye!")
            break

if __name__ == "__main__":
    # Must run inside terminal
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nExiting CLI...")
