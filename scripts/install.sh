#!/bin/bash

# ============================================================
#        🪐  Zohal Uploader — Installer Script  🪐
# ============================================================

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}"
echo "============================================================"
echo "       🪐  Zohal Uploader — Installation Wizard  🪐"
echo "============================================================"
echo -e "${NC}"

# ─── Root check ────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: This installer must be run as root (use sudo).${NC}"
  exit 1
fi

INSTALL_DIR="/root/zohal-uploader"
BACKUP_CONFIG=0
BACKUP_DB=0

# ─── Stop old service if running ───────────────────────────
echo -e "${YELLOW}[Pre-flight] Stopping old service if running...${NC}"
systemctl stop zohal 2>/dev/null
systemctl disable zohal 2>/dev/null

# ─── Backup existing config + database ─────────────────────
if [ -d "$INSTALL_DIR" ]; then
  echo -e "${BLUE}Existing installation found. Backing up config and database...${NC}"
  if [ -f "$INSTALL_DIR/config.json" ]; then
    cp "$INSTALL_DIR/config.json" /tmp/zohal_config_backup.json
    BACKUP_CONFIG=1
    echo -e "  ✔ config.json → /tmp/zohal_config_backup.json"
  fi
  if [ -f "$INSTALL_DIR/zohal.db" ]; then
    cp "$INSTALL_DIR/zohal.db" /tmp/zohal_db_backup.db
    BACKUP_DB=1
    echo -e "  ✔ zohal.db → /tmp/zohal_db_backup.db"
  fi
  echo -e "${RED}Removing old installation directory...${NC}"
  rm -rf "$INSTALL_DIR"
fi

# ─── Step 1: System dependencies ───────────────────────────
echo -e "\n${YELLOW}[1/5] Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv ffmpeg curl git 2>&1 | grep -E "^(Get|Selecting|Unpacking|Setting up|Processing)" || true

# ─── Step 2: Copy project files ────────────────────────────
echo -e "\n${YELLOW}[2/5] Copying project files to ${INSTALL_DIR}...${NC}"
mkdir -p "$INSTALL_DIR"
CUR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$CUR_DIR" != "$INSTALL_DIR" ]; then
  cp -r "$CUR_DIR"/. "$INSTALL_DIR/"
  echo -e "  ✔ Files copied from $CUR_DIR"
fi

# ─── Restore backups ───────────────────────────────────────
if [ $BACKUP_CONFIG -eq 1 ]; then
  cp /tmp/zohal_config_backup.json "$INSTALL_DIR/config.json"
  rm /tmp/zohal_config_backup.json
  echo -e "${GREEN}  ✔ config.json restored from backup.${NC}"
fi
if [ $BACKUP_DB -eq 1 ]; then
  cp /tmp/zohal_db_backup.db "$INSTALL_DIR/zohal.db"
  rm /tmp/zohal_db_backup.db
  echo -e "${GREEN}  ✔ zohal.db restored from backup.${NC}"
fi

cd "$INSTALL_DIR" || exit 1

# ─── Step 3: Python virtual environment ────────────────────
echo -e "\n${YELLOW}[3/5] Creating Python virtual environment...${NC}"
python3 -m venv venv
echo -e "  ✔ venv created."

# ─── Step 4: Install Python packages ───────────────────────
echo -e "\n${YELLOW}[4/5] Installing Python packages...${NC}"
venv/bin/pip install --upgrade pip -q

if ! venv/bin/pip install -r requirements.txt; then
  echo -e "${YELLOW}  ⚠️ خطا در استفاده از میرور پیش‌فرض. تلاش مجدد با سرور رسمی PyPI...${NC}"
  if ! venv/bin/pip install -r requirements.txt --index-url https://pypi.org/simple; then
    echo -e "${RED}  ❌ خطا: نصب پیش‌نیازهای پایتون ناموفق بود. اتصال شبکه را بررسی کنید.${NC}"
    exit 1
  fi
fi
echo -e "  ✔ All Python packages installed."

# ─── Step 5: CLI wrapper ────────────────────────────────────
echo -e "\n${YELLOW}[5/5] Installing zohal-up CLI command...${NC}"
chmod +x "$INSTALL_DIR/cli.py"
cat > /usr/local/bin/zohal-up << 'WRAPPER'
#!/bin/bash
/root/zohal-uploader/venv/bin/python /root/zohal-uploader/cli.py "$@"
WRAPPER
chmod +x /usr/local/bin/zohal-up
echo -e "  ✔ 'zohal-up' command registered globally."

# ─── Register systemd service ──────────────────────────────
if [ -f "$INSTALL_DIR/scripts/zohal.service" ]; then
  cp "$INSTALL_DIR/scripts/zohal.service" /etc/systemd/system/zohal.service
  systemctl daemon-reload
  systemctl enable zohal.service
  systemctl start zohal.service
  echo -e "  ✔ zohal.service enabled and registered."
fi

# ─── Check if configuration is completed ───────────────────
SETUP_COMPLETED=0
if [ -f "$INSTALL_DIR/config.json" ]; then
  SETUP_COMPLETED=$(python3 -c "import json; print(1 if json.load(open('$INSTALL_DIR/config.json')).get('setup_completed') else 0)" 2>/dev/null)
fi

# ─── Done! ──────────────────────────────────────────────────
echo -e "\n${CYAN}"
echo "============================================================"
echo "           🎉  Installation Complete!  🎉"
echo "============================================================"
echo -e "${NC}"
echo -e "${GREEN}Zohal Uploader has been successfully installed.${NC}"
echo ""

if [ "$SETUP_COMPLETED" -ne 1 ]; then
  echo -e "  ${YELLOW}⚠️  توجه: ربات هنوز پیکربندی نشده است.${NC}"
  echo -e "  برای انجام تنظیمات اولیه و فعال‌سازی ربات، دستور زیر را اجرا کنید:"
  echo -e "  ${CYAN}zohal-up${NC} (سپس گزینه‌ی 7 را انتخاب کنید)"
else
  echo -e "  ${GREEN}✔ تنظیمات قبلی شناسایی و بارگذاری شد.${NC}"
  echo -e "  ربات زحل با موفقیت در حال اجرا است."
fi

echo ""
echo -e "  ${BOLD}CLI Management:${NC}"
echo -e "  Type ${CYAN}zohal-up${NC} from anywhere to manage the bot."
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
echo -e "  ${CYAN}systemctl status zohal${NC}       — check service status"
echo -e "  ${CYAN}systemctl restart zohal${NC}      — restart service"
echo -e "  ${CYAN}journalctl -u zohal -f -n 100${NC} — live logs"
echo ""
echo "============================================================"
