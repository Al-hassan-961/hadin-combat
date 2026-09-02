# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/_cv2shim.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Minimal `cv2` shim so the backend tests run without OpenCV installed.

On a real deployment (and in CI) OpenCV is installed from requirements.txt and
this shim is not needed; it exists only so tests are runnable on constrained
devices such as Termux.
"""
from __future__ import annotations

import sys
import types

import numpy as np

cv2 = types.ModuleType("cv2")
cv2.COLOR_BGR2RGB = 4
cv2.IMREAD_COLOR = 1
cv2.IMWRITE_JPEG_QUALITY = 95
cv2.FONT_HERSHEY_SIMPLEX = 0
cv2.INTER_AREA = 3
cv2.MORPH_OPEN = 2
cv2.MORPH_CLOSE = 3
cv2.MORPH_ELLIPSE = 2
cv2.RETR_EXTERNAL = 0
cv2.CHAIN_APPROX_SIMPLE = 2


def imdecode(buf, flags):
    # Faithful to real OpenCV: empty/invalid input returns None. Accepts either
    # raw bytes or a numpy uint8 buffer (camera_processor passes a buffer).
    data = np.frombuffer(buf, dtype=np.uint8) if not isinstance(buf, np.ndarray) else buf
    if data.size < 2 or not (data[0] == 0xFF and data[1] == 0xD8):
        return None
    return np.zeros((240, 320, 3), dtype=np.uint8)


def imencode(ext, img, params=None):
    return True, np.frombuffer(b"\xff\xd8fakejpeg\xff\xd9", dtype=np.uint8)


def cvtColor(img, code):
    return img


def resize(img, size, interpolation=None):
    return img


def line(*a, **k):
    pass


def circle(*a, **k):
    pass


def rectangle(*a, **k):
    pass


def putText(*a, **k):
    pass


def addWeighted(a, aw, b, bw, g, dst=None):
    if dst is None:
        return b
    dst[...] = b
    return dst


class _BGSub:
    def apply(self, frame):
        mask = np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)
        mask[60:180, 120:200] = 255
        return mask


def createBackgroundSubtractorMOG2(*a, **k):
    return _BGSub()


def morphologyEx(src, op, kernel):
    return src


def getStructuringElement(shape, ksize):
    return np.ones(ksize, dtype=np.uint8)


def findContours(mask, mode, method):
    pts = np.array([[120, 60], [200, 60], [200, 180], [120, 180]], dtype=np.int32)
    return ([pts], None)


def contourArea(c):
    return 10000.0


def countNonZero(mask):
    return int(np.count_nonzero(mask))


def boundingRect(c):
    x, y = int(c[:, 0].min()), int(c[:, 1].min())
    w = int(c[:, 0].max()) - x
    h = int(c[:, 1].max()) - y
    return x, y, w, h


cv2.imdecode = imdecode
cv2.imencode = imencode
cv2.cvtColor = cvtColor
cv2.resize = resize
cv2.line = line
cv2.circle = circle
cv2.rectangle = rectangle
cv2.putText = putText
cv2.addWeighted = addWeighted
cv2.createBackgroundSubtractorMOG2 = createBackgroundSubtractorMOG2
cv2.morphologyEx = morphologyEx
cv2.getStructuringElement = getStructuringElement
cv2.findContours = findContours
cv2.contourArea = contourArea
cv2.countNonZero = countNonZero
cv2.boundingRect = boundingRect


def install():
    """Install the shim (no-op if real cv2 is already available)."""
    try:
        import cv2 as _real  # noqa: F401

        return  # real OpenCV present
    except Exception:  # noqa: BLE001
        sys.modules["cv2"] = cv2
