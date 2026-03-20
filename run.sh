#!/usr/bin/env bash
# run.sh — Start RBIS without Docker
# Usage: bash run.sh
# Requirements: Python 3.10+, pip

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$SCRIPT_DIR/backend"
PORT="${PORT:-8000}"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   RBIS — Retail Behavior Intelligence System ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "❌  Python 3 is not installed. Download from https://python.org"
  exit 1
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓  Python $PY_VERSION found"

# ── 2. Create virtualenv if needed ──────────────────────────────────────────
VENV="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV" ]; then
  echo "→  Creating virtual environment…"
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"

# ── 3. Install dependencies ──────────────────────────────────────────────────
echo "→  Installing / checking dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r "$BACKEND/requirements.txt"
echo "✓  Dependencies ready"

# ── 4. Create data dirs ──────────────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/data/snapshots" \
         "$SCRIPT_DIR/data/clips" \
         "$SCRIPT_DIR/data/reports"

# ── 5. Show local IP for phone access ────────────────────────────────────────
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

echo ""
echo "══════════════════════════════════════════════"
echo "  Dashboard URL (this computer):"
echo "    http://localhost:$PORT"
echo ""
echo "  Dashboard URL (phone / other devices on same WiFi):"
echo "    http://$LOCAL_IP:$PORT"
echo ""
echo "  📱 Open the phone URL to add cameras from your phone"
echo "══════════════════════════════════════════════"
echo ""
echo "  Press Ctrl+C to stop"
echo ""

# ── 6. Start backend ─────────────────────────────────────────────────────────
cd "$BACKEND"
DATABASE_URL="sqlite+aiosqlite:///$SCRIPT_DIR/data/rbis.db" \
LOCAL_STORAGE_PATH="$SCRIPT_DIR/data" \
PORT="$PORT" \
uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
