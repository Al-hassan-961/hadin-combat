# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/analytics.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Fatigue & performance analytics engine.
#
# FatigueTracker watches several signals over the session and outputs a
# real-time fatigue score 0-100 with actionable recovery recommendations:
#   * snap / explosiveness decay   — technique speed & confidence drifting down
#   * reaction slowdown            — strike cadence (pause between attacks) rising
#   * stance stability             — shoulder-over-hip alignment wobble, and
#                                    stance WIDTH becoming erratic over time
# ---------------------------------------------------------------------------
from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from .coach import (L_ANKLE, L_HIP, L_SHOULDER, R_ANKLE, R_HIP, R_SHOULDER,
                    _pt)

WARMUP_STRIKES = 5       # strikes needed to form the "fresh" baseline
SNAP_WINDOW = 8          # recent strikes used for the live mean
STANCE_WINDOW = 30       # recent stance samples
MAX_INTERVAL = 4.0       # seconds; longer gaps count as idle, not fatigue


def stance_wobble(kps) -> float:
    """How far the shoulder centre is off the hip centre (normalized)."""
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


def stance_width(kps) -> Optional[float]:
    """Ankle spread relative to shoulder width (a stable ratio in good form)."""
    sl, sr = _pt(kps, L_SHOULDER), _pt(kps, R_SHOULDER)
    al, ar = _pt(kps, L_ANKLE), _pt(kps, R_ANKLE)
    if not (sl and sr and al and ar):
        return None
    shoulder_w = abs(sl[0] - sr[0])
    if shoulder_w < 1e-4:
        return None
    return abs(al[0] - ar[0]) / shoulder_w


class FatigueTracker:
    """Session-level fatigue estimation with recovery recommendations."""

    def __init__(self) -> None:
        self.started = time.time()
        self._snaps: Deque[float] = deque(maxlen=SNAP_WINDOW)
        self._snap_baseline: Optional[float] = None
        self._strike_ts: Deque[float] = deque(maxlen=12)
        self._intervals: Deque[float] = deque(maxlen=10)
        self._wobbles: Deque[float] = deque(maxlen=STANCE_WINDOW)
        self._wobble_baseline: Optional[float] = None
        # Stance-width stability: the ratio's running variance.
        self._widths: Deque[float] = deque(maxlen=STANCE_WINDOW)
        self._width_baseline: Optional[float] = None
        self._last_score = 0.0

    # ------------------------------------------------------------- ingestion --
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
        """Feed a pose so stance alignment AND stance-width stability can be
        tracked over the session."""
        self._wobbles.append(stance_wobble(kps))
        w = stance_width(kps)
        if w is not None:
            self._widths.append(w)
            if len(self._widths) >= STANCE_WINDOW and self._width_baseline is None:
                self._width_baseline = sum(list(self._widths)) / len(self._widths)

    # ---------------------------------------------------------------- score --
    def _components(self) -> Dict[str, float]:
        snaps = list(self._snaps)
        intervals = list(self._intervals)
        wobbles = list(self._wobbles)

        # Explosiveness decay.
        snap_component = 0.0
        if self._snap_baseline and snaps:
            recent = sum(snaps) / len(snaps)
            snap_component = max(
                0.0, min(100.0, (1 - recent / max(self._snap_baseline, 1e-6)) * 100))

        # Reaction slowdown (cadence slowing => bigger gaps).
        react_component = 0.0
        if len(intervals) >= 3:
            early = intervals[0] if len(intervals) > 1 else intervals[0]
            recent = sum(intervals) / len(intervals)
            if recent > early and early > 0:
                react_component = max(
                    0.0, min(100.0, (recent / early - 1) * 100))

        # Stance alignment wobble.
        stab_component = 0.0
        if self._wobble_baseline is not None and wobbles:
            recent = sum(wobbles) / len(wobbles)
            stab_component = max(
                0.0, min(100.0, (recent / max(self._wobble_baseline, 1e-6) - 1) * 120))

        # Stance-WIDTH stability: erratic width (growing variance) = fatigue.
        width_component = 0.0
        if self._width_baseline is not None and len(self._widths) >= 6:
            widths = list(self._widths)
            recent_var = sum((x - self._width_baseline) ** 2 for x in widths) / len(widths)
            width_component = max(0.0, min(100.0, recent_var * 160))

        return {"snap": snap_component, "reaction": react_component,
                "stability": stab_component, "width": width_component}

    def score(self) -> Dict[str, Any]:
        """Return fatigue 0-100 + per-component signals + recovery advice."""
        comps = self._components()
        strikes = len(self._strike_ts)
        base = 8.0 if strikes >= 3 else 4.0
        if strikes < WARMUP_STRIKES and self._snap_baseline is None:
            # Not enough data yet — report low but note calibration.
            self._last_score = min(20.0, base)
            return self._package(base, comps, warmup=True)

        fatigue = (base
                   + 0.40 * comps["snap"]
                   + 0.25 * comps["reaction"]
                   + 0.15 * comps["stability"]
                   + 0.20 * comps["width"])
        fatigue = max(0.0, min(100.0, fatigue))
        self._last_score = fatigue
        return self._package(fatigue, comps, warmup=False)

    def _package(self, fatigue: float, comps: Dict[str, float],
                 warmup: bool) -> Dict[str, Any]:
        advice: List[str] = []
        if warmup:
            advice.append("Keep training — a few more exchanges and I'll calibrate "
                          "your fresh baseline.")
        else:
            dominant = max(comps, key=lambda k: comps[k]) if max(comps.values()) > 12 \
                else None
            if fatigue < 30:
                advice.append("You're fresh — this is the best window for quality "
                              "technique work.")
            elif fatigue < 60:
                advice.append("Moderate fatigue: keep form strict, drop to ~80% "
                              "power for the next rounds.")
            else:
                advice.append("Take a 30-second break: shake out your arms, breathe, "
                              "and re-centre your stance.")
            if dominant == "snap":
                advice.append("Your strikes are losing snap — take a 30-second break "
                              "and reset your posture before continuing.")
            elif dominant == "reaction":
                advice.append("Your reactions are slowing — rest 30s, then drill "
                              "simple combos to sharpen timing.")
            elif dominant == "stability":
                advice.append("Your stance is wobbling — brace your core and centre "
                              "over your hips.")
            elif dominant == "width":
                advice.append("Your stance width is becoming erratic — plant your "
                              "feet shoulder-width and stay grounded.")
        return {
            "score": round(fatigue),
            "level": "fresh" if fatigue < 30 else "moderate" if fatigue < 60 else "fatigued",
            "components": {k: round(v) for k, v in comps.items()},
            "advice": advice[:2],
        }

    def reset(self) -> None:
        self.__init__()
