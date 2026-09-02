# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/strike_detector.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Strike gating & calibration.
#
# The raw detector is deliberately sensitive (it watches every joint). This
# module turns raw detections into CONFIDENT strikes by enforcing:
#   * confidence >= MIN_CONFIDENCE (0.6 = 60%) — below this a candidate is
#     marked "uncertain" and never counted;
#   * a refractory cooldown so one punch is not counted 10x across frames;
#   * same-type deduplication (a 2-frame jab is one jab, not two);
#   * an optional per-athlete minimum speed set by calibration.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .coach import STRIKE_TYPES

MIN_CONFIDENCE = 0.6        # 60% — only confident strikes are counted
UNCERTAIN_LO = 0.35         # below this: noise, discarded entirely
COOLDOWN_S = 0.35           # seconds between two accepted strikes
SAME_TYPE_WINDOW = 0.9      # same technique within this window = one strike


def confidence_state(conf: float) -> str:
    """human label: confident / uncertain / noise"""
    if conf >= MIN_CONFIDENCE:
        return "confident"
    if conf >= UNCERTAIN_LO:
        return "uncertain"
    return "noise"


class StrikeGate:
    """Accepts at most one strike per cooldown window, confident only."""

    def __init__(self, min_conf: float = MIN_CONFIDENCE,
                 cooldown: float = COOLDOWN_S,
                 min_speed: Optional[float] = None) -> None:
        self.min_conf = min_conf
        self.cooldown = cooldown
        self.min_speed = min_speed          # calibrated optional gate (per s)
        self._until = 0.0
        self._last_type: Optional[str] = None
        self._last_time = -1e9

    # ---- configuration -------------------------------------------------------
    def configure(self, min_conf: Optional[float] = None,
                  cooldown: Optional[float] = None,
                  min_speed: Optional[float] = None) -> None:
        if min_conf is not None:
            self.min_conf = min_conf
        if cooldown is not None:
            self.cooldown = cooldown
        if min_speed is not None:
            self.min_speed = min_speed

    def reset(self) -> None:
        self._until = 0.0
        self._last_type = None
        self._last_time = -1e9

    # ---- helpers ---------------------------------------------------------------
    def pick(self, detections: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Best confident strike candidate honoring this gate's min_conf."""
        best: Optional[Dict[str, Any]] = None
        best_score = -1.0
        for d in detections or []:
            if d.get("type") not in STRIKE_TYPES:
                continue
            conf = float(d.get("confidence", 0.0) or 0.0)
            if conf < self.min_conf:
                continue
            score = conf * 100 + float(d.get("quality", 0) or 0)
            if score > best_score:
                best_score = score
                best = d
        return best

    @staticmethod
    def best_candidate(detections: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Highest (confidence, quality) STRIKE detection, confident only."""
        best: Optional[Dict[str, Any]] = None
        best_score = -1.0
        for d in detections or []:
            if d.get("type") not in STRIKE_TYPES:
                continue
            conf = float(d.get("confidence", 0.0) or 0.0)
            if conf < MIN_CONFIDENCE:
                continue                       # uncertain/noise -> not a strike
            score = conf * 100 + float(d.get("quality", 0) or 0)
            if score > best_score:
                best_score = score
                best = d
        return best

    def accept(self, t: float, detection: Optional[Dict[str, Any]],
               speed_per_s: Optional[float] = None) -> bool:
        """Decision: is this detection a NEW countable strike at time t?"""
        if detection is None:
            return False
        if float(detection.get("confidence", 0) or 0) < self.min_conf:
            return False
        if speed_per_s is not None and self.min_speed is not None \
                and speed_per_s < self.min_speed:
            return False
        if t < self._until:                     # cooldown
            return False
        if detection["type"] == self._last_type \
                and (t - self._last_time) < SAME_TYPE_WINDOW:
            return False                        # duplicate of the same motion
        self._until = t + self.cooldown
        self._last_type = detection["type"]
        self._last_time = t
        return True


def calibrate_thresholds(speeds: List[float], confs: List[float],
                         target_fps: float = 10.0) -> Dict[str, float]:
    """Turn 3-5 clean calibration punches into personal gating thresholds.

    speeds: measured peak speeds (normalized displacement per second).
    """
    if not speeds or len(speeds) < 2:
        raise ValueError("calibration needs at least 2 clean punches")
    avg_speed = sum(speeds) / len(speeds)
    avg_conf = sum(confs) / len(confs)
    return {
        "min_speed": round(max(0.25, 0.6 * avg_speed), 3),
        "min_conf": round(max(MIN_CONFIDENCE, min(0.9, avg_conf * 0.9)), 2),
        "cooldown": COOLDOWN_S,
        "target_fps": target_fps,
    }
