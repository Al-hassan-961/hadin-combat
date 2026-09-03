# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/stability.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Camera (phone) ego-motion detection.
#
# Rotating or moving the phone shifts the ENTIRE frame. When that happens the
# pose backend — and especially the OpenCV motion fallback, which uses MOG2
# background subtraction — mistakes the whole-frame change for athlete motion,
# synthesizing a wildly-moving skeleton that the coach then reads as "front
# kicks" and "hooks". The fix is to gate detection on camera stability: while
# the camera itself is moving we ignore detections entirely.
#
# CameraMotionDetector observes consecutive downscaled grayscale frames and
# reports whether the camera is effectively still. The key discriminator is
# the FRACTION of the frame that changed coherently: rotating the phone moves
# the whole background (large changed fraction, high global motion), whereas an
# athlete punching against a static background only changes the pixels they
# occupy (smaller fraction). A hysteresis + settle window prevents brief jolts
# from flapping the gate, and a separate "hold still to calibrate" helper
# confirms the camera is steady before analysis is trusted.
#
# This module is used by BOTH the live WebSocket path (app/main.py) and the
# offline video path (app/video_analyzer.py) so a shaky recording or a moving
# phone never produces phantom strikes.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Optional

try:
    from .camera_processor import cv2
except Exception:  # noqa: BLE001  (no OpenCV -> detector stays permissive)
    cv2 = None

# Downscaled working width for cheap per-frame analysis.
PROBE_W = 64
# Fraction of changed pixels above which we consider the WHOLE frame moving.
# (An athlete typically changes a minority of the frame; a phone rotation moves
# nearly all of it, including the background.)
MOVING_FRAC = 0.45
# Hysteresis: frames of calm required after motion before we call it stable.
SETTLE_FRAMES = 4
# How many "still" frames are needed to complete a hold-still calibration.
STILL_CALIBRATION_FRAMES = 24        # ~2s @ ~12fps
# Lower-bound mean abs-diff that also counts as motion (helps on textured bg).
MEAN_MOTION_THRESH = 8.0             # 0..255 grey scale


class CameraMotionDetector:
    """Detects whole-frame (camera) motion so detections can be suppressed.

    Pure image-difference based: no neural models, safe on a phone CPU.
    """

    def __init__(self, moving_frac: float = MOVING_FRAC,
                 settle_frames: int = SETTLE_FRAMES,
                 mean_thresh: float = MEAN_MOTION_THRESH) -> None:
        self.moving_frac = moving_frac
        self.settle_frames = settle_frames
        self.mean_thresh = mean_thresh
        self._prev: Optional[Any] = None
        self._calm = 0                  # consecutive calm frames
        self._motion = 0.0              # latest motion score (0..1)
        self._still_streak = 0          # frames camera has been still
        self.moving = False
        self._calibrated = False

    # ------------------------------------------------------------------ reset
    def reset(self) -> None:
        self._prev = None
        self._calm = 0
        self._motion = 0.0
        self._still_streak = 0
        self.moving = False
        self._calibrated = False

    # ----------------------------------------------------------------- observe
    def observe(self, frame: Any) -> bool:
        """Ingest one BGR frame; return True if the camera is STILL this frame."""
        if cv2 is None or frame is None:
            self._still_streak += 1
            return True
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            pw = PROBE_W
            ph = max(1, int(h * pw / max(1, w)))
            small = cv2.resize(gray, (pw, ph), interpolation=cv2.INTER_AREA)
        except Exception:  # noqa: BLE001
            return True   # can't measure -> don't block

        is_moving_now = False
        if self._prev is not None:
            diff = cv2.absdiff(self._prev, small)
            changed = float(cv2.countNonZero(cv2.threshold(
                diff, 6, 1, cv2.THRESH_BINARY)[1])) / (pw * ph)
            mean_d = float(cv2.mean(diff)[0])
            self._motion = min(1.0, max(changed / self.moving_frac,
                                        mean_d / (self.mean_thresh * 4)))
            is_moving_now = changed >= self.moving_frac \
                or mean_d >= self.mean_thresh
        self._prev = small

        if is_moving_now:
            self._calm = 0
            self._still_streak = 0
            self.moving = True
        else:
            self._calm += 1
            self._still_streak += 1
            # Hysteresis: only declare still after SETTLE_FRAMES of calm.
            if self._calm >= self.settle_frames:
                self.moving = False
        return not self.moving

    # -------------------------------------------------------------- accessors
    @property
    def still_frames(self) -> int:
        """How many consecutive frames the camera has been steady."""
        return self._still_streak if not self.moving else 0

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    def is_calibrated_still(self, required: int = STILL_CALIBRATION_FRAMES) -> bool:
        """True once the camera has been held still for `required` frames."""
        if not self._calibrated and self.still_frames >= required:
            self._calibrated = True
        return self._calibrated
