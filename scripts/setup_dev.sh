#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HADIN-COMBAT – setup_dev.sh
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Linux / macOS development environment setup.
#
# Usage:  bash scripts/setup_dev.sh
# ---------------------------------------------------------------------------
set -euo pipefail

C_RESET=$'\e[0m'
C_GREEN=$'\e[32m'
C_CYAN=$'\e[36m'
C_YELLOW=$'\e[33m'

info() { echo -e "${C_CYAN}[HADIN]${C_RESET} $*"; }
ok()   { echo -e "${C_GREEN}[HADIN] ✅ $*${C_RESET}"; }
warn() { echo -e "${C_YELLOW}[HADIN] ⚠️  $*${C_RESET}"; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ---------- 0. Termux system deps (pre-built, never pip-built) -----------------
# numpy + OpenCV are system dependencies. On Termux install them via pkg;
# on other platforms the `.[native]` extra provides the wheels.
ON_TERMUX=0
if [ -n "${TERMUX_VERSION:-}" ] || [ -d /data/data/com.termux ]; then
    ON_TERMUX=1
fi

if [ "$ON_TERMUX" -eq 1 ]; then
    info "Termux detected – installing pre-built system packages..."
    pkg install -y x11-repo tur-repo >/dev/null 2>&1 || true
    pkg update -y >/dev/null 2>&1 || true
    if ! pkg install -y python-numpy python-opencv clang >/dev/null 2>&1; then
        pkg install -y python-numpy python-opencv-python clang >/dev/null 2>&1 || \
            warn "pkg install failed. Run manually: pkg install python-numpy python-opencv clang"
    fi
    ok "System numpy + OpenCV ready."
fi

# ---------- 1. Python env ------------------------------------------------------
info "Step 1/4: Creating Python virtual environment..."
python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
# setup.py NEVER installs numpy/OpenCV via pip. On Termux they already come
# from pkg; on Linux/macOS/Windows the `.[native]` extra adds the wheels.
pip install -e .
if [ "$ON_TERMUX" -eq 1 ]; then
    ok "Skipped pip numpy/OpenCV (provided by Termux pkg)."
else
    pip install -e ".[native]"
fi
pip install pytest ruff black
pip install -e ".[mediapipe]" >/dev/null 2>&1 || true
ok "Python environment ready."

# ---------- 2. C++ core --------------------------------------------------------
info "Step 2/4: Building C++ core (optional)..."
BUILD_OK=1
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 \
    && cmake --build build -j"$(nproc)" >/dev/null 2>&1 \
    || BUILD_OK=0

USE_CPP="true"
if [ "$BUILD_OK" -ne 1 ] || ! ls build/*.so* >/dev/null 2>&1; then
    warn "C++ build failed. Falling back to MediaPipe (USE_CPP_CORE=false)."
    USE_CPP="false"
else
    ok "C++ core built."
fi

# ---------- 3. config ------------------------------------------------------------
info "Step 3/4: Writing default configuration..."
cat > python-backend/.env <<EOF
USE_CPP_CORE=$USE_CPP
FALLBACK_TO_PYTHON=true
HOST=0.0.0.0
PORT=8000
EOF
ok "Configuration written."

# ---------- 4. run ---------------------------------------------------------------
info "Step 4/4: Starting development server..."
echo
info "Launching HADIN-COMBAT (run.sh prints the access URL + QR) ..."
echo

exec bash "$ROOT/scripts/run.sh" --port 8000
