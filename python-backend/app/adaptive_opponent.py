# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/adaptive_opponent.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Adaptive sparring opponent.
#
# This is the canonical module for the AI opponent that adapts its stance,
# tempo and defense to counter the athlete, exposed under the file name
# referenced throughout the docs/README. The implementations live in
# app/engine.py (PurePythonOpponentGenerator) and app/coevolution.py
# (PurePythonCoEvolution) and are re-exported / aliased here so callers get a
# stable, semantically-named API:
#
#   AdaptiveOpponent   — mirrors the athlete and adds difficulty/defense bias
#                        shaped by the active sparring profile.
#   CoEvolutionPolicy  — picks the next difficulty from the athlete's long-term
#                        profile so both athlete and AI improve session-over-
#                        session.
#
# The fighting-DNA latent (app/dna_encoder.py) conditions how aggressively /
# defensively the opponent responds, and app/profiles.py shapes its framing
# (guard height, pressure) by sparring style.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .coevolution import CoEvolutionPolicy  # noqa: F401  (re-exported here)
from .engine import PurePythonOpponentGenerator
from .profiles import build_opponent

__all__ = ["AdaptiveOpponent", "CoEvolutionPolicy", "build_opponent"]


class AdaptiveOpponent(PurePythonOpponentGenerator):
    """Public alias for the adaptive opponent generator.

    Generates a normalized opponent pose from the athlete's current pose,
    mirroring it and adding difficulty-scaled responsiveness. Profile-specific
    framing (guard / pressure) is applied via app.profiles.build_opponent.
    """
