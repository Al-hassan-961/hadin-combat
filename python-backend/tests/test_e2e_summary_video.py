# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_e2e_summary_video.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Live end-to-end: boots a REAL uvicorn server and exercises
#   1. the match-summary WebSocket flow (hello -> frame -> summary message),
#   2. the video-upload REST flow with a REAL MJPG-encoded .avi, polled to done
#      and confirmed archived in /api/history.
# Requires a real OpenCV; otherwise skipped (like test_e2e_websocket.py).
# ---------------------------------------------------------------------------
import json
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
        raise ImportError
except Exception:  # noqa: BLE001
    pytest.skip("real OpenCV not available; skipping e2e", allow_module_level=True)

from starlette.websockets import WebSocketDisconnect  # noqa: E402
from app.main import ws_endpoint  # noqa: E402
from app import camera_processor as cp  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(BACKEND_DIR),
        env=dict(__import__("os").environ, PORT=str(port)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        dl = time.time() + 30
        while time.time() < dl:
            if proc.poll() is not None:
                pytest.fail(f"uvicorn exited {proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.fail("server did not start")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _http(port, path, data=None, headers=None, method=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers or {},
        method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


# ---- match-summary WS flow -------------------------------------------------
class FakeWS:
    def __init__(self, incoming): self._incoming = list(incoming); self.sent = []
    @property
    def path_params(self): return {"client_id": "summary-test"}
    async def accept(self): pass
    async def receive(self):
        if self._incoming: return self._incoming.pop(0)
        raise WebSocketDisconnect()
    async def send_json(self, d): self.sent.append(d)
    async def send_bytes(self, d): self.sent.append({"type": "bytes", "bytes": d})
    async def close(self, code=1000): pass


def _mkjpeg():
    f = np.zeros((240, 320, 3), dtype=np.uint8)
    f[60:180, 120:200] = (200, 120, 60)
    return cp.jpeg_bytes(f, 70)


def test_match_summary_message_flow():
    ws = FakeWS([{"bytes": _mkjpeg()}, {"bytes": _mkjpeg()},
                 {"text": json.dumps({"type": "summary"})}])
    __import__("asyncio").run(ws_endpoint(ws, client_id="summary-test"))
    types = [s["type"] for s in ws.sent]
    assert types[0] == "hello"
    # There should be frames and finally a match_summary.
    assert "frame" in types
    assert "match_summary" in types
    summ = [s for s in ws.sent if s["type"] == "match_summary"][0]
    for field in ("total_strikes", "landed", "accuracy", "performance",
                  "reaction_s", "duration_s", "suggestions"):
        assert field in summ


# ---- real encoded video upload ---------------------------------------------
def test_video_upload_end_to_end(server):
    # Encode a real, short .avi with a visible moving blob (MJPG works here).
    out = BACKEND_DIR / "data" / "uploads" / "_e2e_motion.avi"
    out.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    x = 60
    for _ in range(20):                     # 2 seconds of motion
        f = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(f, (x, 60), (x + 40, 120), (200, 120, 60), -1)
        vw.write(f)
        x = (x + 6) % 280
    vw.release()
    with open(out, "rb") as fh:
        payload = fh.read()
    boundary = "----hadin-e2e"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"motion.avi\"\r\nContent-Type: video/x-msvideo\r\n\r\n").encode()
    body += payload + f"\r\n--{boundary}--\r\n".encode()
    status, resp = _http(server, "/api/analyze", data=body, method="POST",
                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert status == 200, resp
    job_id = json.loads(resp)["job_id"]
    # Poll to completion.
    res = None
    for _ in range(60):
        s, r = _http(server, f"/api/analyze/{job_id}")
        res = json.loads(r)
        if res["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert res["status"] == "done", res
    result = res["result"]
    assert result["engine"] == "gated-v2"
    assert result["summary"]["total_strikes"] <= 8 + int(
        result["duration_s"] * result["max_strikes_per_s"])
    # Confirm it was archived into HISTORY via /api/history.
    for _ in range(40):
        s, r = _http(server, "/api/history")
        hist = json.loads(r)["history"]
        if any(h.get("source") == "video" for h in hist):
            break
        time.sleep(0.5)
    else:
        pytest.fail("video result not archived in history")
    try:
        out.unlink()
    except OSError:
        pass
