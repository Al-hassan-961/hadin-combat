# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/coevolution.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Session-over-session co-evolution.
#
# Canonical module for the co-evolution policy (both the athlete and the AI
# improve across sessions). The implementation lives in app/engine.py
# (PurePythonCoEvolution) and is re-exported here:
#   from app.coevolution import CoEvolutionPolicy
#   from app.engine import PurePythonCoEvolution
#
# CoEvolutionPolicy.step(profile, current_difficulty) reads the athlete's
# long-term profile (win_rate, progress_score, total_sessions) and nudges the
# next opponent difficulty so it always challenges-but-never-overwhelms.
# ---------------------------------------------------------------------------
from __future__ import annotations

from .engine import PurePythonCoEvolution

__all__ = ["CoEvolutionPolicy"]


class CoEvolutionPolicy(PurePythonCoEvolution):
    """Public alias for the co-evolution difficulty policy."""
