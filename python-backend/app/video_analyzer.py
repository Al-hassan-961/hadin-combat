# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/video_analyzer.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Offline video sparring analysis.
#
# Reuses the SAME per-frame pipeline as live sessions (movement detection,
# coaching stats and fatigue analytics) on a recorded video:
#   * analyse a video frame-by-frame with the active pose backend
#   * timeline of every detected technique with timestamps + confidence
#   * fatigue progression curve + full match summary
#   * background jobs with progress % so the UI can show a progress bar.
#
# The pipeline is split so it can be tested on synthetic frame iterators
# without real video files (analyze_frames_iter); analyze_video_file wraps
# cv2.VideoCapture for actual MP4/MOV/AVI uploads.
# ---------------------------------------------------------------------------
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from .analytics import FatigueTracker, build_session_summary
from .coach import (L_ANKLE, L_WRIST, R_ANKLE, R_WRIST, CoachEngine,
                    MovementAnalyzer, STRIKE_TYPES)

PoseFn = Callable[[Any], Optional[List[Dict[str, float]]]]

FATIGUE_SAMPLE_S = 0.5     # seconds between fatigue-curve samples
TARGET_FPS = 10            # analyse at ~10 fps regardless of source fps


def _norm(kps_px: List[Dict[str, float]], w: int, h: int):
    return [{"x": k["x"] / w, "y": k["y"] / h, "score": k.get("score", 1.0)}
            for k in kps_px]


def _mean_joint_disp(a: List[Dict[str, float]], b: List[Dict[str, float]],
                     joints: Sequence[int]) -> float:
    """Mean normalized displacement of selected joints between two poses."""
    d = 0.0
    n = 0
    for j in joints:
        if j < len(a) and j < len(b) and a[j].get("score", 0) >= 0.3 \
                and b[j].get("score", 0) >= 0.3:
            d += ((a[j]["x"] - b[j]["x"]) ** 2 + (a[j]["y"] - b[j]["y"]) ** 2) ** 0.5
            n += 1
    return d / n if n else 0.0


def speed_band(speed_per_s: float) -> str:
    """Classify normalized movement speed into slow/medium/fast."""
    if speed_per_s < 0.4:
        return "slow"
    if speed_per_s < 0.9:
        return "medium"
    return "fast"


class FramePipeline:
    """Reusable per-frame analysis pipeline (shared by live + video paths)."""

    def __init__(self) -> None:
        self.movement = MovementAnalyzer()
        self.coach = CoachEngine()
        self.fatigue = FatigueTracker()
        self._prev_pose: Optional[List[Dict[str, float]]] = None
        self._prev_total = 0
        self.speed_per_s = 0.0
        self.speed_band = "slow"
        self.fatigue_curve: List[List[float]] = []      # [t_s, score]
        self.timeline: List[Dict[str, Any]] = []        # per detected technique
        self.landed = 0
        self._t_last_fatigue = -1.0

    def step(self, kps_px: Optional[List[Dict[str, float]]],
             w: int, h: int, t_s: float, sample_fps: float = TARGET_FPS) -> None:
        norm = _norm(kps_px, w, h) if kps_px else None

        # Movement speed from wrist/ankle displacement (per second).
        if norm and self._prev_pose:
            disp = _mean_joint_disp(self._prev_pose, norm,
                                    (L_WRIST, R_WRIST, L_ANKLE, R_ANKLE))
            self.speed_per_s = disp * sample_fps
            self.speed_band = speed_band(self.speed_per_s)
        if norm:
            self._prev_pose = norm

        if norm:
            self.movement.push(norm)
            self.fatigue.observe_stance(norm)

        detections = self.movement.analyze()
        coach = self.coach.update(detections)

        # Feed each NEW strike to fatigue + timeline + landed counter.
        total = coach.get("total_strikes", 0)
        if total > self._prev_total:
            latest = coach.get("last")
            if latest:
                snap = (latest.get("confidence", 0.5) * 0.5 +
                        (latest.get("quality", 50) / 100.0) * 0.5)
                for _ in range(total - self._prev_total):
                    self.fatigue.observe_strike(snap, t_s)
                if latest.get("quality", 0) >= 70 or latest.get("confidence", 0) >= 0.6:
                    self.landed += 1
                self.timeline.append({
                    "t": round(t_s, 2),
                    "type": latest.get("type"),
                    "side": latest.get("side"),
                    "quality": latest.get("quality"),
                    "confidence": latest.get("confidence"),
                })
            self._prev_total = total

        # Fatigue curve sample.
        if t_s - self._t_last_fatigue >= FATIGUE_SAMPLE_S:
            self._t_last_fatigue = t_s
            self.fatigue_curve.append([round(t_s, 2), self.fatigue.score()["score"]])

    def summary(self, counts: Dict[str, int], duration_s: float,
                tempo: float, reaction_s: float) -> Dict[str, Any]:
        m = self.coach.metrics()
        final_fatigue = self.fatigue.score()["score"] if self.fatigue_curve else 0
        return build_session_summary(
            total_strikes=m["total_strikes"],
            landed=self.landed,
            counts=counts,
            avg_quality=m.get("avg_quality", 0),
            tempo=tempo or m.get("tempo_per_s", 0),
            reaction_s=reaction_s or m.get("reaction_s", 0),
            final_fatigue=final_fatigue,
            duration_s=duration_s,
            fatigue_curve=self.fatigue_curve,
        )


def analyze_frames_iter(pose_fn: PoseFn, frames: Iterator[Any],
                        fps: float, duration_hint: Optional[float] = None,
                        progress_cb: Optional[Callable[[float], None]] = None,
                        total_hint: Optional[int] = None) -> Dict[str, Any]:
    """Analyse an iterator of frames (BGR numpy arrays) with a pose function.

    `progress_cb(0..100)` is called periodically for the UI progress bar.
    """
    pipe = FramePipeline()
    stride = max(1, int(round(fps / TARGET_FPS)))
    t = 0.0
    step_s = 1.0 / TARGET_FPS
    seen = 0

    for i, frame in enumerate(frames):
        if frame is None:
            continue
        if i % stride != 0:
            continue
        seen += 1
        try:
            h, w = frame.shape[:2]
        except Exception:  # noqa: BLE001
            continue
        kps = None
        try:
            kps = pose_fn(frame)
        except Exception:  # noqa: BLE001
            kps = None
        pipe.step(kps, w, h, t)
        t += step_s
        if progress_cb and total_hint:
            progress_cb(min(100.0, (i + 1) / total_hint * 100))

    counts = pipe.coach.counts
    duration = duration_hint or t
    summary = pipe.summary(counts, duration, pipe.coach.metrics()["tempo_per_s"],
                           pipe.coach.metrics()["reaction_s"])
    return {
        "source": "video",
        "fps": fps,
        "duration_s": round(duration, 1),
        "frames_analysed": seen,
        "timeline": pipe.timeline,
        "fatigue_curve": pipe.fatigue_curve,
        "techniques": dict(counts),
        "summary": summary,
    }


def analyze_video_file(pose_fn: PoseFn, path: str,
                       progress_cb: Optional[Callable[[float], None]] = None,
                       on_frame: Optional[Callable[[int, int], None]] = None
                       ) -> Dict[str, Any]:
    """Analyse a video file (MP4/MOV/AVI) frame by frame via OpenCV."""
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or TARGET_FPS
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    def frames():
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame

    try:
        return analyze_frames_iter(pose_fn, frames(), fps,
                                   duration_hint=total / fps if total else None,
                                   progress_cb=progress_cb,
                                   total_hint=total or None)
    finally:
        cap.release()


class VideoJobManager:
    """Runs video analyses in the background with progress tracking."""

    def __init__(self, pose_fn: PoseFn) -> None:
        self._pose_fn = pose_fn
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, video_path: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "status": "queued", "progress": 0.0, "error": None, "result": None}
        thread = threading.Thread(target=self._worker,
                                  args=(job_id, video_path), daemon=True)
        thread.start()
        return job_id

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"status": "missing", "progress": 0}
            return dict(job)

    def prune(self, keep: int = 12) -> None:
        with self._lock:
            if len(self._jobs) > keep:
                for k in list(self._jobs)[:-keep]:
                    self._jobs.pop(k, None)

    def _worker(self, job_id: str, video_path: str) -> None:
        def progress(p: float) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job["progress"] = round(p, 1)
                    job["status"] = "processing"
        try:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "processing"
            result = analyze_video_file(self._pose_fn, video_path, progress_cb=progress)
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.update({"status": "done", "progress": 100.0,
                                "result": result})
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job.update({"status": "error", "error": str(exc)})
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass
