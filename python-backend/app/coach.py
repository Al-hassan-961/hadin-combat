# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/coach.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Movement detection + professional coaching engine.
#
# MovementAnalyzer runs kinematic analysis on the normalized pose stream and
# recognizes martial-arts techniques (jab/cross/hook/uppercut, front/round
# kicks, knee raises, guard, stance). It works with ANY pose backend (C++,
# MediaPipe or the OpenCV motion fallback) because it only needs the same
# COCO 17 keypoints. CoachEngine tracks session statistics (technique counts,
# quality, tempo) and produces actionable, coach-style advice.
# ---------------------------------------------------------------------------
from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

# ---- COCO 17 landmark indices -----------------------------------------------
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

STRIKE_TYPES = {"jab", "cross", "hook", "uppercut",
                "front_kick", "roundhouse_kick"}

# Per-technique professional advice (rotated per repetition).
ADVICE: Dict[str, List[str]] = {
    "jab": [
        "Extend the jab fully, then snap it straight back to your guard.",
        "Keep your rear hand glued to your chin while you jab.",
        "Step in slightly with the jab to add reach and power.",
    ],
    "cross": [
        "Rotate your hips and rear foot into the cross — power comes from the ground.",
        "Don't drop your lead hand when you throw the cross.",
        "Exhale sharply as the cross lands.",
    ],
    "hook": [
        "Keep your elbow at 90° and pivot your rear foot as you swing.",
        "Swing through the target — don't slap at it.",
        "Turn your hips over to generate the hook's power.",
    ],
    "uppercut": [
        "Drive upward from your legs and keep your elbow tucked.",
        "Don't pull your lead hand back before throwing.",
        "Shorten the arc: the uppercut is compact and explosive.",
    ],
    "front_kick": [
        "Chamber the knee high, extend the shin, and snap it back.",
        "Keep both hands up in guard while you kick.",
        "Strike with the ball of your foot, not the toes.",
    ],
    "roundhouse_kick": [
        "Pivot on your support foot and turn your hip over for power.",
        "Keep your standing leg slightly bent so you stay balanced.",
        "Chamber the knee before extending the shin.",
    ],
    "knee_raise": [
        "Great knee drive — turn it into a strike by extending the shin.",
        "Stay tall: don't lean back when you lift the knee.",
    ],
    "block": [
        "Excellent defense — follow the block with an immediate counter.",
        "Keep your elbows tight so the block covers your ribs.",
    ],
    "guard": [
        "Nice guard — keep your chin tucked and elbows close.",
        "Keep your hands up even between attacks.",
    ],
    "stance": [
        "Widen your stance — feet roughly shoulder-width apart.",
        "Keep your knees soft and your weight on the balls of your feet.",
        "Center your shoulders over your hips to stay balanced.",
    ],
}

QUALITY_NOTES = {
    "low": "Keep the movement crisp and controlled — speed comes from clean technique.",
    "mid": "Good intention — tighten the range and add snap to the finish.",
    "high": "Excellent technique — keep that form, even when you're tired.",
}


def _band(quality: float) -> str:
    if quality < 60:
        return "low"
    if quality < 85:
        return "mid"
    return "high"


def _pt(kps: Sequence[Dict[str, float]], idx: int) -> Optional[Tuple[float, float]]:
    """Return a valid (x, y) point for landmark idx, or None if missing/low."""
    if idx < 0 or idx >= len(kps):
        return None
    k = kps[idx]
    if k.get("score", 0.0) < 0.3:
        return None
    return (k["x"], k["y"])


def _speed(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class MovementAnalyzer:
    """Detects martial-arts techniques from a rolling window of poses."""

    def __init__(self, window: int = 12) -> None:
        self.window = window
        self._buffer: Deque[List[Dict[str, float]]] = deque(maxlen=window)

    def push(self, kps: Sequence[Dict[str, float]]) -> None:
        self._buffer.append(list(kps))

    def reset(self) -> None:
        self._buffer.clear()

    def analyze(self) -> List[Dict[str, Any]]:
        detections: List[Dict[str, Any]] = []
        if len(self._buffer) < 4:
            return detections
        frames = list(self._buffer)
        detections.extend(self._detect_arms(frames))
        detections.extend(self._detect_legs(frames))
        detections.append(self._assess_stance(frames[-1]))
        return detections

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def _trajectory(frames: List[List[Dict[str, float]]], joint: int):
        traj = []
        for f in frames:
            p = _pt(f, joint)
            if p is not None:
                traj.append(p)
        return traj

    @staticmethod
    def _detection(mtype: str, side: str, quality: float,
                   extra: Optional[List[str]] = None) -> Dict[str, Any]:
        notes = list(ADVICE.get(mtype, []))
        if extra:
            notes = extra + notes
        notes.append(QUALITY_NOTES[_band(quality)])
        return {"type": mtype, "side": side, "quality": round(quality),
                "advice": notes[:3]}

    @staticmethod
    def _strike_quality(speed: float, extension: float) -> float:
        q = 45 + min(speed * 150, 32) + min(extension * 45, 20)
        return max(40, min(98, q))

    # ---- arms: punches + guard -------------------------------------------------
    def _detect_arms(self, frames: List[List[Dict[str, float]]]) -> List[Dict[str, Any]]:
        results = []
        for side, (sh, _el, wr) in {"left": (L_SHOULDER, L_ELBOW, L_WRIST),
                                    "right": (R_SHOULDER, R_ELBOW, R_WRIST)}.items():
            traj = self._trajectory(frames, wr)
            if len(traj) < 3:
                continue
            first, last = traj[0], traj[-1]
            dx = last[0] - first[0]
            dy = last[1] - first[1]
            dist = _speed(first, last)

            if dist < 0.05:
                # No strike: check guard (wrist held high near the face).
                shoulder = _pt(frames[-1], sh)
                if shoulder and last[1] < shoulder[1] - 0.08:
                    results.append(self._detection("guard", side, 72))
                continue

            if dy <= -0.045 and abs(dx) < abs(dy) * 1.6:
                mtype = "uppercut"
            elif abs(dx) >= 0.045 and abs(dy) < 0.06:
                mtype = "hook"
            else:
                mtype = "jab" if side == "left" else "cross"

            shoulder = _pt(frames[-1], sh)
            extension = 0.0
            if shoulder:
                extension = _speed(last, shoulder)
            quality = self._strike_quality(dist, extension)
            results.append(self._detection(mtype, side, quality))
        return results

    # ---- legs: kicks -------------------------------------------------------------
    def _detect_legs(self, frames: List[List[Dict[str, float]]]) -> List[Dict[str, Any]]:
        results = []
        for side, (hip, _kn, ank) in {"left": (L_HIP, L_KNEE, L_ANKLE),
                                      "right": (R_HIP, R_KNEE, R_ANKLE)}.items():
            traj = self._trajectory(frames, ank)
            if len(traj) < 3:
                continue
            first, last = traj[0], traj[-1]
            dx = last[0] - first[0]
            dy = last[1] - first[1]
            dist = _speed(first, last)
            if dist < 0.07:
                continue
            if dy <= -0.06 and abs(dx) < abs(dy) * 2:
                mtype = "front_kick" if dist > 0.13 else "knee_raise"
            elif abs(dx) >= 0.07 and abs(dy) < 0.09:
                mtype = "roundhouse_kick"
            else:
                mtype = "front_kick"
            hip_pt = _pt(frames[-1], hip)
            extension = _speed(last, hip_pt) if hip_pt else 0.0
            quality = self._strike_quality(dist, extension)
            results.append(self._detection(mtype, side, quality))
        return results

    # ---- stance / balance -----------------------------------------------------------
    def _assess_stance(self, kps: List[Dict[str, float]]) -> Dict[str, Any]:
        notes: List[str] = []
        sh_l, sh_r = _pt(kps, L_SHOULDER), _pt(kps, R_SHOULDER)
        an_l, an_r = _pt(kps, L_ANKLE), _pt(kps, R_ANKLE)
        hip_l, hip_r = _pt(kps, L_HIP), _pt(kps, R_HIP)

        if sh_l and sh_r and an_l and an_r:
            shoulder_w = abs(sh_l[0] - sh_r[0])
            stance_w = abs(an_l[0] - an_r[0])
            if shoulder_w > 0.02:
                ratio = stance_w / shoulder_w
                if ratio < 0.75:
                    notes.append("Widen your stance — feet should be about shoulder-width apart.")
                elif ratio > 1.7:
                    notes.append("Your stance is very wide — it may slow your footwork.")

        if hip_l and hip_r and sh_l and sh_r:
            sx = (sh_l[0] + sh_r[0]) / 2
            hx = (hip_l[0] + hip_r[0]) / 2
            if abs(sx - hx) / max(abs(sh_l[0] - sh_r[0]), 0.02) > 0.45:
                notes.append("Center your shoulders over your hips to stay balanced.")

        if not notes:
            notes.append("Your stance and balance look solid — stay light on your feet.")
        return self._detection("stance", "center", 75, extra=notes)


class CoachEngine:
    """Session-level coach: tracks technique counts, tempo and advice."""

    def __init__(self) -> None:
        self.counts: Dict[str, int] = {}
        self.last: Optional[Dict[str, Any]] = None
        self.total_strikes = 0
        self._strike_times: Deque[float] = deque(maxlen=8)
        self._advice_idx: Dict[str, int] = {}
        self._last_tempo = 0.0

    def update(self, detections: List[Dict[str, Any]],
               now: Optional[float] = None) -> Dict[str, Any]:
        if now is None:
            now = time.time()
        advice: List[str] = []
        latest_strike: Optional[Dict[str, Any]] = None

        for d in detections:
            t = d["type"]
            if t in STRIKE_TYPES:
                self.counts[t] = self.counts.get(t, 0) + 1
                self.total_strikes += 1
                self._strike_times.append(now)
                latest_strike = d
            elif d.get("advice"):
                # Guard / stance notes surface as general coach advice.
                advice.append(d["advice"][0])

        # Rotate technique-specific advice so it doesn't repeat every strike.
        if latest_strike:
            self.last = latest_strike
            idx = self._advice_idx.get(latest_strike["type"], 0)
            pool = ADVICE.get(latest_strike["type"], [])
            if pool:
                tip = pool[idx % len(pool)]
                advice.append(tip)
                self._advice_idx[latest_strike["type"]] = idx + 1

        # Tempo (strikes per second over the recent window).
        if len(self._strike_times) >= 2:
            span = self._strike_times[-1] - self._strike_times[0]
            self._last_tempo = (len(self._strike_times) - 1) / max(span, 0.001)

        # Milestone / combination coaching.
        if self.total_strikes and self.total_strikes % 3 == 0:
            advice.append("Nice rhythm — chain your strikes into combinations "
                          "(jab-cross, hook-kick).")
        if self.total_strikes == 10:
            advice.append("Great pace! Now add footwork angles between your attacks.")
        if self.total_strikes == 25:
            advice.append("You're in flow — mix levels: attack high, then go low.")

        last_payload = None
        if self.last:
            last_payload = {
                "type": self.last["type"],
                "side": self.last["side"],
                "quality": self.last["quality"],
                "advice": self.last.get("advice", []),
            }

        return {
            "last": last_payload,
            "counts": dict(self.counts),
            "total_strikes": self.total_strikes,
            "tempo_per_s": round(self._last_tempo, 1),
            "advice": advice[-3:],
        }

    def reset(self) -> None:
        self.counts.clear()
        self.last = None
        self.total_strikes = 0
        self._strike_times.clear()
        self._advice_idx.clear()
        self._last_tempo = 0.0
