#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# HADIN-COMBAT – scripts/prepare_ai_coach.sh
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Optional auto-enable helper for the silent global-AI coach (official
# Google free-tier API). It is NOT required — HADIN auto-activates the coach at
# startup when a key is present, and silently uses the local ML engine otherwise.
#
# This script only:
#   1. ensures the pure-Python `google-genai` SDK is installed (free tier), and
#   2. reminds you to set GEMINI_API_KEY if it isn't already set.
#
# It never touches cookies and never talks to any third-party proxy.
#
# Usage:  bash scripts/prepare_ai_coach.sh
# ---------------------------------------------------------------------------
set -euo pipefail

C_RESET=$'\e[0m'; C_GREEN=$'\e[32m'; C_CYAN=$'\e[36m'; C_YELLOW=$'\e[33m'
ok()   { echo -e "${C_GREEN}[HADIN] ✅ $*${C_RESET}"; }
info() { echo -e "${C_CYAN}[HADIN] ℹ️  $*${C_RESET}"; }
warn() { echo -e "${C_YELLOW}[HADIN] ⚠️  $*${C_RESET}"; }

# Prefer the project venv if present.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="python3"
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; fi

# 1. google-genai (official SDK). Install only if importable via the venv.
if "$PY" -c "import google.genai" >/dev/null 2>&1; then
    ok "google-genai already available."
else
    info "Installing google-genai (official free-tier SDK)…"
    "$PY" -m pip install -q "google-genai>=1.0" \
        && ok "google-genai installed." \
        || warn "Could not install google-genai — the local ML coach will be used (no problem)."
fi

# 2. Key check (never printed, never logged to files).
if [ -n "${GEMINI_API_KEY:-}" ]; then
    ok "GEMINI_API_KEY is set — the AI coach will auto-activate at startup."
else
    warn "GEMINI_API_KEY is not set — silent local-ML coaching will be used."
    info "Get a free key at https://aistudio.google.com/apikey then add to python-backend/.env:"
    info "  GEMINI_API_KEY=your_key   (and optionally GEMINI_MODEL=gemini-2.0-flash-exp)"
fi

exit 0
