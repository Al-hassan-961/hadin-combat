# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/fatigue.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Fatigue analysis engine.
#
# FatigueTracker watches three signals over the session and outputs a real-time
# fatigue score 0-100 with actionable recovery advice:
#   * snap/explosiveness decay  — technique speed & confidence drifting down
#   * reaction slowdown          — strike cadence (pause between attacks) rising
#   * stance stability loss      — shoulder-over-hip wobble increasing
# ---------------------------------------------------------------------------
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional

from .coach import L_HIP, L_SHOULDER, NOSE, R_HIP, R_SHOULDER, _pt, _speed

WARMUP_STRIKES = 5       # strikes needed to form the "fresh" baseline
SNAP_WINDOW = 8          # recent strikes used for the live mean
WOBBLE_WINDOW = 30       # recent stance samples
MAX_INTERVAL = 4.0       # seconds; longer gaps count as idle, not fatigue


def stance_wobble(kps) -> float:
    """Return how far the shoulder centre is off the hip centre (normalized)."""
    sl, sr = _pt(kps, L_SHOULDER), _pt(kps, R_SHOULDER)
    hl, hr = _pt(kps, L_HIP), _pt(kps, R_HIP)
    if not (sl and sr and hl and hr):
        return 0.0
    shoulder_w = abs(sl[0] - sr[0])
    if shoulder_w < 1e-4:
        return 0.0
    sx = (sl[0] + sr[0]) / 2
    hx = (hl[0] + hr[0]) / 2
    return min(1.0, abs(sx - hx) / shoulder_w)


class FatigueTracker:
    """Session-level fatigue estimation with recovery recommendations."""

    def __init__(self) -> None:
        self.started = time.time()
        self._snaps: Deque[float] = deque(maxlen=SNAP_WINDOW)
        self._snap_baseline: Optional[float] = None
        self._strike_ts: Deque[float] = deque(maxlen=12)
        self._intervals: Deque[float] = deque(maxlen=10)
        self._wobbles: Deque[float] = deque(maxlen=WOBBLE_WINDOW)
        self._wobble_baseline: Optional[float] = None
        self._last_score = 0.0

    def observe_strike(self, snap: float, now: Optional[float] = None) -> None:
        """Record a landed technique; snap ~ explosive speed (0..1)."""
        if now is None:
            now = time.time()
        self._snaps.append(max(0.0, min(1.0, snap)))
        if len(self._snaps) >= WARMUP_STRIKES and self._snap_baseline is None:
            self._snap_baseline = sum(list(self._snaps)) / len(self._snaps)
        if self._strike_ts:
            gap = now - self._strike_ts[-1]
            if gap <= MAX_INTERVAL:
                self._intervals.append(gap)
        self._strike_ts.append(now)

    def observe_stance(self, kps, now: Optional[float] = None) -> None:
        """Feed a pose so stance stability can be tracked."""
        self._wobbles.append(stance_wobble(kps))
        if len(self._wobbles) >= WOBBLE_WINDOW and self._wobble_baseline is None:
            self._wobble_baseline = sum(list(self._wobbles)) / len(self._wobbles)

    # ------------------------------------------------------------------ score --
    def _components(self) -> Dict[str, float]:
        snaps = list(self._snaps)
        intervals = list(self._intervals)
        wobbles = list(self._wobbles)

        # Explosiveness decay.
        snap_component = 0.0
        if self._snap_baseline and snaps:
            recent = sum(snaps) / len(snaps)
            snap_component = max(0.0, min(100.0, (1 - recent / max(self._snap_baseline, 1e-6)) * 100))

        # Reaction slowdown (cadence slowing => bigger gaps).
        react_component = 0.0
        if len(intervals) >= 3 and self._strike_ts:
            early = intervals[0] if len(intervals) > 1 else intervals[0]
            recent = sum(intervals) / len(intervals)
            if recent > early and early > 0:
                react_component = max(0.0, min(100.0, (recent / early - 1) * 100))
        elif len(self._strike_ts) < 3:
            react_component = 0.0

        # Stance instability.
        stab_component = 0.0
        if self._wobble_baseline is not None and wobbles:
            recent = sum(wobbles) / len(wobbles)
            stab_component = max(0.0, min(100.0, (recent / max(self._wobble_baseline, 1e-6) - 1) * 120))

        return {"snap": snap_component, "reaction": react_component,
                "stability": stab_component}

    def score(self) -> Dict[str, Any]:
        """Return fatigue 0-100 + per-component signals + recovery advice."""
        comps = self._components()
        strikes = len(self._strike_ts)
        # Fresh athletes start low; fatigue builds with activity.
        base = 8.0 if strikes >= 3 else 4.0
        if strikes < WARMUP_STRIKES and self._snap_baseline is None:
            # Not enough data yet — show low fatigue but note it's forming.
            self._last_score = min(20.0, base)
            return self._package(base, comps, warmup=True)

        # Weight: explosiveness 0.45, reaction 0.3, stability 0.25.
        fatigue = base + 0.45 * comps["snap"] + 0.30 * comps["reaction"] \
            + 0.25 * comps["stability"]
        fatigue = max(0.0, min(100.0, fatigue))
        self._last_score = fatigue
        return self._package(fatigue, comps, warmup=False)

    def _package(self, fatigue: float, comps: Dict[str, float],
                 warmup: bool) -> Dict[str, Any]:
        advice: List[str] = []
        if warmup:
            advice.append("Keep training — a few more exchanges and I'll calibrate your fresh baseline.")
        else:
            dominant = max(comps, key=lambda k: comps[k]) if max(comps.values()) > 12 else None
            if fatigue < 30:
                advice.append("You're fresh — this is the best window for quality technique work.")
            elif fatigue < 60:
                advice.append("Moderate fatigue: keep form strict, drop to ~80% power on the next rounds.")
            else:
                advice.append("High fatigue: protect your technique — slow down and prioritise clean form.")
            if dominant == "snap":
                advice.append("Your punches are losing snap — take a 30s breather and reset your posture.")
            elif dominant == "reaction":
                advice.append("Your reactions are slowing — drill simple combos on the pads to sharpen timing.")
            elif dominant == "stability":
                advice.append("Your stance is wobbling — brace your core and centre over your hips.")
        return {
            "score": round(fatigue),
            "level": "fresh" if fatigue < 30 else "moderate" if fatigue < 60 else "fatigued",
            "components": {k: round(v) for k, v in comps.items()},
            "advice": advice[:2],
        }

    def reset(self) -> None:
        self.__init__()
