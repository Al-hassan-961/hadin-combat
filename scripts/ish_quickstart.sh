#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HADIN-COMBAT – ish_quickstart.sh
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# One-command setup for iOS iSH Shell (Alpine Linux). Uses apk. Falls back to
# MediaPipe if the C++ build fails.
#
# Usage:  bash scripts/ish_quickstart.sh [repo_url]
# ---------------------------------------------------------------------------
set -euo pipefail

C_RESET=$'\e[0m'
C_GREEN=$'\e[32m'
C_CYAN=$'\e[36m'
C_YELLOW=$'\e[33m'
C_RED=$'\e[31m'
C_BOLD=$'\e[1m'

info() { echo -e "${C_CYAN}[HADIN]${C_RESET} $*"; }
ok()   { echo -e "${C_GREEN}[HADIN] ✅ $*${C_RESET}"; }
warn() { echo -e "${C_YELLOW}[HADIN] ⚠️  $*${C_RESET}"; }
fail() { echo -e "${C_RED}[HADIN] ❌ $*${C_RESET}"; }

REPO_URL="${1:-https://github.com/Al-hassan-961/hadin-combat.git}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/hadin-combat}"

echo -e "${C_BOLD}${C_GREEN}🥋 HADIN-COMBAT – iSH (iOS) quickstart${C_RESET}"

# ---------- 1. install deps via apk -------------------------------------------
info "Step 1/4: Installing packages (apk)..."
apk update >/dev/null 2>&1 || true
apk add --no-cache \
    python3 py3-pip git cmake make g++ gcc \
    >/dev/null 2>&1 || warn "Some packages may have failed."

# ---------- 2. clone -----------------------------------------------------------
info "Step 2/4: Cloning repository..."
if [ ! -d "$PROJECT_DIR" ]; then
    git clone "$REPO_URL" "$PROJECT_DIR" || { fail "Clone failed."; exit 1; }
fi
cd "$PROJECT_DIR"

# ---------- 3. venv + deps + build ----------------------------------------------
info "Step 3/4: Setting up Python and dependencies..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r python-backend/requirements.txt >/dev/null \
    || { fail "Core dependencies failed to install. Cannot continue."; exit 1; }
pip install -r python-backend/requirements-optional.txt >/dev/null 2>&1 \
    || warn "MediaPipe optional install failed – using OpenCV motion fallback."

BUILD_OK=1
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 \
    && cmake --build build -j"$(nproc)" >/dev/null 2>&1 \
    || BUILD_OK=0

USE_CPP="true"
if [ "$BUILD_OK" -ne 1 ] || ! ls build/*.so* >/dev/null 2>&1; then
    warn "C++ build failed. Falling back to MediaPipe."
    USE_CPP="false"
fi

cat > python-backend/.env <<EOF
USE_CPP_CORE=$USE_CPP
FALLBACK_TO_PYTHON=true
HOST=0.0.0.0
PORT=8000
EOF
ok "Configuration written."

# ---------- 4. run ---------------------------------------------------------------
info "Step 4/4: Starting server..."
LOCAL_IP="${LOCAL_IP:-127.0.0.1}"
echo
echo -e "${C_BOLD}${C_GREEN}✅ Server running at http://${LOCAL_IP}:8000 – open this URL in your browser!${C_RESET}"
echo

cd python-backend
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
