# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/dna_encoder.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Fighting-DNA extraction.
#
# This is the canonical module for encoding a fighter's movement style into a
# latent "fighting DNA" fingerprint, exposed under the file name referenced
# throughout the docs/README. The implementation lives in app/engine.py
# (PurePythonStyleEncoder) and is re-exported here so that:
#   from app.dna_encoder import FightingDNAEncoder
#   from app.engine import PurePythonStyleEncoder
# both work and reference the same encoder.
#
# FightingDNAEncoder.push() ingests a stream of normalized COCO-17 poses and
# encode() returns (latent, tags):
#   * latent — a fixed-size vector (default 64) whose leading entries encode
#              interpretable style axes (energy/aggression, stance width,
#              symmetry, normalized energy, habitual reach);
#   * tags   — human-readable tendency labels ("aggressive"/"patient",
#              "mobile"/"grounded", "balanced", "adaptive").
#
# The latent is the fingerprint fed to the adaptive opponent generator and the
# co-evolution policy so the AI adapts to THIS athlete's style.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import List, Sequence, Tuple

from .engine import PurePythonStyleEncoder

__all__ = ["FightingDNAEncoder", "PurePythonStyleEncoder"]


class FightingDNAEncoder(PurePythonStyleEncoder):
    """Public alias for the Fighting-DNA style encoder.

    Inherits the full push()/encode()/reset() implementation from the engine
    module so there is a single source of truth, while giving callers a stable,
    semantically-named entry point.
    """

    # (implementation inherited — see PurePythonStyleEncoder)
