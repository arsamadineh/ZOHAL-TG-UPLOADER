#!/usr/bin/env python3
"""
Zohal Uploader CLI - Modern, optimized command-line interface.
Clean English UI, real-time update checks, Telegram notifications.
"""
import os
import sys
import json
import shutil
import asyncio
import subprocess
import httpx
import time
from typing import Dict, Any, Optional
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.config import ConfigManager
from database.db import Database

# ==================== STYLING ====================

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Primary
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    
    # Backgrounds
    BG_DARK = "\033[40m"


class UI:
    """Modern CLI UI builder."""
    
    @staticmethod
    def header(title: str) -> str:
        """Format main header."""
        border = "━" * 60
        return f"{Colors.CYAN}{border}{Colors.RESET}\n{Colors.BOLD}{Colors.MAGENTA}  🪐  {title}{Colors.RESET}\n{Colors.CYAN}{border}{Colors.RESET}\n"
    
    @staticmethod
    def section(title: str) -> str:
        """Format section header."""
        return f"\n{Colors.BOLD}{Colors.BLUE}▸ {title}{Colors.RESET}"
    
    @staticmethod
    def success(msg: str) -> str:
        """Format success message."""
        return f"{Colors.GREEN}✓{Colors.RESET} {msg}"
    
    @staticmethod
    def error(msg: str) -> str:
        """Format error message."""
        return f"{Colors.RED}✗{Colors.RESET} {msg}"
    
    @staticmethod
    def warning(msg: str) -> str:
        """Format warning message."""
        return f"{Colors.YELLOW}⚠{Colors.RESET} {msg}"
    
    @staticmethod
    def info(msg: str) -> str:
        """Format info message."""
        return f"{Colors.CYAN}ℹ{Colors.RESET} {msg}"
    
    @staticmethod
    def status(key: str, value: str, color=None) -> str:
        """Format status line."""
        if color:
            return f"  {Colors.DIM}•{Colors.RESET} {key}: {color}{value}{Colors.RESET}"
        return f"  {Colors.DIM}•{Colors.RESET} {key}: {value}"
    
    @staticmethod
    def menu_item(num: int, text: str) -> str:
        """Format menu item."""
        return f"  {Colors.BOLD}{num}{Colors.RESET}. {text}"
    
    @staticmethod
    def clear():
        """Clear screen."""
        os.system("clear" if os.name != "nt" else "cls")


# ==================== SYSTEM UTILS ====================

class System:
    """System-level utilities."""
    
    @staticmethod
    def run_cmd(cmd: str) -> tuple[int, str]:
        """Run shell command, return (exit_code, output)."""
        try:
            result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
            return result.returncode, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return -1, "Command timeout"
        except Exception as e:
            return -1, str(e)
    
    @staticmethod
    def get_service_status() -> str:
        """Get systemd service status."""
        code, status = System.run_cmd("systemctl is-active zohal 2>/dev/null || echo 'inactive'")
        return status if code == 0 else "inactive"
    
    @staticmethod
    def restart_service() -> bool:
        """Restart systemd service."""
        code, _ = System.run_cmd("systemctl restart zohal 2>/dev/null")
        return code == 0
    
    @staticmethod
    def stop_service() -> bool:
        """Stop systemd service."""
        code, _ = System.run_cmd("systemctl stop zohal 2>/dev/null")
        return code == 0
    
    @staticmethod
    def start_service() -> bool:
        """Start systemd service."""
        code, _ = System.run_cmd("systemctl start zohal 2>/dev/null")
        return code == 0


# ==================== VERSION & UPDATES ====================

class Updater:
    """Handle version checks and updates."""
    
    REPO_OWNER = "arsamadineh"
    REPO_NAME = "ZOHAL-TG-UPLOADER"
    RELEASES_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    
    @staticmethod
    async def get_latest_version() -> Optional[str]:
        """Fetch latest release tag."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(Updater.RELEASES_URL, follow_redirects=True)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("tag_name")
        except Exception:
            pass
        return None
    
    @staticmethod
    def get_current_version() -> str:
        """Get current version from git tag."""
        code, output = System.run_cmd("git -C /root/zohal-uploader describe --tags 2>/dev/null || echo 'dev'")
        return output or "dev"
    
    @staticmethod
    async def notify_update_available(new_version: str, telegram_token: str, user_id: int) -> bool:
        """Send Telegram notification about update."""
        try:
            current = Updater.get_current_version()
            msg = f"🚀 Update available!\n\nCurrent: {current}\nLatest: {new_version}\n\nRun `zohal update` to upgrade."
            
            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(url, json={"chat_id": user_id, "text": msg})
                return resp.status_code == 200
        except Exception:
            return False


# ==================== DATABASE MANAGEMENT ====================

class UserManager:
    """Manage authorized users."""
    
    @staticmethod
    async def list_users() -> None:
        """List all authorized users."""
        config = ConfigManager.load()
        if not config.get("setup_completed"):
            print(UI.error("Setup not completed. Run 'zohal setup' first."))
            return
        
        await Database.init_db()
        users = await Database.get_users()
        
        if not users:
            print(UI.info("No authorized users registered."))
            return
        
        print(UI.section("Authorized Users"))
        print(f"\n  {'ID':<15} {'Username':<20} {'Name':<20} {'Role':<12}")
        print(f"  {'-' * 67}")
        
        for u in users:
            role = f"{Colors.BOLD}OWNER{Colors.RESET}" if u["is_admin"] else "User"
            name = u["first_name"][:18] if u["first_name"] else "N/A"
            username = f"@{u['username'][:18]}" if u['username'] else "N/A"
            print(f"  {u['user_id']:<15} {username:<20} {name:<20} {role:<12}")
        
        print()
    
    @staticmethod
    async def add_user(user_id: int, username: str = "", first_name: str = "") -> bool:
        """Add authorized user."""
        await Database.init_db()
        success = await Database.add_user(user_id, username, first_name, is_admin=False)
        if success:
            print(UI.success(f"User {user_id} authorized."))
        else:
            print(UI.error(f"Failed to authorize user {user_id}."))
        return success
    
    @staticmethod
    async def remove_user(user_id: int) -> bool:
        """Remove authorized user."""
        config = ConfigManager.load()
        owner_id = int(config.get("owner_id", 0))
        
        if user_id == owner_id:
            print(UI.error("Cannot remove owner account."))
            return False
        
        await Database.init_db()
        success = await Database.remove_user(user_id)
        if success:
            print(UI.success(f"User {user_id} access revoked."))
        else:
            print(UI.error(f"User {user_id} not found."))
        return success


# ==================== CONNECTION TESTING ====================

class Tester:
    """Test API connections."""
    
    @staticmethod
    async def test_telegram(token: str, proxy: Optional[dict] = None) -> bool:
        """Test Telegram API connection."""
        try:
            proxies = None
            if proxy:
                auth = f"{proxy['username']}:{proxy['password']}@" if proxy.get("username") else ""
                proxies = f"{proxy['scheme']}://{auth}{proxy['hostname']}:{proxy['port']}"
            
            url = f"https://api.telegram.org/bot{token}/getMe"
            async with httpx.AsyncClient(proxy=proxies, timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.json().get("ok"):
                    bot_name = resp.json()["result"].get("first_name", "Bot")
                    print(UI.success(f"Telegram connected. Bot: {bot_name}"))
                    return True
        except Exception as e:
            print(UI.error(f"Telegram connection failed: {str(e)[:60]}"))
        return False
    
    @staticmethod
    async def test_s3(config: dict) -> bool:
        """Test S3 connection."""
        try:
            from core.s3 import S3Client
            s3 = S3Client(config)
            
            start = time.time()
            success = await s3.test_connection()
            latency = (time.time() - start) * 1000
            
            if success:
                provider = config.get('s3_provider', 'custom').upper()
                bucket = config.get('s3_bucket')
                print(UI.success(f"S3 connected ({provider}). Bucket: {bucket}. Latency: {latency:.0f}ms"))
                return True
        except Exception as e:
            print(UI.error(f"S3 connection failed: {str(e)[:60]}"))
        return False


# ==================== SETUP WIZARD ====================

class SetupWizard:
    """Interactive setup wizard."""
    
    @staticmethod
    def prompt(question: str, default: str = "", sensitive: bool = False) -> str:
        """Prompt user for input."""
        prompt_text = f"{Colors.BOLD}{question}{Colors.RESET}"
        if default:
            prompt_text += f" [{Colors.DIM}{default}{Colors.RESET}]"
        prompt_text += ": "
        
        if sensitive:
            import getpass
            return getpass.getpass(prompt_text) or default
        return input(prompt_text) or default
    
    @staticmethod
    def confirm(question: str, default: bool = False) -> bool:
        """Prompt yes/no question."""
        default_str = "y/N" if not default else "Y/n"
        resp = SetupWizard.prompt(f"{question} ({default_str})", "").lower()
        return resp == 'y' if resp else default
    
    @staticmethod
    async def run() -> None:
        """Run complete setup wizard."""
        UI.clear()
        print(UI.header("Zohal Uploader Setup"))
        
        config = ConfigManager.load()
        
        # ==================== Telegram ====================
        print(UI.section("Telegram Configuration"))
        
        api_id = SetupWizard.prompt("Telegram API ID", config.get("telegram_api_id", ""))
        api_hash = SetupWizard.prompt("Telegram API Hash", config.get("telegram_api_hash", ""), sensitive=True)
        bot_token = SetupWizard.prompt("Bot Token", config.get("telegram_bot_token", ""), sensitive=True)
        owner_id_str = SetupWizard.prompt("Owner User ID", str(config.get("owner_id", "")))
        
        try:
            owner_id = int(owner_id_str) if owner_id_str else 0
        except ValueError:
            owner_id = 0
        
        # Test Telegram
        print()
        tg_ok = await Tester.test_telegram(bot_token)
        
        if not tg_ok and not SetupWizard.confirm("Continue anyway?"):
            print(UI.warning("Setup cancelled."))
            return
        
        # ==================== Proxy ====================
        print(UI.section("Proxy (Optional)"))
        has_proxy = SetupWizard.confirm("Use proxy?", False)
        
        proxy_type = proxy_host = proxy_port = proxy_username = proxy_password = ""
        if has_proxy:
            proxy_type = SetupWizard.prompt("Proxy type", "socks5")
            proxy_host = SetupWizard.prompt("Proxy hostname")
            proxy_port_str = SetupWizard.prompt("Proxy port", "1080")
            try:
                proxy_port = int(proxy_port_str)
            except ValueError:
                proxy_port = 1080
            proxy_username = SetupWizard.prompt("Proxy username (optional)", "")
            proxy_password = SetupWizard.prompt("Proxy password (optional)", "", sensitive=True)
        
        # ==================== S3 ====================
        print(UI.section("S3 Storage Configuration"))
        
        s3_provider = SetupWizard.prompt("Provider (aws/cloudflare/minio/arvan)", "custom")
        s3_endpoint = SetupWizard.prompt("S3 Endpoint URL", config.get("s3_endpoint", ""))
        s3_access_key = SetupWizard.prompt("Access Key", config.get("s3_access_key", ""), sensitive=True)
        s3_secret_key = SetupWizard.prompt("Secret Key", config.get("s3_secret_key", ""), sensitive=True)
        s3_bucket = SetupWizard.prompt("Bucket Name", config.get("s3_bucket", ""))
        s3_region = SetupWizard.prompt("Region", config.get("s3_region", "us-east-1"))
        
        proposed_s3 = {
            "s3_provider": s3_provider,
            "s3_endpoint": s3_endpoint,
            "s3_access_key": s3_access_key,
            "s3_secret_key": s3_secret_key,
            "s3_bucket": s3_bucket,
            "s3_region": s3_region
        }
        
        print()
        s3_ok = await Tester.test_s3(proposed_s3)
        
        if not s3_ok and not SetupWizard.confirm("Continue anyway?"):
            print(UI.warning("Setup cancelled."))
            return
        
        # ==================== Save ====================
        config.update({
            "telegram_api_id": api_id,
            "telegram_api_hash": api_hash,
            "telegram_bot_token": bot_token,
            "owner_id": owner_id,
            "proxy_type": proxy_type,
            "proxy_host": proxy_host,
            "proxy_port": proxy_port,
            "proxy_username": proxy_username,
            "proxy_password": proxy_password,
            **proposed_s3,
            "setup_completed": True
        })
        
        ConfigManager.save_sync(config)
        await Database.init_db()
        
        if owner_id > 0:
            await Database.add_user(owner_id, "owner", "Bot Owner", is_admin=True)
        
        print()
        print(UI.success("Setup completed!"))
        print(UI.info("Restarting service..."))
        
        System.restart_service()
        print(UI.success("Service restarted."))


# ==================== UPDATE MANAGER ====================

class UpdateManager:
    """Handle bot updates."""
    
    @staticmethod
    async def check_and_notify() -> None:
        """Check for updates and notify via Telegram."""
        try:
            config = ConfigManager.load()
            if not config.get("setup_completed"):
                return
            
            current = Updater.get_current_version()
            latest = await Updater.get_latest_version()
            
            if latest and latest != current:
                print(UI.info(f"Update available: {current} → {latest}"))
                
                # Notify owner
                token = config.get("telegram_bot_token")
                owner_id = int(config.get("owner_id", 0))
                if token and owner_id:
                    await Updater.notify_update_available(latest, token, owner_id)
        except Exception:
            pass
    
    @staticmethod
    async def auto_update() -> None:
        """Automatic update from GitHub."""
        print(UI.header("Update Check"))
        
        current = Updater.get_current_version()
        latest = await Updater.get_latest_version()
        
        if not latest:
            print(UI.error("Could not fetch latest version."))
            return
        
        print(UI.status("Current", current))
        print(UI.status("Latest", latest))
        
        if current == latest:
            print(UI.success("Already up to date."))
            return
        
        if not SetupWizard.confirm("\nDownload and install update?"):
            return
        
        print(UI.info("Downloading..."))
        
        try:
            url = f"https://github.com/{Updater.REPO_OWNER}/{Updater.REPO_NAME}/archive/refs/heads/main.zip"
            
            code, _ = System.run_cmd(
                f"cd /tmp && wget -q {url} -O zohal_update.zip && unzip -q -o zohal_update.zip"
            )
            
            if code != 0:
                print(UI.error("Download failed."))
                return
            
            print(UI.success("Downloaded."))
            print(UI.info("Installing..."))
            
            System.stop_service()
            
            src_path = f"/tmp/{Updater.REPO_NAME}-main"
            dest_path = "/root/zohal-uploader"
            
            for root, dirs, files in os.walk(src_path):
                rel = os.path.relpath(root, src_path)
                target = os.path.normpath(os.path.join(dest_path, rel))
                
                if rel.startswith("web"):
                    continue
                
                os.makedirs(target, exist_ok=True)
                
                for file in files:
                    if file in ["config.json", "zohal.db", "zohal.session"]:
                        continue
                    
                    src_file = os.path.join(root, file)
                    dest_file = os.path.normpath(os.path.join(target, file))
                    shutil.copy2(src_file, dest_file)
            
            print(UI.success("Installed."))
            print(UI.info("Restarting service..."))
            
            System.start_service()
            print(UI.success(f"Updated to {latest}"))
            
        except Exception as e:
            print(UI.error(f"Update failed: {str(e)}"))
            System.start_service()


# ==================== MAIN MENU ====================

class Menu:
    """Interactive CLI menu."""
    
    @staticmethod
    async def main_menu() -> None:
        """Display main menu."""
        config = ConfigManager.load()
        setup_done = config.get("setup_completed")
        
        while True:
            UI.clear()
            print(UI.header("Zohal Uploader CLI"))
            
            status = System.get_service_status()
            status_color = Colors.GREEN if status == "active" else Colors.RED
            print(UI.status("Service", status.upper(), status_color))
            print(UI.status("Version", Updater.get_current_version()))
            print()
            
            if setup_done:
                print(UI.menu_item(1, "View Status"))
                print(UI.menu_item(2, "Manage Users"))
                print(UI.menu_item(3, "Bot Control"))
                print(UI.menu_item(4, "Configuration"))
                print(UI.menu_item(5, "Update"))
                print(UI.menu_item(6, "View Logs"))
                print(UI.menu_item(0, "Exit"))
            else:
                print(UI.menu_item(1, "Initial Setup"))
                print(UI.menu_item(0, "Exit"))
            
            choice = input(f"\n{Colors.BOLD}Select:{Colors.RESET} ").strip()
            
            if choice == "0":
                break
            elif choice == "1":
                if not setup_done:
                    await SetupWizard.run()
                    config = ConfigManager.load()
                    setup_done = config.get("setup_completed")
                else:
                    await Menu.status_menu()
            elif setup_done and choice == "2":
                await Menu.users_menu()
            elif setup_done and choice == "3":
                await Menu.bot_control_menu()
            elif setup_done and choice == "4":
                await Menu.config_menu()
            elif setup_done and choice == "5":
                await UpdateManager.auto_update()
            elif setup_done and choice == "6":
                await Menu.view_logs()
            
            input(f"\n{Colors.DIM}Press Enter to continue...{Colors.RESET}")
    
    @staticmethod
    async def status_menu() -> None:
        """Status submenu."""
        UI.clear()
        print(UI.header("System Status"))
        
        import psutil
        
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        
        print(UI.section("Server Resources"))
        print(UI.status("CPU Usage", f"{cpu}%", Colors.GREEN if cpu < 75 else Colors.YELLOW))
        print(UI.status("Memory", f"{ram}%", Colors.GREEN if ram < 75 else Colors.YELLOW))
        print(UI.status("Disk", f"{disk}%", Colors.GREEN if disk < 85 else Colors.RED))
        
        print(UI.section("Service"))
        status = System.get_service_status()
        status_color = Colors.GREEN if status == "active" else Colors.RED
        print(UI.status("Status", status.upper(), status_color))
        
        config = ConfigManager.load()
        s3 = await Tester.test_s3(config) if config.get("setup_completed") else False
        
        print()
    
    @staticmethod
    async def users_menu() -> None:
        """Users management submenu."""
        UI.clear()
        print(UI.header("User Management"))
        
        while True:
            print(UI.menu_item(1, "List Users"))
            print(UI.menu_item(2, "Add User"))
            print(UI.menu_item(3, "Remove User"))
            print(UI.menu_item(0, "Back"))
            
            choice = input(f"\n{Colors.BOLD}Select:{Colors.RESET} ").strip()
            
            if choice == "0":
                break
            elif choice == "1":
                await UserManager.list_users()
            elif choice == "2":
                try:
                    user_id = int(input("User ID: "))
                    username = input("Username (optional): ")
                    first_name = input("Name (optional): ")
                    await UserManager.add_user(user_id, username, first_name)
                except ValueError:
                    print(UI.error("Invalid user ID."))
            elif choice == "3":
                try:
                    user_id = int(input("User ID to remove: "))
                    await UserManager.remove_user(user_id)
                except ValueError:
                    print(UI.error("Invalid user ID."))
            
            input(f"\n{Colors.DIM}Press Enter to continue...{Colors.RESET}")
            UI.clear()
            print(UI.header("User Management"))
    
    @staticmethod
    async def bot_control_menu() -> None:
        """Bot control submenu."""
        UI.clear()
        print(UI.header("Bot Control"))
        
        print(UI.menu_item(1, "Restart Bot"))
        print(UI.menu_item(2, "Stop Bot"))
        print(UI.menu_item(3, "Start Bot"))
        print(UI.menu_item(4, "Status"))
        print(UI.menu_item(0, "Back"))
        
        choice = input(f"\n{Colors.BOLD}Select:{Colors.RESET} ").strip()
        
        if choice == "1":
            print(UI.info("Restarting..."))
            System.restart_service()
            print(UI.success("Restarted."))
        elif choice == "2":
            print(UI.info("Stopping..."))
            System.stop_service()
            print(UI.success("Stopped."))
        elif choice == "3":
            print(UI.info("Starting..."))
            System.start_service()
            print(UI.success("Started."))
        elif choice == "4":
            status = System.get_service_status()
            color = Colors.GREEN if status == "active" else Colors.RED
            print(UI.status("Status", status.upper(), color))
    
    @staticmethod
    async def config_menu() -> None:
        """Configuration submenu."""
        UI.clear()
        print(UI.header("Configuration"))
        
        config = ConfigManager.load()
        
        print(UI.section("Current Configuration"))
        print(UI.status("Setup Completed", "Yes" if config.get("setup_completed") else "No"))
        print(UI.status("S3 Provider", config.get("s3_provider", "N/A")))
        print(UI.status("S3 Bucket", config.get("s3_bucket", "N/A")))
        print(UI.status("Proxy Enabled", "Yes" if config.get("proxy_host") else "No"))
        
        print()
        print(UI.menu_item(1, "Reconfigure Setup"))
        print(UI.menu_item(2, "Backup Configuration"))
        print(UI.menu_item(0, "Back"))
        
        choice = input(f"\n{Colors.BOLD}Select:{Colors.RESET} ").strip()
        
        if choice == "1":
            await SetupWizard.run()
        elif choice == "2":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"config_backup_{timestamp}.json"
            shutil.copy(os.path.join(os.path.dirname(__file__), "config.json"), backup_path)
            print(UI.success(f"Backed up to {backup_path}"))
    
    @staticmethod
    async def view_logs() -> None:
        """View service logs."""
        UI.clear()
        print(UI.header("Recent Logs"))
        
        code, logs = System.run_cmd("journalctl -u zohal -n 50 --no-pager 2>/dev/null || echo 'No logs available'")
        print(logs)


# ==================== MAIN ====================

async def main():
    """Main entry point."""
    # Check for updates on every run
    await Updater.check_and_notify()
    
    try:
        await Menu.main_menu()
    except KeyboardInterrupt:
        print(f"\n{UI.warning('Interrupted.')}")
    except Exception as e:
        print(f"\n{UI.error(f'Error: {str(e)}')}")


if __name__ == "__main__":
    asyncio.run(main())
