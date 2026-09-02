# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/profiles.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Sparring-partner AI profiles. Each profile changes how the ghost opponent
# behaves mid-session: difficulty pressure, how much it moves/attacks
# (aggression) and how it frames up (guard).
# ---------------------------------------------------------------------------
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .coach import L_WRIST, R_WRIST

# COCO indices for "facing" helpers used below.
NOSE = 0
L_ANKLE, R_ANKLE = 15, 16
L_HIP, R_HIP = 11, 12

ProfileConfig = Dict[str, Any]

PROFILES: Dict[str, ProfileConfig] = {
    "balanced": {
        "label": "Balanced",
        "emoji": "🥊",
        "difficulty_boost": 0.0,     # added to base difficulty
        "aggression": 0.5,           # 0 (defensive) .. 1 (attacks constantly)
        "jitter": 0.02,              # pose randomness (movement/activity)
        "pressure": 0.0,             # how far the ghost closes in (0..1)
        "guard": 0.0,                # 0..1 how high the ghost keeps its guard
        "desc": "Rounds out every style — adapts to whatever you throw.",
    },
    "aggressive": {
        "label": "Aggressive",
        "emoji": "🔥",
        "difficulty_boost": 0.15,
        "aggression": 1.0,
        "jitter": 0.045,
        "pressure": 0.25,
        "guard": 0.2,
        "desc": "Swarm fighter — pushes forward and throws constant combinations.",
    },
    "counter_puncher": {
        "label": "Counter-Puncher",
        "emoji": "🛡️",
        "difficulty_boost": -0.05,
        "aggression": 0.15,
        "jitter": 0.012,
        "pressure": -0.15,           # backs off, waits for your mistakes
        "guard": 0.6,
        "desc": "Patience personified — slips, then snaps back after your miss.",
    },
    "defensive": {
        "label": "Defensive",
        "emoji": "🧱",
        "difficulty_boost": -0.12,
        "aggression": 0.05,
        "jitter": 0.008,
        "pressure": 0.05,
        "guard": 0.9,
        "desc": "High guard, tight shell — you must open it up with setups.",
    },
    "pressure_fighter": {
        "label": "Pressure Fighter",
        "emoji": "🚀",
        "difficulty_boost": 0.08,
        "aggression": 0.85,
        "jitter": 0.03,
        "pressure": 0.35,            # constantly cuts the distance
        "guard": 0.15,
        "desc": "Walks you down behind a busy jab — relentless forward pressure.",
    },
}

PROFILE_NAMES = list(PROFILES.keys())


def difficulty_for(profile: str, base: float) -> float:
    """Apply a profile's difficulty bias to the base co-evolution difficulty."""
    cfg = PROFILES.get(profile, PROFILES["balanced"])
    return max(0.05, min(1.0, base + cfg["difficulty_boost"]))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _shape_pose(pose: List[Dict[str, float]], cfg: ProfileConfig) -> List[Dict[str, float]]:
    """Apply profile framing (guard height, pressure) to a normalized pose."""
    out = [dict(p) for p in pose]

    def pt(i: int):
        return out[i] if i < len(out) else None

    # ---- Guard: raise wrists toward the chin when the style guards up -------
    nose = pt(NOSE)
    hip_l, hip_r = pt(L_HIP), pt(R_HIP)
    torso_top = nose["y"] if nose else 0.2
    if hip_l and hip_r:
        hip_mid = (hip_l["y"] + hip_r["y"]) / 2
    else:
        hip_mid = 0.6
    guard_target = torso_top + (hip_mid - torso_top) * 0.28  # around chin/upper chest

    for wr in (L_WRIST, R_WRIST):
        w = pt(wr)
        if w:
            # Blend wrist height toward guard height by the profile's guard value.
            w["y"] = _clamp(w["y"] * (1 - cfg["guard"]) + guard_target * cfg["guard"])
            if cfg["guard"] > 0.4:
                # pull wrists in toward the midline for a tight shell
                nose_x = nose["x"] if nose else 0.5
                w["x"] = _clamp(w["x"] + (nose_x - w["x"]) * (cfg["guard"] - 0.3))

    # ---- Pressure: ghost closes distance by drifting toward the athlete -------
    if cfg["pressure"] != 0:
        # "toward the athlete" = toward the vertical centre line of the frame.
        drift = cfg["pressure"]
        for i, p in enumerate(out):
            if drift > 0:
                p["x"] = _clamp(p["x"] * (1 - drift) + 0.5 * drift)
            else:  # counter-puncher backs away from centre
                p["x"] = _clamp(p["x"] + (0.5 - p["x"]) * (-drift))
            out[i] = p
    return out


def build_opponent(athlete_pose: Sequence[Dict[str, float]],
                   profile: str, difficulty: float,
                   rng: Optional[random.Random] = None) -> List[Dict[str, float]]:
    """Build a normalized opponent pose that mirrors the athlete, shaped by the
    chosen sparring profile. Returns [] if the athlete is not in frame."""
    athlete = list(athlete_pose)
    if not athlete:
        return []
    rng = rng or random
    cfg = PROFILES.get(profile, PROFILES["balanced"])
    d = max(0.0, min(1.0, difficulty))

    opponent = []
    for k in athlete:
        if k.get("score", 0.0) < 0.3:
            opponent.append({"x": 0.5, "y": 0.5, "score": 0.0})
            continue
        # Mirror horizontally (a front-facing opponent).
        mx = 1.0 - k["x"]
        my = k["y"]
        jitter = (cfg["jitter"] + 0.03 * d * cfg["aggression"])
        jx = rng.gauss(0.0, jitter)
        jy = rng.gauss(0.0, jitter)
        opponent.append({"x": _clamp(mx + jx), "y": _clamp(my + jy), "score": 1.0})

    return _shape_pose(opponent, cfg)
