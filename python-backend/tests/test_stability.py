# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_stability.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Camera / phone ego-motion detection tests. A moving phone shifts the WHOLE
# frame (textured background included); an athlete punching against a static
# camera changes only part of it. The gate must suppress detections while the
# camera moves and clear once it settles.
# ---------------------------------------------------------------------------
import numpy as np
import pytest

try:
    from app import stability as stab
    from app.stability import CameraMotionDetector
    from app.camera_processor import cv2
except Exception:  # noqa: BLE001
    pytest.skip("OpenCV unavailable; skipping stability tests", allow_module_level=True)


def base_scene(w=320, h=240, seed=1):
    """A static textured scene (background) with strong edges."""
    rng = np.random.RandomState(seed)
    img = rng.randint(40, 200, (h, w), dtype=np.uint8)
    img[50:110, 40:130] = 220
    img[90:130, 180:250] = 60
    img[150:190, 70:160] = 160
    return np.repeat(img[:, :, None], 3, axis=2)


def still_frame():
    """Identical textured frame (camera perfectly still)."""
    return base_scene()


def translate(base, dx, dy=0):
    """Translate the WHOLE scene by (dx, dy) -> simulates a camera pan/rotate."""
    h, w = base.shape[:2]
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(base, M, (w, h), borderMode=cv2.BORDER_REFLECT)


def test_static_camera_is_stable():
    det = CameraMotionDetector()
    det.observe(still_frame())
    for _ in range(8):
        assert det.observe(still_frame()) is True
    assert det.moving is False


def test_camera_pan_is_motion():
    det = CameraMotionDetector(moving_frac=0.45, settle_frames=3)
    det.observe(still_frame())
    # A progressive whole-frame pan: the whole background shifts each frame.
    flags = []
    for k in range(1, 9):
        flags.append(det.observe(translate(still_frame(), dx=k * 3)))
    assert det.moving is True
    assert not all(flags)          # at least some frames flagged as moving


def test_recovers_after_camera_settles():
    det = CameraMotionDetector(moving_frac=0.45, settle_frames=3)
    det.observe(still_frame())
    for k in range(1, 7):
        det.observe(translate(still_frame(), dx=k * 3))      # panning
    assert det.moving is True
    for _ in range(12):
        det.observe(still_frame())                            # hold still again
    assert det.moving is False


def test_hold_still_calibration():
    det = CameraMotionDetector(settle_frames=1)
    det.observe(still_frame())
    for _ in range(stab.STILL_CALIBRATION_FRAMES + 2):
        det.observe(still_frame())
    assert det.is_calibrated_still() is True
    assert det.calibrated is True


def test_localized_object_motion_stays_stable():
    """A bright object moving on a STATIC textured background (the athlete) must
    not be mistaken for camera motion."""
    det = CameraMotionDetector(moving_frac=0.5, settle_frames=2)
    base = base_scene()
    det.observe(base)
    x = 20
    for _ in range(12):
        f = base.copy()
        x = (x + 12) % 240
        f[120:170, x:x + 40] = 255          # small moving patch, bg static
        assert det.observe(f) is True
    assert det.moving is False
