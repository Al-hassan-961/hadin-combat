# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_e2e_websocket.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""End-to-end tests for the server.

* REST endpoints (/api/stats, /api/health) against a REAL uvicorn subprocess.
* WebSocket handler (ws_endpoint) exercised directly with a fake ASGI
  websocket (deterministic): hello -> frame -> feedback/opponent -> reset.

Requires a REAL OpenCV install (system or pip); skipped otherwise.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from _cv2shim import install  # noqa: E402

install()
try:
    import cv2  # noqa: F401

    if not hasattr(cv2, "VideoCapture"):
        raise ImportError  # cv2 shim active — requires real OpenCV
except Exception:  # noqa: BLE001
    pytest.skip("real OpenCV not available; skipping e2e test",
                allow_module_level=True)

from starlette.websockets import WebSocketDisconnect  # noqa: E402
from app.main import ai_core, ws_endpoint  # noqa: E402
from app import camera_processor as cp  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent

FRAME_BYTES: bytes = cp.jpeg_bytes(
    (lambda f: (f.__setitem__((slice(60, 180), slice(120, 200)), (200, 120, 60)) or f))(
        np.zeros((240, 320, 3), dtype=np.uint8)), 70)


# ---------------------------------------------------------------------------
# Real HTTP server (uvicorn subprocess)
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """Start uvicorn on a random port; yield the port."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(BACKEND_DIR),
        env=dict(os.environ, PORT=str(port)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"uvicorn exited early with code {proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.fail("server did not start in time")
        hd = time.time() + 30
        while time.time() < hd:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
        else:
            pytest.fail("server /api/health not ready")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _http_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.load(r)


def test_rest_stats(server):
    data = _http_json(server, "/api/stats")
    assert "backend" in data
    assert data["backend"] == "opencv"
    assert "sessions" in data


def test_health(server):
    data = _http_json(server, "/api/health")
    assert data["status"] == "ok"
    assert data["name"] == "hadin-combat"
    assert "version" in data
    assert data["backend"] == "opencv"


# ---------------------------------------------------------------------------
# WebSocket handler (direct, deterministic)
# ---------------------------------------------------------------------------
class FakeWebSocket:
    """Minimal stand-in for a Starlette WebSocket (ASGI message dicts)."""

    def __init__(self, incoming: list) -> None:
        self._incoming = list(incoming)
        self.sent: list = []

    @property
    def path_params(self) -> dict:
        return {"client_id": "unit-test"}

    async def accept(self) -> None:
        pass

    async def receive(self) -> dict:
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, data) -> None:
        self.sent.append(data)

    async def send_bytes(self, data) -> None:  # pragma: no cover
        self.sent.append({"type": "bytes", "bytes": data})

    async def close(self, code: int = 1000) -> None:
        pass


def _run_endpoint(incoming: list) -> list:
    ws = FakeWebSocket(incoming)
    asyncio.run(ws_endpoint(ws, client_id="unit-test"))
    return ws.sent


def test_websocket_hello_and_frame():
    sent = _run_endpoint([{"bytes": FRAME_BYTES}])
    hello = sent[0]
    assert hello["type"] == "hello"
    assert hello["backend"] == "opencv"

    frame = sent[1]
    assert frame["type"] == "frame"
    assert isinstance(frame["keypoints"], list) and len(frame["keypoints"]) == 17
    assert isinstance(frame["opponent"], list)
    assert "feedback" in frame
    assert "debug_frame" in frame
    assert frame["debug_frame"].startswith("/9j/")  # base64 JPEG


def test_websocket_reset():
    sent = _run_endpoint([
        {"bytes": FRAME_BYTES},
        {"text": json.dumps({"type": "reset"})},
    ])
    assert sent[0]["type"] == "hello"
    assert sent[1]["type"] == "frame"
    ack = sent[2]
    assert ack["type"] == "reset_ack"
    assert ack["difficulty"] == 0.4


def test_websocket_survives_consecutive_frames():
    sent = _run_endpoint([{"bytes": FRAME_BYTES} for _ in range(8)])
    assert sent[0]["type"] == "hello"
    for msg in sent[1:]:
        assert msg["type"] == "frame"
        assert isinstance(msg["keypoints"], list)
