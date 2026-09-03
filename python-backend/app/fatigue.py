# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/fatigue.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Real-time fatigue analysis (0-100).
#
# This is the canonical module for fatigue estimation, exposed under the file
# name referenced throughout the docs/README. The implementation lives in
# app/analytics.py (FatigueTracker) and is re-exported here so that:
#   from app.fatigue import FatigueTracker
#   from app.analytics import FatigueTracker
# both work and always point at the same class.
#
# FatigueTracker watches three signals over the session and outputs a live
# fatigue score plus recovery recommendations:
#   * snap / explosiveness decay   — technique speed & confidence drifting down
#   * reaction slowdown            — strike cadence (pause between attacks) rising
#   * stance stability             — shoulder-over-hip alignment wobble, and
#                                    stance WIDTH becoming erratic over time
# ---------------------------------------------------------------------------
from __future__ import annotations

from .analytics import (MAX_INTERVAL, SNAP_WINDOW, STANCE_WINDOW,
                        WARMUP_STRIKES, FatigueTracker, stance_width,
                        stance_wobble)

__all__ = ["FatigueTracker", "stance_wobble", "stance_width",
           "WARMUP_STRIKES", "SNAP_WINDOW", "STANCE_WINDOW", "MAX_INTERVAL"]
