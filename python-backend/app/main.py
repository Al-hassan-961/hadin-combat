# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/main.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Starlette/ASGI server (FastAPI-free on purpose):
#   - serves the HTML5 frontend
#   - exposes REST endpoints for stats/profile
#   - exposes a WebSocket /ws/{client_id} for real-time pose → opponent → feedback
#
# WHY STARLETTE INSTEAD OF FASTAPI:
#   FastAPI pulls in pydantic-core (Rust), which has no ARM64 wheel for
#   Python 3.14 and cannot be compiled on Android/Termux. Starlette provides
#   the same routing, WebSocket, FileResponse/JSONResponse and StaticFiles we
#   use, with ZERO compiled dependencies (pure-Python wheels) — so the whole
#   backend installs on Termux with no C/Rust compilation.
#
# The AI pipeline is Python-first and ALWAYS functional:
#   - Pose:   C++ ONNX core → MediaPipe → OpenCV motion fallback → none
#   - Style:  C++ model (if ready) else PurePythonStyleEncoder
#   - Opponent:C++ model (if ready) else PurePythonOpponentGenerator
#   - Co-evol:C++ model (if ready) else PurePythonCoEvolution
# No C++ build and no ONNX models are required for the app to work.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .camera_processor import (
    cv2_info,
    decode_jpeg_frame,
)
from .profiles import PROFILES, load_profile_preference
from .engine import (
    MotionPoseEstimator,
    PurePythonCoEvolution,
    PurePythonOpponentGenerator,
    PurePythonStyleEncoder,
)
from .coach import CoachEngine, MovementAnalyzer
from .analytics import (FatigueTracker, build_session_summary)
from .video_analyzer import (VideoJobManager, _mean_joint_disp, speed_band)
from .coach import L_ANKLE, L_WRIST, R_ANKLE, R_WRIST

logger = logging.getLogger("hadin")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

# Server process start time, used by the /api/health uptime field.
_START_TIME: float = time.time()

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

__version__ = "1.0.0"

# The Starlette application is assembled at the bottom of this module once
# all endpoint functions are defined (routes reference them).


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
        # Runtime watchdog state (graceful degradation / self-recovery).
        self._pose_misses = 0
        self._backend_errors = 0

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
        """Return COCO-style keypoints [{"x","y","score"}] in raw pixels.

        Never raises: on a backend error it degrades to the next available
        backend and continues; a long streak of misses resets the motion
        background model so the tracker can recover from drift.
        """
        kps: Optional[List[Dict[str, float]]] = None
        try:
            if self.backend == "cpp":
                kps = self._pose_cpp(frame)
            elif self.backend == "mediapipe":
                kps = self._pose_mediapipe(frame)
            elif self.backend == "opencv":
                kps = self._pose_motion(frame)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HADIN: pose backend error (%s) - degrading.", exc)
            kps = None
            self._backend_errors += 1
            self._degrade_if_stuck()

        if kps:
            self._pose_misses = 0
            return kps

        self._pose_misses += 1
        # Recover the motion fallback if it has drifted (e.g. background
        # changed or the subject left and returned).
        if self.backend == "opencv" and self._motion is not None \
                and self._pose_misses >= 25:
            logger.info("HADIN: resetting motion tracker to recover.")
            self._motion.reset()
            self._pose_misses = 0
        return None

    def _degrade_if_stuck(self) -> None:
        if self._backend_errors < 10:
            return
        if self.backend == "cpp" and self._mp_pose is not None:
            self.backend = "mediapipe"
        elif self.backend in ("cpp", "mediapipe") and self._motion is not None:
            self.backend = "opencv"
        elif self.backend == "opencv" and self._motion is not None:
            # Motion itself is failing; keep it but reset on the next miss.
            pass
        logger.warning("HADIN: degraded active backend to '%s'.", self.backend)
        self._backend_errors = 0

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
                          latent: List[float], difficulty: float,
                          profile: str = "balanced") -> List[Dict[str, float]]:
        """Return a normalized opponent pose shaped by the sparring profile."""
        from .profiles import build_opponent

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
        return build_opponent(athlete_pose, profile, difficulty)

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

# Offline video analysis jobs (background threads with progress).
video_jobs = VideoJobManager(ai_core.pose_keypoints)
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

# Live "rounds" for the timer HUD.
ROUND_SECONDS = 180     # 3-minute rounds
REST_SECONDS = 60       # 1-minute rest between rounds


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------
def _saved_profile() -> str:
    """The user's saved sparring profile (from data/preferences.json)."""
    try:
        return load_profile_preference()
    except Exception:  # noqa: BLE001
        return "balanced"
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
            "movement": MovementAnalyzer(),   # martial-arts movement detection
            "coach": CoachEngine(),           # session coaching stats + advice
            "fatigue": FatigueTracker(),      # fatigue score + recovery advice
            # Sparring-partner AI profile: start from the user's saved
            # preference (JSON), defaulting to "balanced".
            "profile": _saved_profile(),
            # Post-session summary / live-panel accumulators.
            "quality_list": [],          # (quality, confidence) per landed strike
            "fatigue_progression": [],   # [elapsed_s, fatigue_score] samples
            "_prev_norm": None,          # last normalized pose (speed calc)
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

# Completed-session summaries (bounded), for the performance dashboard.
HISTORY: List[Dict[str, Any]] = []
MAX_HISTORY = 20


def _compose_session_summary(client_id: str, sess: Dict[str, Any],
                             source: str = "live",
                             title: Optional[str] = None) -> Dict[str, Any]:
    """Build the full match-summary dict for a session (no history side-effects)."""
    coach = sess.get("coach")
    fatigue = sess.get("fatigue")
    counts = dict(getattr(coach, "counts", None) or {})
    try:
        fatigue_score = fatigue.score()["score"] if fatigue else 0
    except Exception:  # noqa: BLE001
        fatigue_score = 0
    duration = max(0.0, time.time() - sess.get("started", time.time()))
    try:
        m = coach.metrics() if coach else {}
    except Exception:  # noqa: BLE001
        m = {}
    total = sess.get("_strikes_seen", 0)
    quality_list = sess.get("quality_list") or []
    landed = sum(1 for q, c in quality_list if q >= 70 or c >= 0.6)

    summ = build_session_summary(
        total_strikes=total, landed=landed, counts=counts,
        avg_quality=m.get("avg_quality", 0),
        tempo=m.get("tempo_per_s", 0),
        reaction_s=m.get("reaction_s", 0.0),
        final_fatigue=fatigue_score,
        duration_s=duration,
        fatigue_curve=sess.get("fatigue_progression") or [],
    )
    return {
        "client_id": client_id,
        "source": source,
        "title": title or f"{source} session",
        "ended": round(time.time(), 1),
        "duration_s": round(duration),
        "frames": sess.get("frames", 0),
        "profile": sess.get("profile", "balanced"),
        "techniques": counts,
        "strikes_per_min": round((total / duration) * 60) if duration else 0,
        "fatigue": fatigue_score,
        **summ,
    }


def _record_history(client_id: str, sess: Optional[Dict[str, Any]],
                    source: str = "live", title: Optional[str] = None) -> None:
    """Save a full match summary of a finished session/video for the dashboard."""
    if not sess:
        return
    HISTORY.append(_compose_session_summary(client_id, sess, source, title))
    del HISTORY[:-MAX_HISTORY]

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
    movements: List[Dict[str, Any]] = []
    coach: Dict[str, Any] = {}
    if draw_kps:
        norm = [{"x": k["x"] / w, "y": k["y"] / h, "score": k["score"]}
                for k in draw_kps]
        ai_core._style_py.push(norm)
        sess["pose_buffer"] = list(ai_core._style_py._buffer)
        if len(sess["pose_buffer"]) >= 4:
            latent, tags = ai_core.style_from_buffer(sess["pose_buffer"])
            sess["latent"] = latent
            sess["style_tags"] = tags

        # Martial-arts movement detection + coaching.
        sess["movement"].push(norm)
        movements = sess["movement"].analyze()
        coach = sess["coach"].update(movements)

        # Movement speed (live-panel indicator): wrist/ankle displacement.
        prev_norm = sess.get("_prev_norm")
        speed_band_live = "slow"
        if prev_norm is not None:
            disp = _mean_joint_disp(prev_norm, norm,
                                    (L_WRIST, R_WRIST, L_ANKLE, R_ANKLE))
            speed_band_live = speed_band(disp * 10)   # ~10 sampled fps
        sess["_prev_norm"] = norm

        # Fatigue analysis: track stance stability each frame and feed each NEW
        # strike once with a "snap" proxy (confidence x quality ~ explosive speed).
        sess["fatigue"].observe_stance(norm)
        prev = sess.get("_strikes_seen", 0)
        total = coach.get("total_strikes", 0)
        if total > prev:
            latest = coach.get("last")
            if latest:
                snap = (latest.get("confidence", 0.5) * 0.5 +
                        (latest.get("quality", 50) / 100.0) * 0.5)
            else:
                snap = 0.6
            for _ in range(total - prev):
                sess["fatigue"].observe_strike(snap)
            if latest:
                sess.setdefault("quality_list", []).append(
                    [latest.get("quality", 0), latest.get("confidence", 0)])
            sess["_strikes_seen"] = total
    else:
        speed_band_live = "slow"
    fatigue = sess["fatigue"].score()

    # Fatigue progression curve (sampled ~every 12 frames) for the dashboard.
    if sess["frames"] % 12 == 0:
        elapsed_now = time.time() - sess.get("started", time.time())
        sess.setdefault("fatigue_progression", []).append(
            [round(elapsed_now, 1), fatigue["score"]])

    # Co-evolution drives difficulty; the sparring profile applies its own bias.
    from .profiles import difficulty_for

    sess["difficulty"] = difficulty_for(
        sess["profile"],
        ai_core.coevolution_step(athlete_profile, sess["difficulty"]))

    # Opponent generation, shaped by the selected sparring profile. Sent as
    # data only — the CLIENT draws the ghost overlay over the live video.
    norm_pose = [{"x": k["x"] / w, "y": k["y"] / h, "score": k["score"]}
                 for k in draw_kps] if draw_kps else []
    opponent = ai_core.generate_opponent(norm_pose, sess["latent"],
                                         sess["difficulty"],
                                         profile=sess["profile"])

    feedback = build_feedback(sess, draw_kps)
    # Merge the coach's advice into the feedback shown to the trainee.
    notes = list(coach.get("advice", []))
    if fatigue.get("advice"):
        notes += fatigue["advice"]
    if notes:
        feedback["notes"] = (notes + feedback.get("notes", []))[:3]
    latency_ms = (time.perf_counter() - t0) * 1000.0

    # ---- LIVE ANALYSIS payload (strike, fatigue, profile, round, speed,
    # ---- coaching tip and latest action summary for the live panel).
    elapsed = time.time() - sess.get("started", time.time())
    period = ROUND_SECONDS + REST_SECONDS
    phase = elapsed % period
    round_no = int(elapsed // period) + 1
    if phase <= ROUND_SECONDS:
        phase_label, remain = "round", ROUND_SECONDS - phase
    else:
        phase_label, remain = "rest", phase - ROUND_SECONDS

    strike = None
    latest = coach.get("last")
    if latest:
        strike = {"type": latest.get("type"), "side": latest.get("side"),
                  "confidence_pct": round((latest.get("confidence", 0) or 0) * 100),
                  "quality": latest.get("quality")}

    action = "Stay light on your feet — pick your moments."
    if strike:
        q = strike["quality"] or 0
        good = q >= 70
        action = f"{strike['type'].replace('_', ' ').title()} thrown — " + \
                 ("good form!" if good else "work on the extension.")
    elif fatigue["level"] == "fatigued":
        action = "Fatigue increasing — slow down and breathe."
    elif speed_band_live == "fast":
        action = "Moving fast — keep your guard up between strikes."

    tip = (notes[0] if notes else
           "Breathe, stay light, and keep your hands high.")

    analysis = {
        "strike": strike,
        "fatigue_score": fatigue["score"],
        "fatigue_level": fatigue["level"],
        "profile": PROFILES.get(sess["profile"], PROFILES["balanced"])["label"],
        "elapsed_s": round(elapsed, 1),
        "round": round_no,
        "phase": phase_label,
        "phase_remain": max(0, int(remain)),
        "speed_band": speed_band_live,
        "tip": tip,
        "action": action,
    }

    # NOTE: no debug frame is sent back — the browser draws the overlays on
    # the LIVE video element, which removes the JPEG round-trip entirely
    # (this was the main source of camera lag on phones).
    payload = {
        "type": "frame",
        "client_id": client_id,
        "keypoints": draw_kps,
        "opponent": opponent,
        "profile": PROFILES.get(sess["profile"], PROFILES["balanced"])["label"],
        "feedback": feedback,
        "movements": movements,
        "coach": coach,
        "fatigue": fatigue,
        "analysis": analysis,
        "difficulty": round(sess["difficulty"], 2),
        "latency_ms": round(latency_ms, 2),
        "backend": ai_core.backend,
    }
    # Debug aid: with HADIN_DEBUG=1 the server logs ~every 20th frame so you
    # can confirm analysis is being produced and sent (check uvicorn output).
    if os.getenv("HADIN_DEBUG") and sess["frames"] % 20 == 0:
        logger.info("frame#%s kps=%d analysis=yes fatigue=%s speed=%s backend=%s",
                    sess["frames"], len(draw_kps),
                    analysis["fatigue_score"], analysis["speed_band"], ai_core.backend)
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
            sess["movement"].reset()
            sess["coach"].reset()
            sess["fatigue"].reset()
            sess["_strikes_seen"] = 0
        await websocket.send_json({"type": "reset_ack", "difficulty": 0.4})
    elif msg_type == "set_profile":
        from .profiles import PROFILE_NAMES, save_profile_preference
        name = str(data.get("profile", ""))
        if name in PROFILE_NAMES and sess:
            sess["profile"] = name
            save_profile_preference(name)   # remember for future sessions (JSON)
            await websocket.send_json({"type": "profile_ack", "profile": name})
        else:
            await websocket.send_json({"type": "error", "message": f"Unknown profile: {name}"})
    elif msg_type == "summary":
        if sess:
            await websocket.send_json({
                "type": "match_summary",
                **_compose_session_summary(client_id, sess),
            })
    elif msg_type == "feedback_text":
        await websocket.send_json({"type": "feedback",
                                   "message": data.get("text", "")})
    else:
        await websocket.send_json({"type": "ack", "received": msg_type})


# ---------------------------------------------------------------------------
# Routes (endpoints; the Starlette routes are assembled at the bottom)
# ---------------------------------------------------------------------------
async def index(request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def api_health(request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "name": "hadin-combat",
        "version": __version__,
        "backend": ai_core.backend,
        "opencv": cv2_info(),
        "uptime_s": round(time.time() - _START_TIME, 1),
    })


async def api_stats(request) -> JSONResponse:
    return JSONResponse({
        "backend": ai_core.backend,
        "sessions": sessions.all_sessions(),
        "profile": athlete_profile,
        "profiles": {k: v["label"] for k, v in PROFILES.items()},
        "latency_target_ms": 50 if ai_core.backend == "cpp" else 120,
    })


async def api_history(request) -> JSONResponse:
    return JSONResponse({
        "history": list(HISTORY),
        "improvement": _improvement_suggestions(),
    })


def _improvement_suggestions() -> List[str]:
    """Derive personalized suggestions from recent session history."""
    if not HISTORY:
        return ["Complete a session to receive personalized improvement tips."]
    total = {"jab": 0, "cross": 0, "hook": 0, "uppercut": 0,
             "front_kick": 0, "roundhouse_kick": 0}
    best: Optional[Tuple[str, int]] = None
    for h in HISTORY:
        for t, c in (h.get("techniques") or {}).items():
            if t in total:
                total[t] += c
    for t, c in total.items():
        if c and (best is None or c > best[1]):
            best = (t, c)
    tips = []
    if best:
        tips.append(f"Your most-used technique is {best[0].replace('_', ' ')} "
                    f"({best[1]} reps) — drill it into sharper, faster reps.")
    avg_fatigue = sum(h.get("fatigue", 0) for h in HISTORY) / len(HISTORY)
    if avg_fatigue > 60:
        tips.append("Sessions end quite fatigued — add short breaks between rounds.")
    elif avg_fatigue < 30:
        tips.append("Push your intensity a little — your fatigue stays low.")
    if len(HISTORY) >= 2:
        tips.append("Try a different sparring profile (e.g. counter-puncher) to "
                    "develop your defence.")
    return tips[:3]


async def api_session(request) -> JSONResponse:
    """Live view of one active session (or the last matching history entry)."""
    client_id = request.path_params.get("client_id", "")
    sess = sessions.sessions.get(client_id)
    if sess:
        coach = sess.get("coach")
        fatigue = sess.get("fatigue")
        live = {
            "live": True,
            "profile": sess.get("profile"),
            "frames": sess.get("frames", 0),
            "difficulty": round(sess.get("difficulty", 0.4), 2),
            "techniques": dict(getattr(coach, "counts", None) or {}),
            "total_strikes": sess.get("_strikes_seen", 0),
            "style_tags": sess.get("style_tags", []),
        }
        try:
            live["fatigue"] = fatigue.score() if fatigue else {"score": 0}
        except Exception:  # noqa: BLE001
            live["fatigue"] = {"score": 0}
        return JSONResponse(live)
    for h in reversed(HISTORY):
        if h.get("client_id") == client_id:
            return JSONResponse({**h, "live": False})
    return JSONResponse({"live": False, "error": "session not found"}, status_code=404)


# Videos archived into HISTORY only once, when their job completes.
_archived_videos: set = set()
_ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


async def api_analyze_upload(request) -> JSONResponse:
    """Upload a sparring video for offline analysis -> {job_id}."""
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"bad form data: {exc}"}, status_code=400)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename") or not upload.filename:
        return JSONResponse({"error": "no file provided (field 'file')"}, status_code=400)

    ext = os.path.splitext(str(upload.filename))[1].lower()
    if ext not in _ALLOWED_VIDEO_EXTS:
        return JSONResponse(
            {"error": f"unsupported type '{ext}' — use MP4/MOV/AVI"},
            status_code=415)

    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOAD_DIR / f"upload_{int(time.time() * 1000)}{ext}"
        data = await upload.read()
        dest.write_bytes(data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("upload failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    job_id = video_jobs.submit(str(dest))
    return JSONResponse({"job_id": job_id, "filename": str(upload.filename)})


async def api_analyze_status(request) -> JSONResponse:
    """Poll analysis progress; on completion, archive the result in HISTORY."""
    job_id = request.path_params.get("job_id", "")
    job = video_jobs.get(job_id)
    if job["status"] == "done" and job_id not in _archived_videos:
        result = job.get("result") or {}
        summ = result.get("summary") or {}
        entry = {
            "client_id": f"video-{job_id}",
            "source": "video",
            "title": result.get("title", "Video analysis"),
            "ended": round(time.time(), 1),
            "duration_s": summ.get("duration_s", 0),
            "frames": result.get("frames_analysed", 0),
            "profile": summ.get("profile", "balanced"),
            "techniques": result.get("techniques") or {},
            "strikes_per_min": round(
                (summ.get("total_strikes", 0) / max(1, summ.get("duration_s", 1))) * 60),
            "fatigue": summ.get("final_fatigue", 0),
            **summ,
        }
        HISTORY.append(entry)
        del HISTORY[:-MAX_HISTORY]
        _archived_videos.add(job_id)
        video_jobs.prune()
    return JSONResponse(job)


async def ws_endpoint(websocket: WebSocket, **kwargs: Any) -> None:
    # Starlette >= 1.6 calls WebSocket endpoints with only the session; older
    # versions pass path params as kwargs. Read client_id from either source.
    client_id: str = str(
        kwargs.get("client_id") or websocket.path_params.get("client_id")
        or "anonymous"
    )
    await websocket.accept()
    sessions.create(client_id)
    logger.info("WS connect: %s", client_id)
    sess = sessions.sessions[client_id]
    try:
        await websocket.send_json({
            "type": "hello",
            "backend": ai_core.backend,
            "profile": sess["profile"],
            "profiles": list(PROFILES.keys()),
            "message": "HADIN-COMBAT ready. Begin your session.",
        })

        # Client keep-alive every 20s so proxies/timeouts don't drop the socket.
        async def _keepalive():
            try:
                while True:
                    await asyncio.sleep(20)
                    await websocket.send_json({"type": "ping", "t": time.time()})
            except Exception:  # noqa: BLE001
                return
        ka = asyncio.create_task(_keepalive())

        while True:
            message = await websocket.receive()

            try:  # isolate one bad frame/message so it can't kill the session
                if "bytes" in message and message["bytes"]:
                    sess = sessions.touch(client_id)
                    frame = decode_jpeg_frame(message["bytes"])
                    if frame is None or sess is None:
                        continue
                    await process_frame(websocket, client_id, sess, frame)
                elif "text" in message and message["text"]:
                    await handle_json(websocket, client_id, message["text"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("frame error for %s (continuing): %s", client_id, exc)

    except WebSocketDisconnect:
        logger.info("WS disconnect: %s", client_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WS error for %s: %s", client_id, exc)
    finally:
        try:
            ka.cancel()
        except Exception:  # noqa: BLE001
            pass
        _record_history(client_id, sessions.sessions.pop(client_id, None))


# ---- Starlette application (FastAPI-free: zero compiled dependencies) ----------
# NOTE: the frontend uses RELATIVE asset paths (css/style.css, js/app.js), so
# the static website must be served at the SITE ROOT, not under /static.
_routes = [
    Route("/", endpoint=index, methods=["GET"]),  # fallback index
    Route("/api/health", endpoint=api_health, methods=["GET"]),
    Route("/api/stats", endpoint=api_stats, methods=["GET"]),
    Route("/api/history", endpoint=api_history, methods=["GET"]),
    Route("/api/analyze", endpoint=api_analyze_upload, methods=["POST"]),
    Route("/api/analyze/{job_id}", endpoint=api_analyze_status, methods=["GET"]),
    Route("/api/session/{client_id}", endpoint=api_session, methods=["GET"]),
    WebSocketRoute("/ws/{client_id}", endpoint=ws_endpoint),
]
# Serve the website (index.html + css/js) at the root so relative asset
# paths resolve. html=True also serves index.html for "/".
if STATIC_DIR.exists():
    _routes.append(Mount("/", app=StaticFiles(directory=STATIC_DIR, html=True),
                         name="static"))

app = Starlette(routes=_routes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
