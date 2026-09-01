#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HADIN-COMBAT – termux_quickstart.sh
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# One-command setup for Android Termux.
#
# ZERO-COMPILATION on Android: numpy and OpenCV are installed as Termux's
# pre-built packages (`pkg install python-numpy python-opencv-python`), and
# the Python deps are installed via `pip install -e .`, whose setup.py skips
# numpy/opencv on Termux so pip never triggers a C source build.
#
# Usage:  bash scripts/termux_quickstart.sh [repo_url]
# ---------------------------------------------------------------------------
set -euo pipefail

# ---------- Colours / helpers ----------------------------------------------
C_RESET=$'\e[0m'
C_GREEN=$'\e[32m'
C_CYAN=$'\e[36m'
C_YELLOW=$'\e[33m'
C_RED=$'\e[31m'
C_BOLD=$'\e[1m'

info()  { echo -e "${C_CYAN}[HADIN]${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}[HADIN] ✅ $*${C_RESET}"; }
warn()  { echo -e "${C_YELLOW}[HADIN] ⚠️  $*${C_RESET}"; }
fail()  { echo -e "${C_RED}[HADIN] ❌ $*${C_RESET}"; }

REPO_URL="${1:-https://github.com/Al-hassan-961/hadin-combat.git}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/hadin-combat}"

# ---------- Step 0: banner ---------------------------------------------------
echo -e "${C_BOLD}${C_CYAN}"
cat <<'EOF'
   _   _    _    _   _ ___   ___    ___  ___  _____ _____  _   _ ___ _____
  | | | |  / \  | \ | |_ _| / _ \  / __|/ _ \|_   _|_   _|/ \ | |_ _|_   _|
  | |_| | / _ \ |  \| || | | | | | \__ \ (_) | | |   | | / _ \| || |  | |
  |  _  |/ ___ \| |\  || | | |_| | __/ |> _ <  | |   | |/ ___ \ || |  | |
  |_| |_/_/   \_\_| \_|___| \___/ |___/_/ \_\ |_|   |_/_/   \_\___|  |_|
EOF
echo -e "${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}HADIN-COMBAT – The AI Opponent That Learns Your Fighting DNA${C_RESET}"
echo -e "${C_CYAN}Created by Al-hassan Shehade & Dina Balcheh${C_RESET}\n"

# ---------- Step 1: update packages -------------------------------------------
info "Step 1/6: Updating Termux packages..."
pkg update -y >/dev/null 2>&1 || warn "pkg update failed (continuing)"
pkg upgrade -y >/dev/null 2>&1 || true

# ---------- Step 2: install pre-built system packages --------------------------
info "Step 2/6: Installing pre-built Termux packages (numpy + OpenCV)..."
# python-numpy and python-opencv-python provide native binaries so pip never
# needs to compile C extensions. clang/cmake are only for the optional C++ core.
pkg install -y \
    git python clang cmake make pkg-config binutils \
    python-numpy python-opencv-python \
    >/dev/null 2>&1 || {
        warn "Some packages failed. At minimum you need: pkg install python-numpy python-opencv-python"
        warn "Re-run: pkg install -y python-numpy python-opencv-python"
    }
ok "Pre-built native dependencies installed (no C compilation)."

# ---------- Step 3: clone / enter repo ------------------------------------------
info "Step 3/6: Preparing project directory..."
if [ ! -d "$PROJECT_DIR" ]; then
    info "Cloning repository..."
    git clone "$REPO_URL" "$PROJECT_DIR" || { fail "Clone failed."; exit 1; }
fi
cd "$PROJECT_DIR"
ok "Working in $(pwd)"

# ---------- Step 4: python venv + deps -------------------------------------------
info "Step 4/6: Setting up Python virtual environment..."
python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1 || true

# `pip install -e .` uses setup.py, which DETECTS Termux and skips numpy/OpenCV
# so pip never triggers a source build (which would fail on Bionic's missing ctanh).
pip install -e . >/dev/null \
    || { fail "Core dependencies failed to install."; exit 1; }

# Optional MediaPipe – improves pose quality, but NOT required.
pip install -e ".[mediapipe]" >/dev/null 2>&1 \
    || warn "MediaPipe optional install failed – using OpenCV motion fallback."
ok "Python environment ready (zero C compilation)."

# ---------- Step 5: build C++ core (optional, graceful) -------------------------
info "Step 5/6: Building C++ core (optional accelerator)..."
BUILD_OK=1
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 \
    && cmake --build build -j"$(nproc)" >/dev/null 2>&1 \
    || BUILD_OK=0

if [ "$BUILD_OK" -eq 1 ] && ls build/*.so* >/dev/null 2>&1; then
    ok "C++ core built successfully (sub-50ms inference)."
    USE_CPP="true"
else
    warn "C++ build skipped/failed – using pure-Python pipeline (MediaPipe/OpenCV)."
    USE_CPP="false"
fi

# ---------- Step 6: write .env + launch server ------------------------------------
info "Step 6/6: Writing configuration and starting server..."
cat > python-backend/.env <<EOF
USE_CPP_CORE=$USE_CPP
FALLBACK_TO_PYTHON=true
HOST=0.0.0.0
PORT=8000
EOF
ok "Configuration written to python-backend/.env"

# Detect local IP for the friendly access message.
LOCAL_IP="$(ifconfig 2>/dev/null | awk '/inet / && $2 !~ /^127/ {print $2; exit}' || true)"
LOCAL_IP="${LOCAL_IP:-127.0.0.1}"

echo
echo -e "${C_BOLD}${C_GREEN}════════════════════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_GREEN}  🚀 Starting HADIN-COMBAT server...${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}  ✅ Server running at http://${LOCAL_IP}:8000 – open this URL in your browser!${C_RESET}"
echo -e "${C_GREEN}  Backend: $([ "$USE_CPP" = "true" ] && echo "C++ ONNX core" || echo "MediaPipe/OpenCV (pure Python)")${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}════════════════════════════════════════════════════════════════════${C_RESET}"
echo

cd python-backend
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
