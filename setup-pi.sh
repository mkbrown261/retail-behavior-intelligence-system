#!/usr/bin/env bash
# =============================================================================
# setup-pi.sh — One-time Raspberry Pi setup for RBIS
#
# Run this ONCE after cloning the repo onto a fresh Pi.
# It installs all system packages, Python dependencies, configures the
# .env file, and registers RBIS as a systemd service so it starts
# automatically every time the Pi powers on.
#
# Usage:
#   bash setup-pi.sh
#
# After it finishes:
#   - Dashboard: http://<pi-ip>:8000  (or http://rbis.local:8000 if mDNS works)
#   - Control:   sudo systemctl start|stop|restart|status rbis
#   - Logs:      sudo journalctl -u rbis -f
#
# Requirements: Raspberry Pi OS (Bullseye or Bookworm), internet connection
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$SCRIPT_DIR/backend"
PORT="${PORT:-8000}"
SERVICE_NAME="rbis"
SERVICE_USER="${SUDO_USER:-pi}"          # the non-root user who will own the service
VENV="$SCRIPT_DIR/.venv"

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${YELLOW}→${NC}  $*"; }
err()  { echo -e "${RED}✗${NC}  $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   RBIS — Raspberry Pi Setup                          ║"
echo "║   Retail Behavior Intelligence System v2.0           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Must NOT be run as root directly — but needs sudo for systemd ─────────────
if [ "$EUID" -eq 0 ] && [ -z "$SUDO_USER" ]; then
    err "Don't run as root directly. Run: bash setup-pi.sh"
fi

# ── 1. System packages ────────────────────────────────────────────────────────
info "Installing system packages (needs sudo password)…"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    ffmpeg \
    v4l-utils \
    git \
    curl \
    avahi-daemon \
    2>/dev/null
ok "System packages installed"

# Enable mDNS so the Pi is reachable as rbis.local
sudo systemctl enable avahi-daemon --quiet 2>/dev/null || true
sudo systemctl start  avahi-daemon 2>/dev/null || true

# Set a friendly hostname so it shows up as rbis.local on the network
CURRENT_HOSTNAME=$(hostname)
if [ "$CURRENT_HOSTNAME" != "rbis" ]; then
    info "Setting hostname to 'rbis' (will be rbis.local on your network)…"
    sudo hostnamectl set-hostname rbis 2>/dev/null || true
    sudo sed -i "s/$CURRENT_HOSTNAME/rbis/g" /etc/hosts 2>/dev/null || true
    ok "Hostname set to 'rbis'"
fi

# ── 2. Python virtual environment ─────────────────────────────────────────────
info "Creating Python virtual environment…"
python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
ok "Virtual environment ready at $VENV"

# ── 3. Python dependencies ────────────────────────────────────────────────────
info "Installing Python dependencies (this takes 3-5 minutes on a Pi)…"
pip install --quiet -r "$BACKEND/requirements.txt"
ok "Python dependencies installed"

# ── 4. Data directories ───────────────────────────────────────────────────────
info "Creating data directories…"
mkdir -p "$SCRIPT_DIR/data/snapshots" \
         "$SCRIPT_DIR/data/clips" \
         "$SCRIPT_DIR/data/reports"
ok "Data directories created"

# ── 5. Environment file ───────────────────────────────────────────────────────
ENV_FILE="$BACKEND/.env"
if [ ! -f "$ENV_FILE" ]; then
    info "Creating .env from template…"
    cp "$BACKEND/.env.example" "$ENV_FILE"

    # Generate a real SECRET_KEY automatically
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/CHANGE_ME_use_secrets.token_hex(32)/$SECRET/" "$ENV_FILE"

    # Point DATABASE_URL and LOCAL_STORAGE_PATH to the data/ folder
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=sqlite+aiosqlite:///$SCRIPT_DIR/data/rbis.db|" "$ENV_FILE"
    sed -i "s|LOCAL_STORAGE_PATH=.*|LOCAL_STORAGE_PATH=$SCRIPT_DIR/data|" "$ENV_FILE"

    ok ".env created with auto-generated SECRET_KEY"
else
    ok ".env already exists — skipping"
fi

# ── 6. systemd service ────────────────────────────────────────────────────────
info "Registering RBIS as a systemd service…"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=RBIS — Retail Behavior Intelligence System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$BACKEND
Environment="PATH=$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$BACKEND"
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-server-header
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
ok "systemd service '$SERVICE_NAME' enabled and started"

# ── 7. Get the Pi's local IP ──────────────────────────────────────────────────
sleep 3   # give uvicorn a moment to bind
LOCAL_IP=$(python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except:
    print('127.0.0.1')
")

# Quick health check
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/api/health" 2>/dev/null || echo "000")

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Setup Complete!                                     ║"
echo "╠══════════════════════════════════════════════════════╣"
if [ "$HTTP_STATUS" = "200" ]; then
echo "║   ✅ Backend is running (HTTP $HTTP_STATUS)               ║"
else
echo "║   ⚠️  Backend starting up... check in a few seconds  ║"
fi
echo "║                                                       ║"
echo "║   Dashboard URL (from the Pi itself):                 ║"
echo "║     http://localhost:$PORT                            ║"
echo "║                                                       ║"
echo "║   Dashboard URL (from your phone / laptop):           ║"
echo "║     http://$LOCAL_IP:$PORT"
echo "║     http://rbis.local:$PORT  (if mDNS works)         ║"
echo "║                                                       ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║   Useful commands:                                    ║"
echo "║     sudo systemctl status rbis                        ║"
echo "║     sudo systemctl restart rbis                       ║"
echo "║     sudo journalctl -u rbis -f        (live logs)     ║"
echo "║     sudo systemctl stop rbis                          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  ➡  Add cameras: open the dashboard → Cameras → + Add Camera"
echo "  ➡  Or edit backend/cameras.yaml directly and restart."
echo ""
