# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/engine.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Pure-Python AI components that guarantee the FULL HADIN pipeline
# (Fighting-DNA style → opponent → co-evolution) works with only NumPy and
# OpenCV installed — no C++ core and no ONNX models required. When the C++
# core and its models are available, main.py prefers those; otherwise the
# engine below takes over so the app is always functional.
# ---------------------------------------------------------------------------
from __future__ import annotations

import math
import random
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

# COCO 17 skeleton landmarks used by the heuristics.
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16


def _pt(keypoints: Sequence[Dict[str, float]], idx: int) -> Optional[Tuple[float, float]]:
    """Return a valid (x, y) point for landmark idx, or None if missing."""
    if idx < 0 or idx >= len(keypoints):
        return None
    k = keypoints[idx]
    if k.get("score", 0.0) < 0.3:
        return None
    return (k["x"], k["y"])


# ---------------------------------------------------------------------------
# Fighting-DNA Style Encoder (pure Python)
# ---------------------------------------------------------------------------
class PurePythonStyleEncoder:
    """Encodes a short window of poses into a style latent + tendency tags.

    The latent is a fixed-size vector (default 64) whose leading entries
    encode interpretable style axes: energy, stance width and symmetry.
    """

    def __init__(self, latent_dim: int = 64, window: int = 12) -> None:
        self.latent_dim = latent_dim
        self.window = window
        self._buffer: Deque[List[Dict[str, float]]] = deque(maxlen=window)

    def push(self, keypoints: Sequence[Dict[str, float]]) -> None:
        """Store one normalized (0..1) pose frame."""
        norm = [
            {"x": max(0.0, min(1.0, k["x"])), "y": max(0.0, min(1.0, k["y"])),
             "score": k.get("score", 1.0)}
            for k in keypoints
        ]
        self._buffer.append(norm)

    def reset(self) -> None:
        self._buffer.clear()

    def encode(self) -> Tuple[List[float], List[str]]:
        if not self._buffer:
            return [0.0] * self.latent_dim, ["neutral"]

        frames = list(self._buffer)
        n = len(frames)

        # -- energy: mean frame-to-frame joint displacement -----------------
        energy = 0.0
        count = 0
        for a, b in zip(frames, frames[1:]):
            for i in range(min(len(a), len(b))):
                pa, pb = _pt(a, i), _pt(b, i)
                if pa and pb:
                    energy += math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                    count += 1
        energy = (energy / max(1, count)) if count else 0.0

        # -- stance width: shoulder/hip spread in the latest frame -----------
        latest = frames[-1]
        sh_l, sh_r = _pt(latest, L_SHOULDER), _pt(latest, R_SHOULDER)
        hip_l, hip_r = _pt(latest, L_HIP), _pt(latest, R_HIP)
        stance = 0.5
        symmetry = 0.5
        if sh_l and sh_r and hip_l and hip_r:
            sh_w = math.hypot(sh_l[0] - sh_r[0], sh_l[1] - sh_r[1])
            hip_w = math.hypot(hip_l[0] - hip_r[0], hip_l[1] - hip_r[1])
            stance = min(1.0, (hip_w / max(1e-4, sh_w)) * 0.7)
            cx = (sh_l[0] + sh_r[0]) / 2.0
            hip_cx = (hip_l[0] + hip_r[0]) / 2.0
            symmetry = 1.0 - min(1.0, abs(cx - hip_cx) * 3.0)

        # -- build latent -----------------------------------------------------
        latent = [0.0] * self.latent_dim
        latent[0] = energy                      # aggression / speed
        latent[1] = stance                      # grounded / mobile
        latent[2] = symmetry                    # technique / balance
        latent[3] = math.tanh(energy * 2.0)     # normalized energy
        # Deterministic-ish fingerprint from recent y-positions (identify the
        # athlete's habitual reach/level) so the latent is personal.
        reach = max((_pt(latest, i)[1] for i in (L_WRIST, R_WRIST)
                     if _pt(latest, i)), default=0.5)
        latent[4] = 1.0 - reach

        # -- tendency tags -----------------------------------------------------
        tags: List[str] = []
        if energy > 0.03:
            tags.append("aggressive")
        elif energy < 0.008:
            tags.append("patient")
        if stance < 0.35:
            tags.append("mobile")
        elif stance > 0.6:
            tags.append("grounded")
        if symmetry > 0.75:
            tags.append("balanced")
        tags.append("neutral" if not tags else "adaptive")
        return latent, tags[:4]


# ---------------------------------------------------------------------------
# Opponent Generator (pure Python)
# ---------------------------------------------------------------------------
class PurePythonOpponentGenerator:
    """Reflexive opponent that mirrors the athlete's pose and adds
    difficulty-scaled jitter. This makes the AI visibly responsive without
    any trained model."""

    def generate(self, athlete_pose: Sequence[Dict[str, float]],
                 difficulty: float) -> List[Dict[str, float]]:
        if not athlete_pose:
            return []
        d = max(0.0, min(1.0, difficulty))
        opponent = []
        for k in athlete_pose:
            if k.get("score", 0.0) < 0.3:
                opponent.append({"x": 0.5, "y": 0.5, "score": 0.0})
                continue
            # Mirror horizontally in normalized space.
            mx = 1.0 - k["x"]
            my = k["y"]
            # Add adaptive jitter; stronger opponent = more reactive offset.
            jx = random.gauss(0.0, 0.02 + 0.03 * d)
            jy = random.gauss(0.0, 0.02 + 0.03 * d)
            opponent.append({
                "x": max(0.0, min(1.0, mx + jx)),
                "y": max(0.0, min(1.0, my + jy)),
                "score": 1.0,
            })
        return opponent


# ---------------------------------------------------------------------------
# Co-Evolution (pure Python)
# ---------------------------------------------------------------------------
class PurePythonCoEvolution:
    """Adjusts the next difficulty from the athlete's long-term profile so
    the opponent keeps pace with (and slightly pushes) the athlete."""

    def step(self, profile: Dict[str, Any],
             current_difficulty: float) -> float:
        win_rate = float(profile.get("win_rate", 0.5))
        progress = float(profile.get("progress_score", 0.0))
        sessions = int(profile.get("total_sessions", 0))

        # Win often  -> harder. Improving -> harder. New -> start gentle.
        base = 0.4 + (win_rate - 0.5) * 0.6 + progress * 0.4
        # Small monotonic growth across sessions (co-evolution).
        growth = min(0.15, sessions * 0.005)
        # Blend, don't yank the difficulty up/down.
        target = max(0.05, min(0.95, base + growth))
        return current_difficulty + (target - current_difficulty) * 0.3


# ---------------------------------------------------------------------------
# Motion-based pose fallback (pure OpenCV, no models)
# ---------------------------------------------------------------------------
class MotionPoseEstimator:
    """Model-free pose fallback using background subtraction.

    Exists so the app still produces keypoints and feedback when neither the
    C++ core nor MediaPipe is available. To keep it fast on phones it runs on
    a half-resolution frame, and the synthesized skeleton is MOTION-AWARE:
    arm/leg positions react to where the foreground mass is (raised arms spread
    the shoulders, big lower-body mass widens the stance), and bbox movement
    adds swing — so the AI coach can still detect gross techniques.
    """

    def __init__(self, history: int = 120, var_threshold: int = 32) -> None:
        from .camera_processor import cv2

        self._cv2 = cv2
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=history, varThreshold=var_threshold, detectShadows=False)
        self._prev_center: Optional[Tuple[float, float]] = None

    def reset(self) -> None:
        self._prev_center = None

    def pose_keypoints(self, frame: Any) -> Optional[List[Dict[str, float]]]:
        cv2 = self._cv2
        h, w = frame.shape[:2]

        # ---- half-resolution background subtraction (CPU-friendly) ---------
        scale = 0.5
        sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
        small = cv2.resize(frame, (sw, sh))
        mask = self._bg.apply(small)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            self._prev_center = None
            return None
        big = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(big) < (sw * sh) * 0.01:
            self._prev_center = None
            return None

        x_s, y_s, bw_s, bh_s = cv2.boundingRect(big)

        # ---- foreground mass distribution (drives the skeleton) ------------
        x0, y0 = x_s, y_s
        x1 = min(sw, x_s + bw_s)
        y_mid = min(sh, y_s + max(1, bh_s // 2))
        y1 = min(sh, y_s + bh_s)
        upper = int(cv2.countNonZero(mask[y0:y_mid, x0:x1]))
        lower = int(cv2.countNonZero(mask[y_mid:y1, x0:x1]))
        total = upper + lower
        arm_factor = min(1.0, (upper / max(lower, 1)) * 1.1) if total else 0.35
        leg_factor = min(1.0, (lower / max(upper, 1)) * 0.9) if total else 0.5

        # ---- scale back to full frame ----------------------------------------
        xs = w / sw
        ys = h / sh
        x, y = x_s * xs, y_s * ys
        bw, bh = bw_s * xs, bh_s * ys
        cx = x + bw / 2.0
        top = y
        height = max(1.0, bh)

        # ---- bbox motion adds swing to the limbs (punch-like movement) -------
        swing = 0.0
        if self._prev_center is not None:
            dx = cx - self._prev_center[0]
            swing = min(0.12, abs(dx) * 0.5) * (1.0 if dx > 0 else -1.0)
        self._prev_center = (cx, top + height / 2)

        # ---- synthesize a 17-keypoint COCO skeleton ----------------------------
        def k(px: float, py: float) -> Dict[str, float]:
            return {"x": px, "y": py, "score": 0.7}

        shoulder_w = bw * 0.18
        arm_reach = 1.0 + 0.9 * arm_factor          # arms out when upper mass big
        wrist_lift = 0.40 - 0.10 * arm_factor       # wrists higher with raised arms
        ankle_spread = 0.7 + 0.45 * leg_factor      # wider stance with big lower mass

        def lw(off: float, fy: float) -> float:
            return cx + off * shoulder_w * arm_reach + swing

        pts = {
            NOSE: k(cx, top + height * 0.05),
            L_SHOULDER: k(cx - shoulder_w, top + height * 0.18),
            R_SHOULDER: k(cx + shoulder_w, top + height * 0.18),
            L_ELBOW: k(lw(-1.15, 0.32), top + height * 0.32),
            R_ELBOW: k(lw(1.15, 0.32), top + height * 0.32),
            L_WRIST: k(lw(-arm_reach, wrist_lift), top + height * wrist_lift),
            R_WRIST: k(lw(arm_reach, wrist_lift), top + height * wrist_lift),
            L_HIP: k(cx - shoulder_w * 0.8, top + height * 0.55),
            R_HIP: k(cx + shoulder_w * 0.8, top + height * 0.55),
            L_KNEE: k(cx - shoulder_w * 0.8, top + height * 0.74),
            R_KNEE: k(cx + shoulder_w * 0.8, top + height * 0.74),
            L_ANKLE: k(cx - shoulder_w * ankle_spread, top + height * 0.92),
            R_ANKLE: k(cx + shoulder_w * ankle_spread, top + height * 0.92),
        }
        return [pts.get(i, {"x": cx, "y": top + height / 2, "score": 0.0})
                for i in range(17)]
