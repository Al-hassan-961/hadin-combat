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
SSL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)   HOST="$2"; shift 2 ;;
        --port)   PORT="$2"; shift 2 ;;
        --ssl)    SSL=1; shift ;;
        --open)   OPEN=1; shift ;;
        --no-qr)  QR=0; shift ;;
        -h|--help)
            echo "Usage: bash scripts/run.sh [--port 8000] [--host 0.0.0.0] [--ssl] [--open] [--no-qr]"
            echo "  --ssl   serve HTTPS (self-signed cert) so the camera works"
            echo "          on OTHER devices (browsers block getUserMedia on"
            echo "          plain http for non-localhost addresses)."
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

# ---------- Termux system deps pre-flight --------------------------------------
# numpy + OpenCV are system dependencies. On Termux, if they are not
# importable, install the pre-built packages (never pip-build them).
ensure_termux_system_deps() {
    [ "${TERMUX_VERSION:-}" = "" ] && return 0
    if python3 -c "import numpy, cv2" >/dev/null 2>&1; then
        ok "System numpy + OpenCV already available."
        return 0
    fi
    warn "numpy/OpenCV not importable – installing Termux pre-built packages..."
    pkg install -y x11-repo tur-repo >/dev/null 2>&1 || true
    pkg update -y >/dev/null 2>&1 || true
    if ! pkg install -y python-numpy python-opencv clang >/dev/null 2>&1; then
        # Some Termux mirrors name the Python binding package differently.
        pkg install -y python-numpy python-opencv-python clang >/dev/null 2>&1 || \
            warn "Auto-install failed. Run manually: pkg install python-numpy python-opencv clang"
    fi
    ok "System dependencies ready."
}

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

# ---------- HTTPS (self-signed cert) ---------------------------------------------
SCHEME="http"
SSL_ARGS=()
if [ "$SSL" -eq 1 ]; then
    SCHEME="https"
    CERTS_DIR="$ROOT/certs"
    mkdir -p "$CERTS_DIR"
    CERT="$CERTS_DIR/cert.pem"
    KEY="$CERTS_DIR/key.pem"
    if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
        info "Generating a self-signed certificate (valid 1 year)..."
        if command -v openssl >/dev/null 2>&1; then
            openssl req -x509 -newkey rsa:2048 -keyout "$KEY" -out "$CERT" \
                -days 365 -nodes -subj "/CN=hadin-combat" >/dev/null 2>&1 \
                || { fail "openssl failed"; exit 1; }
        else
            # Pure-Python fallback (cryptography may not be installed; use ssl).
            "$ROOT/.venv/bin/python" - "$CERT" "$KEY" <<'PYEOF' 2>/dev/null \
                || { fail "Cannot generate cert. Install openssl: pkg install openssl-tool"; exit 1; }
import ssl, sys
print("python ssl cert generation requires the 'cryptography' lib; install openssl-tool instead", file=sys.stderr)
sys.exit(1)
PYEOF
        fi
        chmod 600 "$KEY"
        ok "Certificate ready at $CERT"
    fi
    SSL_ARGS=(--ssl-certfile "$CERT" --ssl-keyfile "$KEY")
fi
LAN_URL="${SCHEME}://${LOCAL_IP}:${PORT}"
LOCAL_URL="${SCHEME}://127.0.0.1:${PORT}"

# ---------- system deps check (Termux) ---------------------------------------------
ensure_termux_system_deps

# ---------- optional silent AI-coach preflight (best-effort, never blocks) ----------
# Auto-activates the global-AI coach if google-genai + GEMINI_API_KEY are ready;
# silently falls back to the local ML coach otherwise. Failures are ignored.
[ -f "$ROOT/scripts/prepare_ai_coach.sh" ] && \
    bash "$ROOT/scripts/prepare_ai_coach.sh" >/dev/null 2>&1 || true

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
echo -e "${C_DIM}   📷 Camera tip: browsers block getUserMedia on plain http for"
echo -e "   non-localhost addresses. On this phone use ${C_CYAN}${LOCAL_URL}${C_RESET}${C_DIM},"
echo -e "   or restart with ${C_CYAN}--ssl${C_RESET}${C_DIM} for HTTPS on other devices.${C_RESET}"
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
info "Starting HADIN-COMBAT on ${HOST}:${PORT} (${SCHEME}) ..."
echo
exec uvicorn app.main:app --host "$HOST" --port "$PORT" "${SSL_ARGS[@]}"
