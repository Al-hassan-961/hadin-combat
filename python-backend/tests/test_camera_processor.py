# ---------------------------------------------------------------------------
# HADIN-COMBAT – test_camera_processor.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Unit tests for the camera_processor helpers.

These exercise real OpenCV behaviour (resize, JPEG decode/encode), so they are
skipped when OpenCV is not installed (e.g. the local cv2 shim is active).
"""

import cv2
import numpy as np
import pytest

if not hasattr(cv2, "VideoCapture"):  # real OpenCV exposes VideoCapture
    pytest.skip("real OpenCV not available; skipping cv2-dependent tests",
                allow_module_level=True)

from app.camera_processor import (  # noqa: E402
    COCO_BONES,
    decode_jpeg_frame,
    draw_skeleton,
    jpeg_bytes,
    preprocess_frame,
    scale_keypoints_to_frame,
)


def test_decode_jpeg_frame_roundtrip():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    blob = jpeg_bytes(frame)
    assert isinstance(blob, bytes) and len(blob) > 0

    decoded = decode_jpeg_frame(blob)
    assert decoded is not None
    assert decoded.shape == (240, 320, 3)


def test_decode_jpeg_frame_rejects_empty():
    assert decode_jpeg_frame(b"") is None
    assert decode_jpeg_frame(b"not-a-jpeg") is None


def test_preprocess_frame_shape():
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    tensor = preprocess_frame(frame, size=224)
    assert tensor.shape == (1, 3, 224, 224)
    assert tensor.dtype == np.float32
    # Normalized roughly around zero.
    assert -1.0 < float(np.mean(tensor)) < 1.0


def test_draw_skeleton_keypoints():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    kps = [{"x": 10.0 * i, "y": 20.0, "score": 0.9} for i in range(17)]
    out = draw_skeleton(frame, kps, conf_threshold=0.3)
    assert out.shape == frame.shape
    assert out is frame  # mutated in place


def test_scale_keypoints_to_frame():
    kps = [{"x": 0.5, "y": 0.25, "score": 1.0}]
    scaled = scale_keypoints_to_frame(kps, 320, 240, norm=True)
    assert scaled[0]["x"] == pytest.approx(160.0)
    assert scaled[0]["y"] == pytest.approx(60.0)


def test_coco_bones_are_valid_indices():
    for a, b in COCO_BONES:
        assert 0 <= a < 17
        assert 0 <= b < 17
