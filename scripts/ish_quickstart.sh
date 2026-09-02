#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HADIN-COMBAT – ish_quickstart.sh
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# One-command setup for iOS iSH Shell (Alpine Linux). Uses apk for pre-built
# native binaries (numpy + OpenCV) so pip never compiles C extensions.
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

# ---------- 1. install pre-built deps via apk ----------------------------------
info "Step 1/4: Installing packages via apk (pre-built numpy + OpenCV)..."
apk update >/dev/null 2>&1 || true
apk add --no-cache \
    python3 py3-pip git cmake make g++ gcc \
    py3-numpy py3-opencv \
    >/dev/null 2>&1 || {
        warn "apk install had issues. Ensure: apk add py3-numpy py3-opencv"
    }
ok "Pre-built native dependencies installed (no C compilation)."

# ---------- 2. clone -----------------------------------------------------------
info "Step 2/4: Cloning repository..."
if [ ! -d "$PROJECT_DIR" ]; then
    git clone "$REPO_URL" "$PROJECT_DIR" || { fail "Clone failed."; exit 1; }
fi
cd "$PROJECT_DIR"

# ---------- 3. venv + deps + build ----------------------------------------------
info "Step 3/4: Setting up Python and dependencies..."
python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1 || true

# HADIN_SYSTEM_OPENCV=1 tells setup.py that numpy/OpenCV already come from apk,
# so pip skips them (no C source build).
HADIN_SYSTEM_OPENCV=1 pip install -e . >/dev/null \
    || { fail "Core dependencies failed to install. Cannot continue."; exit 1; }

# Optional MediaPipe.
HADIN_SYSTEM_OPENCV=1 pip install -e ".[mediapipe]" >/dev/null 2>&1 \
    || warn "MediaPipe optional install failed – using OpenCV motion fallback."

BUILD_OK=1
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 \
    && cmake --build build -j"$(nproc)" >/dev/null 2>&1 \
    || BUILD_OK=0

USE_CPP="true"
if [ "$BUILD_OK" -ne 1 ] || ! ls build/*.so* >/dev/null 2>&1; then
    warn "C++ build skipped/failed. Using pure-Python pipeline."
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
echo
info "Launching HADIN-COMBAT (run.sh prints the access URL + QR) ..."
echo

exec bash "$PROJECT_DIR/scripts/run.sh" --port 8000
