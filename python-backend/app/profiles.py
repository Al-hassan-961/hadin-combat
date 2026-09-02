# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/profiles.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Sparring-partner AI profiles. Each profile changes how the ghost opponent
# behaves mid-session: difficulty pressure, how much it moves/attacks
# (aggression) and how it frames up (guard).
#
# Profile definitions live in python-backend/config/profiles.json (editable
# without code changes); the dict below is the built-in fallback. The user's
# last chosen profile is persisted to python-backend/data/preferences.json so
# new sessions start with their preferred sparring style.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .coach import L_WRIST, R_WRIST

# COCO indices used by the shaping helpers.
NOSE = 0
L_ANKLE, R_ANKLE = 15, 16
L_HIP, R_HIP = 11, 12

ProfileConfig = Dict[str, Any]

# ---- Built-in defaults (fallback when the JSON config is missing) -------------
DEFAULT_PROFILES: Dict[str, ProfileConfig] = {
    "balanced": {
        "label": "Balanced", "emoji": "🥊",
        "difficulty_boost": 0.0, "aggression": 0.5,
        "jitter": 0.02, "pressure": 0.0, "guard": 0.0,
        "desc": "Rounds out every style — adapts to whatever you throw.",
    },
    "aggressive": {
        "label": "Aggressive", "emoji": "🔥",
        "difficulty_boost": 0.15, "aggression": 1.0,
        "jitter": 0.045, "pressure": 0.25, "guard": 0.2,
        "desc": "Swarm fighter — pushes forward and throws constant combinations.",
    },
    "counter_puncher": {
        "label": "Counter-Puncher", "emoji": "🛡️",
        "difficulty_boost": -0.05, "aggression": 0.15,
        "jitter": 0.012, "pressure": -0.15, "guard": 0.6,
        "desc": "Patience personified — slips, then snaps back after your miss.",
    },
    "defensive": {
        "label": "Defensive", "emoji": "🧱",
        "difficulty_boost": -0.12, "aggression": 0.05,
        "jitter": 0.008, "pressure": 0.05, "guard": 0.9,
        "desc": "High guard, tight shell — you must open it up with setups.",
    },
    "pressure_fighter": {
        "label": "Pressure Fighter", "emoji": "🚀",
        "difficulty_boost": 0.08, "aggression": 0.85,
        "jitter": 0.03, "pressure": 0.35, "guard": 0.15,
        "desc": "Walks you down behind a busy jab — relentless forward pressure.",
    },
}

_BASE = Path(__file__).resolve().parent.parent
CONFIG_FILE = _BASE / "config" / "profiles.json"
PREF_FILE = _BASE / "data" / "preferences.json"


def _load_config() -> Dict[str, ProfileConfig]:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001
        return {}


# Merge the JSON config over the built-ins (config file wins for existing
# profiles, and may add new ones).
PROFILES: Dict[str, ProfileConfig] = {
    k: dict(v) for k, v in DEFAULT_PROFILES.items()
}
for name, cfg in _load_config().items():
    PROFILES[name] = {**DEFAULT_PROFILES.get(name, {}), **cfg}

PROFILE_NAMES = list(PROFILES.keys())


# ---- user preference persistence (JSON) ---------------------------------------
def save_profile_preference(profile: str) -> None:
    """Persist the user's last chosen profile for future sessions."""
    try:
        PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PREF_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_profile": profile}, f)
    except Exception:  # noqa: BLE001
        pass


def load_profile_preference() -> str:
    """Return the user's saved profile, or 'balanced' if none is stored."""
    try:
        with open(PREF_FILE, encoding="utf-8") as f:
            name = str(json.load(f).get("last_profile", "balanced"))
        return name if name in PROFILES else "balanced"
    except Exception:  # noqa: BLE001
        return "balanced"


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
    hip_mid = ((hip_l["y"] + hip_r["y"]) / 2) if (hip_l and hip_r) else 0.6
    guard_target = torso_top + (hip_mid - torso_top) * 0.28  # chin/upper chest

    for wr in (L_WRIST, R_WRIST):
        w = pt(wr)
        if w:
            w["y"] = _clamp(w["y"] * (1 - cfg["guard"]) + guard_target * cfg["guard"])
            if cfg["guard"] > 0.4:
                nose_x = nose["x"] if nose else 0.5
                w["x"] = _clamp(w["x"] + (nose_x - w["x"]) * (cfg["guard"] - 0.3))

    # ---- Pressure: ghost closes distance by drifting toward the athlete -------
    if cfg["pressure"] != 0:
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
        mx = 1.0 - k["x"]                       # mirror horizontally
        my = k["y"]
        jitter = (cfg["jitter"] + 0.03 * d * cfg["aggression"])
        jx = rng.gauss(0.0, jitter)
        jy = rng.gauss(0.0, jitter)
        opponent.append({"x": _clamp(mx + jx), "y": _clamp(my + jy), "score": 1.0})

    return _shape_pose(opponent, cfg)
