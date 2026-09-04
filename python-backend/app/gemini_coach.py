# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/gemini_coach.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Backward-compatibility alias. The canonical silent global-AI coach now lives
# in app/gemini_free.py. This module re-exports the same public API so existing
# imports and tests keep working:
#   from app.gemini_coach import GeminiCoach, SilentCoach, get_coach, ...
#
# (The class is named SilentCoach because it never surfaces a provider name in
# the UI — it silently enriches the local coach or falls back to it.)
# ---------------------------------------------------------------------------
from __future__ import annotations

from .gemini_free import (  # noqa: F401
    DEFAULT_MODEL,
    FUNCTION_SCHEMA,
    SilentCoach,
    _coerce_verdict,
    _parse_json_in_text,
    extract_verdict_from_tool_call,
    get_coach,
)

# Compatibility alias: older code/tests used `GeminiCoach`.
GeminiCoach = SilentCoach

__all__ = ["SilentCoach", "GeminiCoach", "get_coach",
           "extract_verdict_from_tool_call", "FUNCTION_SCHEMA", "DEFAULT_MODEL"]
