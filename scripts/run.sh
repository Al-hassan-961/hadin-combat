#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HADIN-COMBAT – scripts/run.sh
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Professional, Termux-aware launcher for the HADIN-COMBAT server.
#
# What it does:
#   * loads/creates .env
#   * auto-detects the device's local IP (works on Termux/Android, Linux, macOS)
#   * prints a clean startup screen with the local + LAN URLs
#   * shows a scannable QR code for the LAN URL (if `qrencode` is available)
#   * optionally opens the browser (Termux: termux-open-url)
#   * starts uvicorn bound to 0.0.0.0 so any device on your network can connect
#
# Usage:
#   bash scripts/run.sh [--port 8000] [--host 0.0.0.0] [--open] [--no-qr]
# ---------------------------------------------------------------------------
set -euo pipefail

# ---------- options --------------------------------------------------------
HOST="0.0.0.0"
PORT="8000"
OPEN=0
QR=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)   HOST="$2"; shift 2 ;;
        --port)   PORT="$2"; shift 2 ;;
        --open)   OPEN=1; shift ;;
        --no-qr)  QR=0; shift ;;
        -h|--help)
            echo "Usage: bash scripts/run.sh [--port 8000] [--host 0.0.0.0] [--open] [--no-qr]"
            exit 0 ;;
        *) shift ;;
    esac
done

# ---------- colours ---------------------------------------------------------
C_RESET=$'\e[0m'; C_BOLD=$'\e[1m'; C_DIM=$'\e[2m'
C_GREEN=$'\e[32m'; C_CYAN=$'\e[36m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'
info() { echo -e "${C_CYAN}[HADIN]${C_RESET} $*"; }
ok()   { echo -e "${C_GREEN}  ✔ $*${C_RESET}"; }
warn() { echo -e "${C_YELLOW}  ⚠ $*${C_RESET}"; }

# ---------- resolve repo root -------------------------------------------------
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Activate the venv if one exists.
if [ -d "$ROOT/.venv/bin" ]; then
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
fi

# ---------- ensure .env ---------------------------------------------------------
ENV_FILE="$ROOT/python-backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    info "No .env found – creating a default one."
    cat > "$ENV_FILE" <<EOF
USE_CPP_CORE=false
FALLBACK_TO_PYTHON=true
HOST=$HOST
PORT=$PORT
EOF
fi

# ---------- detect local IP (Termux-aware) --------------------------------------
detect_ip() {
    local ip
    ip="$(ip -4 addr show 2>/dev/null | awk '/inet / && $2 !~ /^127\./ {split($2,a,"/"); print a[1]; exit}')"
    [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -z "$ip" ] && ip="$(ifconfig 2>/dev/null | awk '/inet / && $2 !~ /^127\./ {print $2; exit}')"
    [ -z "$ip" ] && ip="127.0.0.1"
    echo "$ip"
}
LOCAL_IP="$(detect_ip)"
LAN_URL="http://${LOCAL_IP}:${PORT}"
LOCAL_URL="http://127.0.0.1:${PORT}"

# ---------- banner ----------------------------------------------------------------
clear 2>/dev/null || true
echo -e "${C_BOLD}${C_GREEN}"
cat <<'EOF'
  ██╗  ██╗ █████╗ ██████╗ ██╗███╗   ██╗    ██████╗ ██████╗ ███╗   ███╗██████╗  █████╗ ████████╗
  ██║  ██║██╔══██╗██╔══██╗██║████╗  ██║   ██╔════╝██╔═══██╗████╗ ████║██╔══██╗██╔══██╗╚══██╔══╝
  ███████║███████║██║  ██║██║██╔██╗ ██║   ██║     ██║   ██║██╔████╔██║██████╔╝███████║   ██║
  ██╔══██║██╔══██║██║  ██║██║██║╚██╗██║   ██║     ██║   ██║██║╚██╔╝██║██╔══██╗██╔══██║   ██║
  ██║  ██║██║  ██║██████╔╝██████╔╝██║██║ ╚████║   ╚██████╗╚██████╔╝██║ ╚═╝ ██║██████╔╝██║   ██║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝    ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═════╝ ╚═╝   ╚═╝
EOF
echo -e "${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}HADIN-COMBAT · The AI Opponent That Learns Your Fighting DNA${C_RESET}"
echo -e "${C_DIM}Created by Al-hassan Shehade & Dina Balcheh${C_RESET}\n"

echo -e "${C_BOLD}   ▸ Open in THIS phone's browser:${C_RESET}"
echo -e "       ${C_CYAN}${LOCAL_URL}${C_RESET}"
echo
echo -e "${C_BOLD}   ▸ Other devices on your Wi-Fi:${C_RESET}"
echo -e "       ${C_CYAN}${LAN_URL}${C_RESET}"
echo

# ---------- QR code for the LAN URL (scan with another phone) ----------------------
if [ "$QR" -eq 1 ] && command -v qrencode >/dev/null 2>&1; then
    echo -e "${C_BOLD}   ▸ Scan to open on another device:${C_RESET}"
    echo "$LAN_URL" | qrencode -t ANSIUTF8 2>/dev/null || echo "$LAN_URL"
    echo
elif [ "$QR" -eq 1 ] && [ "${TERMUX_VERSION:-}" != "" ]; then
    warn "Install qrencode for a scannable QR code:  pkg install qrencode"
fi

echo -e "${C_BOLD}   ▸ This screen stays live while the server runs.${C_RESET}"
echo -e "${C_DIM}   Press Ctrl+C to stop.${C_RESET}"
echo

# ---------- open browser ------------------------------------------------------------
if [ "$OPEN" -eq 1 ]; then
    if [ "${TERMUX_VERSION:-}" != "" ] && command -v termux-open-url >/dev/null 2>&1; then
        termux-open-url "$LOCAL_URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$LOCAL_URL" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "$LOCAL_URL" >/dev/null 2>&1 || true   # macOS
    fi
fi

# ---------- start server --------------------------------------------------------------
cd "$ROOT/python-backend"
info "Starting HADIN-COMBAT on ${HOST}:${PORT} ..."
echo
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
