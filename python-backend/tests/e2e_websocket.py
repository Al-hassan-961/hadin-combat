# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/e2e_websocket.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""End-to-end test of the FastAPI server + WebSocket pipeline.

Runs WITHOUT real OpenCV / MediaPipe / C++ by injecting a minimal `cv2` shim.
This proves the full server path (hello → frame → feedback/opponent) works and
that graceful degradation picks a usable backend.
"""
from __future__ import annotations

import sys

import pytest

# The e2e server test requires FastAPI/uvicorn. On platforms where their Rust
# deps (pydantic-core) have no wheel and can't be built, skip gracefully.
try:
    from fastapi.testclient import TestClient
except Exception:  # noqa: BLE001
    pytest.skip("FastAPI not available on this platform; skipping e2e test",
                allow_module_level=True)

# Install the cv2 shim BEFORE importing app modules (they import cv2 at load).
from _cv2shim import install  # noqa: E402

install()
sys.modules.setdefault("mediapipe", None)  # ensure mediapipe is absent

from app.main import app, ai_core  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_rest_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert "backend" in data
    assert data["backend"] == "opencv"
    assert "sessions" in data


def test_websocket_hello_and_frame(client):
    with client.websocket_connect("/ws/e2e-test") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["backend"] == "opencv"

        # Send a binary JPEG frame.
        ws.send_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
        frame = ws.receive_json()
        assert frame["type"] == "frame"
        # Motion fallback synthesizes keypoints.
        assert isinstance(frame["keypoints"], list) and len(frame["keypoints"]) == 17
        assert isinstance(frame["opponent"], list)
        assert "feedback" in frame
        assert "debug_frame" in frame
        assert frame["debug_frame"].startswith("/9j/")  # base64 JPEG

        # Reset via JSON control message.
        ws.send_text('{"type": "reset"}')
        ack = ws.receive_json()
        assert ack["type"] == "reset_ack"


def test_websocket_survives_consecutive_frames(client):
    with client.websocket_connect("/ws/e2e-style") as ws:
        ws.receive_json()  # hello
        for _ in range(8):
            ws.send_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
            msg = ws.receive_json()
            assert msg["type"] == "frame"
            assert isinstance(msg["keypoints"], list)
