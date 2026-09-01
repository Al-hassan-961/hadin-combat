# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/main.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# FastAPI server:
#   - serves the HTML5 frontend
#   - exposes REST endpoints for stats/profile
#   - exposes a WebSocket /ws/{client_id} for real-time pose → opponent → feedback
#
# The AI pipeline is Python-first and ALWAYS functional:
#   - Pose:   C++ ONNX core → MediaPipe → OpenCV motion fallback → none
#   - Style:  C++ model (if ready) else PurePythonStyleEncoder
#   - Opponent:C++ model (if ready) else PurePythonOpponentGenerator
#   - Co-evol:C++ model (if ready) else PurePythonCoEvolution
# No C++ build and no ONNX models are required for the app to work.
# ---------------------------------------------------------------------------
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .camera_processor import (
    decode_jpeg_frame,
    draw_opponent,
    draw_skeleton,
    jpeg_bytes,
    scale_keypoints_to_frame,
)
from .engine import (
    MotionPoseEstimator,
    PurePythonCoEvolution,
    PurePythonOpponentGenerator,
    PurePythonStyleEncoder,
)

logger = logging.getLogger("hadin")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent
# Prefer the canonical frontend at the repo root /website; fall back to a
# local copy under python-backend/static (used when running standalone).
STATIC_DIR = REPO_DIR / "website" if (REPO_DIR / "website" / "index.html").exists() \
    else BASE_DIR / "static"
MODELS_DIR = BASE_DIR / "models"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USE_CPP_CORE = os.getenv("USE_CPP_CORE", "true").lower() in ("1", "true", "yes")
FALLBACK_TO_PYTHON = os.getenv("FALLBACK_TO_PYTHON", "true").lower() in (
    "1", "true", "yes")
OPPONENT_ADAPTATION = float(os.getenv("OPPONENT_ADAPTATION", "0.6"))

MODEL_PATHS = {
    "pose": Path(os.getenv("POSE_MODEL_PATH", MODELS_DIR / "pose.onnx")),
    "style": Path(os.getenv("STYLE_ENCODER_PATH", MODELS_DIR / "style_encoder.onnx")),
    "opponent": Path(os.getenv("OPPONENT_GENERATOR_PATH",
                               MODELS_DIR / "opponent_generator.onnx")),
    "coevolution": Path(os.getenv("COEVOLUTION_PATH", MODELS_DIR / "coevolution.onnx")),
}

app = FastAPI(
    title="HADIN-COMBAT",
    description="The AI Opponent That Learns Your Fighting DNA",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# AI Core: C++ optional, pure-Python guaranteed
# ---------------------------------------------------------------------------
class AICore:
    def __init__(self) -> None:
        self.backend = "none"
        self._cpp = None          # hadin_core module (or None)
        self._pose = None         # C++ PoseEstimator
        self._style = None        # C++ StyleEncoder
        self._opponent = None     # C++ OpponentGenerator
        self._coevolution = None  # C++ CoEvolution
        self._mp_pose = None      # MediaPipe Pose
        self._motion = None       # OpenCV motion fallback

        self._load_cpp_core()
        if self.backend == "none" and FALLBACK_TO_PYTHON:
            self._load_mediapipe()
        if self.backend == "none":
            self._load_motion()
        logger.info("HADIN: active backend = %s", self.backend)

    # ---- backend loading --------------------------------------------------
    def _load_cpp_core(self) -> None:
        if not USE_CPP_CORE:
            logger.info("USE_CPP_CORE=false – skipping C++ core load.")
            return
        try:
            import hadin_core  # type: ignore

            self._cpp = hadin_core
            self._pose = hadin_core.PoseEstimator(str(MODEL_PATHS["pose"]))
            self._style = hadin_core.StyleEncoder(str(MODEL_PATHS["style"]))
            self._opponent = hadin_core.OpponentGenerator(
                str(MODEL_PATHS["opponent"]))
            self._coevolution = hadin_core.CoEvolution(str(MODEL_PATHS["coevolution"]))
            if self._pose.is_ready():
                self.backend = "cpp"
                logger.info("HADIN: C++ ONNX core loaded (sub-50ms inference).")
            else:
                logger.warning("HADIN: C++ pose model not ready; will fall back.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("HADIN: C++ core load failed (%s). Falling back.", exc)
            self.backend = "none"

    def _load_mediapipe(self) -> None:
        try:
            import mediapipe as mp  # type: ignore

            self._mp_pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self.backend = "mediapipe"
            logger.info("HADIN: MediaPipe pose fallback active.")
        except Exception as exc:  # noqa: BLE001
            logger.error("HADIN: MediaPipe fallback unavailable (%s).", exc)
            self.backend = "none"

    def _load_motion(self) -> None:
        try:
            self._motion = MotionPoseEstimator()
            self.backend = "opencv"
            logger.warning("HADIN: OpenCV motion fallback active (degraded mode).")
        except Exception as exc:  # noqa: BLE001
            logger.error("HADIN: Motion fallback unavailable (%s).", exc)
            self.backend = "none"

    # ---- pose estimation ----------------------------------------------------
    def pose_keypoints(self, frame: np.ndarray) -> Optional[List[Dict[str, float]]]:
        """Return COCO-style keypoints [{"x","y","score"}] in raw pixels."""
        if self.backend == "cpp":
            return self._pose_cpp(frame)
        if self.backend == "mediapipe":
            return self._pose_mediapipe(frame)
        if self.backend == "opencv":
            return self._pose_motion(frame)
        return None

    def _pose_cpp(self, frame: np.ndarray) -> Optional[List[Dict[str, float]]]:
        from .camera_processor import preprocess_frame

        h, w = frame.shape[:2]
        tensor = preprocess_frame(frame).astype(np.float32)  # [1,3,224,224]
        result = self._pose.infer(tensor, 224, 224)          # numpy in, binding converts
        if not result:
            return None
        return [{"x": float(kp.x) * w, "y": float(kp.y) * h, "score": float(kp.score)}
                for kp in result.keypoints]

    def _pose_mediapipe(self, frame: np.ndarray) -> Optional[List[Dict[str, float]]]:
        import cv2

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self._mp_pose.process(rgb)
        if not res.pose_landmarks:
            return None
        return [{"x": float(lm.x) * w, "y": float(lm.y) * h,
                 "score": float(lm.visibility)}
                for lm in res.pose_landmarks.landmark]

    def _pose_motion(self, frame: np.ndarray) -> Optional[List[Dict[str, float]]]:
        return self._motion.pose_keypoints(frame)

    # ---- higher-level AI ------------------------------------------------------
    def style_from_buffer(self, pose_buffer) -> tuple[List[float], List[str]]:
        """Encode recent poses into a Fighting-DNA latent + tags."""
        if self.backend == "cpp" and self._style.is_ready():
            try:
                # Build sequence tensor [T, K*2] and ask the C++ encoder.
                seq = []
                for kps in pose_buffer:
                    flat = []
                    for k in kps[:17]:
                        flat.extend([k["x"], k["y"]])
                    if len(flat) < 34:
                        flat += [0.0] * (34 - len(flat))
                    seq.append(flat)
                if len(seq) > 0:
                    encs = self._style.encode([seq], len(seq))
                    if encs:
                        latent = list(encs[0].latent)
                        tags = list(encs[0].tags)
                        return latent, tags
            except Exception as exc:  # noqa: BLE001
                logger.warning("C++ style encoder failed (%s); using Python.", exc)
        return self._style_py.encode() if hasattr(self, "_style_py") else ([0.0] * 64, ["neutral"])

    def generate_opponent(self, athlete_pose: List[Dict[str, float]],
                          latent: List[float], difficulty: float) -> List[Dict[str, float]]:
        """Return a normalized opponent pose."""
        if self.backend == "cpp" and self._opponent.is_ready():
            try:
                op = self._opponent.generate(latent, difficulty)
                if op:
                    n = len(op.pose) // 2
                    return [{"x": float(op.pose[i * 2]),
                             "y": float(op.pose[i * 2 + 1]), "score": 1.0}
                            for i in range(n)]
            except Exception as exc:  # noqa: BLE001
                logger.warning("C++ opponent failed (%s); using Python.", exc)
        return self._opponent_py.generate(athlete_pose, difficulty)

    def coevolution_step(self, profile: Dict[str, Any], current: float) -> float:
        if self.backend == "cpp" and self._coevolution.is_ready():
            try:
                from .engine import PurePythonStyleEncoder  # latent source
                res = self._coevolution.step(profile, [0.0] * 64)
                if res:
                    return float(res[0])
            except Exception as exc:  # noqa: BLE001
                logger.warning("C++ co-evolution failed (%s); using Python.", exc)
        return self._coev_py.step(profile, current)


ai_core = AICore()
# Pure-Python engine instances live alongside the core for guaranteed operation.
ai_core._style_py = PurePythonStyleEncoder()
ai_core._opponent_py = PurePythonOpponentGenerator()
ai_core._coev_py = PurePythonCoEvolution()


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------
class SessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def create(self, client_id: str) -> None:
        self.sessions[client_id] = {
            "frames": 0,
            "started": time.time(),
            "difficulty": 0.4,
            "last_pose": [],
            "pose_buffer": [],     # recent normalized poses for style encoding
            "latent": [0.0] * 64,
            "style_tags": [],
        }

    def touch(self, client_id: str) -> Optional[Dict[str, Any]]:
        s = self.sessions.get(client_id)
        if s:
            s["frames"] += 1
        return s

    def stats(self, client_id: str) -> Dict[str, Any]:
        s = self.sessions.get(client_id, {})
        elapsed = max(1.0, time.time() - s.get("started", time.time()))
        return {
            "frames": s.get("frames", 0),
            "fps": round(s["frames"] / elapsed, 1),
            "difficulty": round(s.get("difficulty", 0.4), 2),
            "style_tags": s.get("style_tags", []),
        }

    def all_sessions(self) -> List[Dict[str, Any]]:
        return [{"client_id": k, **self.stats(k)} for k in self.sessions]


sessions = SessionManager()

# In-memory athlete profile (persist to Redis in production).
athlete_profile: Dict[str, Any] = {
    "athlete_id": "local",
    "total_sessions": 0,
    "total_rounds": 0,
    "win_rate": 0.5,
    "avg_response_ms": 0.0,
    "progress_score": 0.0,
}


# ---------------------------------------------------------------------------
# Feedback heuristic
# ---------------------------------------------------------------------------
def build_feedback(sess: Dict[str, Any], kps: List[Dict[str, float]]) -> Dict[str, Any]:
    notes = []
    if not kps:
        return {"grade": "C", "notes": ["Step into the frame fully."], "score": 0}

    shoulders = [k for i, k in enumerate(kps) if i in (5, 6) and k["score"] > 0.3]
    hips = [k for i, k in enumerate(kps) if i in (11, 12) and k["score"] > 0.3]
    if len(shoulders) == 2 and len(hips) == 2:
        sx = (shoulders[0]["x"] + shoulders[1]["x"]) / 2
        hx = (hips[0]["x"] + hips[1]["x"]) / 2
        shoulder_span = abs(shoulders[0]["x"] - shoulders[1]["x"])
        if shoulder_span > 1 and abs(sx - hx) / shoulder_span > 0.35:
            notes.append("Center your shoulders over your hips for better balance.")
        else:
            notes.append("Good alignment – stable base.")
    else:
        notes.append("Move fully into view so I can read your guard.")

    score = max(50, min(99, 70 + len(notes) * 5))
    grade = "A" if score >= 90 else "B" if score >= 80 else "C"
    return {"grade": grade, "notes": notes[:3] or ["Keep moving – stay active."],
            "score": score}


# ---------------------------------------------------------------------------
# Per-frame processing
# ---------------------------------------------------------------------------
async def process_frame(websocket: WebSocket, client_id: str,
                        sess: Dict[str, Any], frame: np.ndarray) -> None:
    t0 = time.perf_counter()
    h, w = frame.shape[:2]
    kps = ai_core.pose_keypoints(frame)

    if kps:
        sess["last_pose"] = kps
    draw_kps = kps or sess["last_pose"]

    # Update style fingerprint from normalized recent poses.
    if draw_kps:
        norm = [{"x": k["x"] / w, "y": k["y"] / h, "score": k["score"]}
                for k in draw_kps]
        ai_core._style_py.push(norm)
        sess["pose_buffer"] = list(ai_core._style_py._buffer)
        if len(sess["pose_buffer"]) >= 4:
            latent, tags = ai_core.style_from_buffer(sess["pose_buffer"])
            sess["latent"] = latent
            sess["style_tags"] = tags

    # Debug frame with skeleton overlay.
    debug = frame.copy()
    draw_skeleton(debug, draw_kps)

    # Co-evolution drives difficulty.
    sess["difficulty"] = ai_core.coevolution_step(athlete_profile,
                                                  sess["difficulty"])

    # Opponent generation (pure-Python reflex by default).
    norm_pose = [{"x": k["x"] / w, "y": k["y"] / h, "score": k["score"]}
                 for k in draw_kps] if draw_kps else []
    opponent = ai_core.generate_opponent(norm_pose, sess["latent"],
                                         sess["difficulty"])
    if opponent:
        opp_scaled = scale_keypoints_to_frame(opponent, w, h, norm=True)
        draw_opponent(debug, opp_scaled)

    feedback = build_feedback(sess, draw_kps)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    payload = {
        "type": "frame",
        "client_id": client_id,
        "keypoints": draw_kps,
        "opponent": opponent,
        "feedback": feedback,
        "difficulty": round(sess["difficulty"], 2),
        "latency_ms": round(latency_ms, 2),
        "backend": ai_core.backend,
        "debug_frame": base64.b64encode(jpeg_bytes(debug, 65)).decode("ascii"),
    }
    await websocket.send_json(payload)


async def handle_json(websocket: WebSocket, client_id: str, text: str) -> None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "message": "Bad JSON"})
        return

    msg_type = data.get("type")
    sess = sessions.sessions.get(client_id)
    if msg_type == "reset":
        if sess:
            sess["difficulty"] = 0.4
            sess["frames"] = 0
            sess["pose_buffer"] = []
            ai_core._style_py.reset()
        await websocket.send_json({"type": "reset_ack", "difficulty": 0.4})
    elif msg_type == "feedback_text":
        await websocket.send_json({"type": "feedback",
                                   "message": data.get("text", "")})
    else:
        await websocket.send_json({"type": "ack", "received": msg_type})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/stats")
async def api_stats() -> JSONResponse:
    return JSONResponse({
        "backend": ai_core.backend,
        "sessions": sessions.all_sessions(),
        "profile": athlete_profile,
        "latency_target_ms": 50 if ai_core.backend == "cpp" else 120,
    })


@app.websocket("/ws/{client_id}")
async def ws_endpoint(websocket: WebSocket, client_id: str) -> None:
    await websocket.accept()
    sessions.create(client_id)
    logger.info("WS connect: %s", client_id)
    try:
        await websocket.send_json({
            "type": "hello",
            "backend": ai_core.backend,
            "message": "HADIN-COMBAT ready. Begin your session.",
        })

        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                sess = sessions.touch(client_id)
                frame = decode_jpeg_frame(message["bytes"])
                if frame is None or sess is None:
                    continue
                await process_frame(websocket, client_id, sess, frame)

            elif "text" in message and message["text"]:
                await handle_json(websocket, client_id, message["text"])

    except WebSocketDisconnect:
        logger.info("WS disconnect: %s", client_id)
        sessions.sessions.pop(client_id, None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS error for %s: %s", client_id, exc)
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass


# Mount static assets when a local copy exists.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
