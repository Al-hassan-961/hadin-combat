# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/coach.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Movement detection + professional coaching engine.
#
# MovementAnalyzer runs kinematic analysis on the normalized pose stream and
# recognizes martial-arts techniques — basic (jab/cross/hook/uppercut,
# front/roundhouse kicks, knee raises, guard, stance) and complex (superman
# punch, spinning backfist, axe kick, question-mark kick) — each with a
# confidence score. It works with ANY pose backend (C++, MediaPipe or the
# OpenCV motion fallback) because it only needs the same COCO 17 keypoints.
#
# CoachEngine tracks session statistics (technique counts, quality, tempo)
# and produces actionable, coach-style advice.
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
                "front_kick", "roundhouse_kick", "knee_raise",
                "superman_punch", "spinning_backfist",
                "axe_kick", "question_mark_kick"}

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
    "superman_punch": [
        "Leap and drive the lead hand forward as the back leg extends behind you.",
        "Land light on your feet and snap back to your stance.",
        "Exhale sharply as the superman punch lands.",
    ],
    "spinning_backfist": [
        "Pivot the lead foot and rotate the hips before whipping the backfist around.",
        "Keep your eyes over your shoulder as you spin — don't lose your target.",
        "Stay balanced on the finish so you can follow up.",
    ],
    "axe_kick": [
        "Drive the leg straight up with control, then slam it down through the target.",
        "Keep your standing leg planted and your hands up.",
        "Don't let the axe kick turn into a crescent — bring it straight down.",
    ],
    "question_mark_kick": [
        "Show the front kick, then snap the shin across as a head kick at the last second.",
        "The feint is everything — sell the low kick before the high switch.",
        "Pivot on your support foot to get the shin across.",
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


def _score(kps: Sequence[Dict[str, float]], idx: int) -> float:
    if idx < 0 or idx >= len(kps):
        return 0.0
    return float(kps[idx].get("score", 0.0))


def _speed(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class _TorsoState:
    """Track torso lean and shoulder-line rotation over a pose window."""

    def __init__(self) -> None:
        self.lean = 1.0            # hip->nose vertical distance (normalized)
        self.lean_delta = 0.0      # change over window (neg = leaning forward)
        self.shoulder_flip = 0.0   # 1 if shoulders swapped sides
        self.spin = 0.0            # max shoulder-midpoint horizontal speed

    @staticmethod
    def compute(frames: List[List[Dict[str, float]]]) -> "_TorsoState":
        st = _TorsoState()
        if len(frames) < 3:
            return st
        def torso(first: List[Dict[str, float]]) -> Optional[float]:
            hip_l, hip_r = _pt(first, L_HIP), _pt(first, R_HIP)
            nose = _pt(first, NOSE)
            if nose and hip_l and hip_r:
                hy = (hip_l[1] + hip_r[1]) / 2
                return max(0.01, hy - nose[1])  # vertical gap
            return None
        t0 = torso(frames[0])
        t1 = torso(frames[-1])
        if t0 and t1:
            st.lean = t1
            st.lean_delta = (t1 - t0) / max(t0, 0.001)  # neg => leaning forward

        # Shoulder line: orientation + lateral sweep of the shoulder pair.
        def shoulders(f: List[Dict[str, float]]):
            sl, sr = _pt(f, L_SHOULDER), _pt(f, R_SHOULDER)
            if sl and sr:
                return sl, sr
            return None
        s0 = shoulders(frames[0])
        s1 = shoulders(frames[-1])
        if s0 and s1:
            sl0, sr0 = s0
            sl1, sr1 = s1
            # Did the labelled left/right shoulders cross (i.e. ~180deg turn)?
            if abs((sr0[0] - sl0[0])) > 1e-6:
                st.shoulder_flip = 1.0 if (sr1[0] - sl1[0]) * (sr0[0] - sl0[0]) < 0 else 0.0
            mid0 = ((sl0[0] + sr0[0]) / 2, (sl0[1] + sr0[1]) / 2)
            mid1 = ((sl1[0] + sr1[0]) / 2, (sl1[1] + sr1[1]) / 2)
            st.spin = _speed(mid0, mid1)
        return st


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
        torso = _TorsoState.compute(frames)
        detections.extend(self._detect_arms(frames))
        detections.extend(self._detect_legs(frames))
        detections.extend(self._detect_complex(frames, torso))
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
                   confidence: float = 0.75,
                   extra: Optional[List[str]] = None) -> Dict[str, Any]:
        notes = list(ADVICE.get(mtype, []))
        if extra:
            notes = extra + notes
        notes.append(QUALITY_NOTES[_band(quality)])
        return {"type": mtype, "side": side, "quality": round(quality),
                "confidence": round(min(1.0, max(0.0, confidence)), 2),
                "advice": notes[:3]}

    @staticmethod
    def _strike_quality(speed: float, extension: float) -> float:
        q = 45 + min(speed * 150, 32) + min(extension * 45, 20)
        return max(40, min(98, q))

    @staticmethod
    def _avg_score(frames: List[List[Dict[str, float]]]) -> float:
        scores = [k.get("score", 0.0) for f in frames for k in f]
        return sum(scores) / max(1, len(scores))

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
            conf = min(0.9, 0.5 + dist * 2.0)

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
            results.append(self._detection(mtype, side, quality, conf))
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
            conf = min(0.9, 0.45 + dist * 1.5)
            if dy <= -0.06 and abs(dx) < abs(dy) * 2:
                mtype = "front_kick" if dist > 0.13 else "knee_raise"
            elif abs(dx) >= 0.07 and abs(dy) < 0.09:
                mtype = "roundhouse_kick"
            else:
                mtype = "front_kick"
            hip_pt = _pt(frames[-1], hip)
            extension = _speed(last, hip_pt) if hip_pt else 0.0
            quality = self._strike_quality(dist, extension)
            results.append(self._detection(mtype, side, quality, conf))
        return results

    # ---- complex techniques -----------------------------------------------------
    def _detect_complex(self, frames: List[List[Dict[str, float]]],
                        torso: _TorsoState) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        base_conf = 0.5 + self._avg_score(frames) * 0.4  # reward reliable keypoints

        # ---- Superman punch: forward lean + both arms extend + a leg lifts ----
        if torso.lean_delta <= -0.12 and torso.lean < 0.55:
            both_wrists = (self._trajectory(frames, L_WRIST),
                           self._trajectory(frames, R_WRIST))
            if len(both_wrists[0]) >= 3 and len(both_wrists[1]) >= 3:
                ext_l = _speed(both_wrists[0][0], both_wrists[0][-1])
                ext_r = _speed(both_wrists[1][0], both_wrists[1][-1])
                if ext_l > 0.07 and ext_r > 0.07:
                    conf = min(0.95, base_conf + 0.2 + torso.lean * 0.5)
                    results.append(self._detection(
                        "superman_punch", "lead", 78, conf))

        # ---- Spinning backfist: torso rotates fast / shoulder flip + whip -----
        spin_arm = self._trajectory(frames, L_WRIST) + self._trajectory(frames, R_WRIST)
        if (torso.shoulder_flip >= 0.9 or torso.spin > 0.12) and len(spin_arm) >= 3:
            horiz = max(abs(p[0] - spin_arm[0][0]) for p in spin_arm[1:])
            if horiz > 0.12:
                conf = min(0.95, base_conf + 0.25 + min(0.3, torso.spin * 1.5))
                results.append(self._detection("spinning_backfist", "rear", 76, conf))

        # ---- Axe kick: ankle rises very high then drops fast ------------------
        for side, ank in {"left": L_ANKLE, "right": R_ANKLE}.items():
            traj = self._trajectory(frames, ank)
            if len(traj) < 4:
                continue
            y_min = min(p[1] for p in traj)
            i_min = min(range(len(traj)), key=lambda i: traj[i][1])
            if y_min <= 0.32 and i_min < len(traj) - 1:
                drop = traj[-1][1] - y_min
                if drop > 0.12:
                    conf = min(0.95, base_conf + 0.15 + min(0.3, drop * 1.5))
                    results.append(self._detection("axe_kick", side, 75, conf))

        # ---- Question-mark kick: ankle rises then sweeps laterally while up ----
        for side, ank in {"left": L_ANKLE, "right": R_ANKLE}.items():
            traj = self._trajectory(frames, ank)
            if len(traj) < 4:
                continue
            y_min = min(p[1] for p in traj)
            i_min = min(range(len(traj)), key=lambda i: traj[i][1])
            if y_min <= 0.4 and i_min < len(traj) - 1:
                tail = traj[i_min:]
                if len(tail) >= 2:
                    lat = abs(tail[-1][0] - tail[0][0])
                    stays_up = all(p[1] < 0.5 for p in tail)
                    if lat > 0.12 and stays_up:
                        conf = min(0.95, base_conf + 0.15 + min(0.3, lat * 1.5))
                        results.append(self._detection("question_mark_kick", side, 77, conf))
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
        # Session aggregates for the performance dashboard.
        self._qualities: List[float] = []
        self._intervals: List[float] = []

    def metrics(self) -> Dict[str, Any]:
        """Whole-session aggregate metrics for the performance dashboard."""
        avg_quality = (sum(self._qualities) / len(self._qualities)) \
            if self._qualities else 0.0
        reaction = (sum(self._intervals) / len(self._intervals)) \
            if self._intervals else 0.0
        return {
            "avg_quality": round(avg_quality),
            "reaction_s": round(reaction, 2),
            "tempo_per_s": round(self._last_tempo, 1),
            "total_strikes": self.total_strikes,
        }

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
                advice.append(d["advice"][0])

        if latest_strike:
            self.last = latest_strike
            self._qualities.append(float(latest_strike.get("quality", 0)))
            if len(self._strike_times) >= 2:
                prev = self._strike_times[-2]
                gap = now - prev
                if gap <= 4.0:
                    self._intervals.append(gap)
            idx = self._advice_idx.get(latest_strike["type"], 0)
            pool = ADVICE.get(latest_strike["type"], [])
            if pool:
                tip = pool[idx % len(pool)]
                advice.append(tip)
                self._advice_idx[latest_strike["type"]] = idx + 1

        if len(self._strike_times) >= 2:
            span = self._strike_times[-1] - self._strike_times[0]
            self._last_tempo = (len(self._strike_times) - 1) / max(span, 0.001)

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
                "confidence": self.last.get("confidence", 0.0),
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
        self._qualities.clear()
        self._intervals.clear()
        self._last_tempo = 0.0
