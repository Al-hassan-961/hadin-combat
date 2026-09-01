# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_pipeline.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Integration test of the pure-Python AI pipeline (no FastAPI required).

This mirrors the data flow of app.main.process_frame using the real
engine + camera_processor modules: JPEG -> decode -> pose -> style ->
opponent -> co-evolution -> debug frame. It proves the server's per-frame
logic works end-to-end, which is what the WebSocket handler calls.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

from app import camera_processor as cp
from app.engine import (
    MotionPoseEstimator,
    PurePythonCoEvolution,
    PurePythonOpponentGenerator,
    PurePythonStyleEncoder,
)


@pytest.fixture
def synthetic_frame() -> np.ndarray:
    """A BGR frame with a bright subject blob in the center."""
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[60:180, 120:200] = (200, 120, 60)
    return frame


def _decode_ok():
    """Real OpenCV rejects non-JPEG; the shim does too. Return the decoder."""
    return cp.decode_jpeg_frame


def test_full_pipeline_chain(synthetic_frame):
    # JPEG encode -> decode roundtrip.
    jpeg = cp.jpeg_bytes(synthetic_frame, 65)
    assert jpeg.startswith(b"\xff\xd8")
    decoded = cp.decode_jpeg_frame(jpeg)
    assert decoded is not None and decoded.shape == synthetic_frame.shape
    h, w = decoded.shape[:2]

    # Pose via motion fallback (OpenCV background subtraction).
    est = MotionPoseEstimator()
    kps = est.pose_keypoints(decoded)
    assert kps and len(kps) == 17

    # Normalize + style fingerprint.
    norm = [{"x": k["x"] / w, "y": k["y"] / h, "score": k["score"]} for k in kps]
    style = PurePythonStyleEncoder(latent_dim=64, window=8)
    for _ in range(5):
        style.push(norm)
    latent, tags = style.encode()
    assert len(latent) == 64
    assert tags

    # Opponent (normalized) + scale to frame.
    opponent = PurePythonOpponentGenerator().generate(norm, 0.45)
    assert len(opponent) == 17
    opp_scaled = cp.scale_keypoints_to_frame(opponent, w, h, norm=True)
    assert all(0 <= p["x"] <= w and 0 <= p["y"] <= h for p in opp_scaled)

    # Co-evolution difficulty.
    d = PurePythonCoEvolution().step(
        {"win_rate": 0.8, "progress_score": 0.4, "total_sessions": 6}, 0.4)
    assert 0.0 <= d <= 1.0

    # Debug frame with both skeletons drawn + base64 payload (as the WS sends).
    debug = decoded.copy()
    cp.draw_skeleton(debug, kps)
    cp.draw_opponent(debug, opp_scaled)
    payload_b64 = base64.b64encode(cp.jpeg_bytes(debug, 65)).decode("ascii")
    assert payload_b64.startswith("/9j/")
