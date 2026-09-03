# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/video_analyzer.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Offline video sparring analysis.
#
# Reuses the same per-frame pipeline as live sessions (movement detection,
# coaching stats and fatigue analytics) on a recorded video:
#   * analyse a video frame-by-frame with the active pose backend
#   * timeline of every CONFIDENT technique with timestamps + confidence
#   * fatigue progression curve + full match summary
#   * background jobs with progress % for the UI progress bar.
#
# Strike counting is gated (see app/strike_detector.py): only detections with
# confidence >= 60% pass the cooldown + dedupe gate, so one punch is counted
# once, not once per analysed frame. Reaction time is measured as the gap
# between movement onset (speed first rising) and the accepted strike.
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
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

from .analytics import (LANDED_CONFIDENCE, LANDED_QUALITY, FatigueTracker,
                        build_session_summary, is_landed)
from .coach import (COMPLEX_TYPES, L_ANKLE, L_WRIST, R_ANKLE, R_WRIST,
                    CoachEngine, MovementAnalyzer)
from .stability import CameraMotionDetector
from .strike_detector import StrikeGate, UNCERTAIN_LO, confidence_state

PoseFn = Callable[[Any], Optional[List[Dict[str, float]]]]

FATIGUE_SAMPLE_S = 0.5     # seconds between fatigue-curve samples
TARGET_FPS = 10            # analyse at ~10 fps regardless of source fps
ONSET_SPEED = 0.30         # speed (norm units / s) that marks a movement onset
SETTLE_SPEED = 0.15        # below this a burst has ended (one strike per burst)
MAX_BURST_S = 1.6          # longest a single continuous technique may last
QUIET_RUN_S = 0.45         # no detection for this long ends a technique run
MIN_STRIKE_GAP_S = 0.35    # min gap before a new technique can start
MAX_STRIKES_PER_SEC = 4.0  # hard physiological ceiling for the safety cap
UNCERTAIN_WINDOW = 0.5     # how long an 'uncertain' note stays visible


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
    """Reusable per-frame analysis pipeline (shared by live + video paths).

    Counts strikes through a StrikeGate so sensitivity/noise never inflates
    totals, and measures per-strike reaction time (onset -> accepted strike).
    """

    def __init__(self, calibration: Optional[Dict[str, float]] = None) -> None:
        self.movement = MovementAnalyzer()
        self.coach = CoachEngine()
        self.fatigue = FatigueTracker()
        self.gate = StrikeGate()
        self.cam = CameraMotionDetector()
        self.camera_stable = True
        self.camera_unstable_sec = 0.0
        if calibration:
            self.gate.configure(min_conf=calibration.get("min_conf"),
                                cooldown=calibration.get("cooldown"),
                                min_speed=calibration.get("min_speed"))
        self._prev_pose: Optional[List[Dict[str, float]]] = None
        self.speed_per_s = 0.0
        self.speed_band = "slow"
        self.fatigue_curve: List[List[float]] = []      # [t_s, score]
        self.timeline: List[Dict[str, Any]] = []        # accepted techniques
        self.uncertain: int = 0                         # suppressed <60% conf
        self.reaction_samples: List[float] = []         # onset->strike gaps
        self._t_last_fatigue = -1.0
        # ---- movement-episode state ------------------------------------------
        # One continuous run of confident detections = at most ONE accepted
        # strike. A rising ankle that then drops into an axe kick is a SINGLE
        # physical technique; it emits front_kick then axe_kick across frames,
        # so committing each windowed detection would count it 2-3x (the
        # original 677-strike over-count). We instead remember the best
        # (most-specific) candidate of a run and commit once the detections
        # fall quiet for QUIET_RUN_S.
        self._run: bool = False              # inside a detection run
        self._run_best: Optional[Dict[str, Any]] = None
        self._run_onset: Optional[float] = None
        self._run_last_det: float = -1.0
        self._last_strike_t: float = -1.0

    # ------------------------------------------------------------- per frame --
    @staticmethod
    def _prefer(probe: Dict[str, Any], incumbent: Optional[Dict[str, Any]]) -> bool:
        """Should `probe` replace `incumbent` as this run's best candidate?

        Complex techniques beat basic ones (an axe kick IS the whole motion,
        not a front kick); otherwise higher confidence + quality wins.
        """
        if incumbent is None:
            return True
        pc = probe.get("type") in COMPLEX_TYPES
        ic = incumbent.get("type") in COMPLEX_TYPES
        if pc != ic:
            return pc
        return (probe.get("confidence", 0) or 0) > (incumbent.get("confidence", 0) or 0)

    def _commit_strike(self, t_s: float) -> None:
        """Record the current run's best candidate as ONE accepted strike."""
        candidate = self._run_best
        self._run = False
        self._run_best = None
        onset = self._run_onset
        self._run_onset = None
        self._last_strike_t = t_s
        if candidate is None:
            return
        # Reaction = onset -> accepted strike.
        if onset is not None and t_s > onset:
            self.reaction_samples.append(
                min(1.5, max(0.05, round(t_s - onset, 2))))
        else:
            self.reaction_samples.append(-1.0)      # sentinel: not measured

        self.coach.update([candidate], now=t_s)
        # Fatigue "snap" from the ACTUAL measured speed.
        snap = min(1.0, self.speed_per_s / 2.0) if self.speed_per_s > 0.2 \
            else (float(candidate.get("confidence", 0.5)) * 0.5 +
                  (float(candidate.get("quality", 50)) / 100.0) * 0.5)
        self.fatigue.observe_strike(snap, t_s)
        self.timeline.append({
            "t": round(t_s, 2),
            "type": candidate.get("type"),
            "side": candidate.get("side"),
            "quality": candidate.get("quality"),
            "confidence": candidate.get("confidence"),
            "state": confidence_state(float(candidate.get("confidence", 0))),
        })

    def observe_camera(self, frame: Any, t_s: float) -> bool:
        """Feed one RAW BGR frame to the camera-motion gate.

        Returns True when the camera is stable (detections may be trusted).
        While the camera is moving we do NOT accumulate pose/movement so a
        shaky recording or a moving phone can never produce phantom strikes.
        """
        stable = self.cam.observe(frame)
        if self.camera_stable and not stable:
            # Camera just started moving -> drop any in-progress technique and
            # clear buffers so stale motion can't commit after movement ends.
            self._commit_abort()
            self.movement.reset()
            self._prev_pose = None
        self.camera_stable = stable
        if not stable:
            self.camera_unstable_sec += 0.1
        return stable

    def _commit_abort(self) -> None:
        """Discard an in-progress detection run without counting a strike."""
        self._run = False
        self._run_best = None
        self._run_onset = None
        self._run_last_det = -1.0

    def step(self, kps_px: Optional[List[Dict[str, float]]],
             w: int, h: int, t_s: float, sample_fps: float = TARGET_FPS) -> None:
        # While the camera is moving, ignore the pose entirely (see observe_camera).
        if not self.camera_stable:
            if t_s - self._t_last_fatigue >= FATIGUE_SAMPLE_S:
                self._t_last_fatigue = t_s
                self.fatigue_curve.append([round(t_s, 2),
                                           self.fatigue.score()["score"]])
            return
        norm = _norm(kps_px, w, h) if kps_px else None

        # Instantaneous speed from wrist/ankle displacement.
        if norm and self._prev_pose:
            disp = _mean_joint_disp(self._prev_pose, norm,
                                    (L_WRIST, R_WRIST, L_ANKLE, R_ANKLE))
            self.speed_per_s = disp * sample_fps
            self.speed_band = speed_band(self.speed_per_s)
        if norm:
            self._prev_pose = norm
            self.fatigue.observe_stance(norm)
            self.movement.push(norm)

        detections = self.movement.analyze()
        candidate = self.gate.pick(detections)

        # ---- one-strike-per-detection-run state machine ---------------------
        if candidate is not None:
            self._run_last_det = t_s
            if not self._run:
                # Start a new run only if the previous strike is old enough.
                if (t_s - self._last_strike_t) >= MIN_STRIKE_GAP_S:
                    self._run = True
                    self._run_onset = t_s
                    self._run_best = candidate
            elif self._prefer(candidate, self._run_best):
                self._run_best = candidate
        elif self._run and (t_s - self._run_last_det) > QUIET_RUN_S:
            # Detections have gone quiet long enough -> the technique finished.
            self._commit_strike(t_s)

        # Count suppressed near-misses for the debug report.
        if self._run_best is None and (candidate is not None or (detections and
                any(UNCERTAIN_LO <= float(d.get("confidence", 0)) < 0.6
                    for d in detections if d.get("type")))):
            for d in detections:
                if d.get("type") and d.get("type") not in ("guard", "stance"):
                    conf = float(d.get("confidence", 0))
                    if UNCERTAIN_LO <= conf < 0.6:
                        self.uncertain += 1
                        break

        # Fatigue progression curve.
        if t_s - self._t_last_fatigue >= FATIGUE_SAMPLE_S:
            self._t_last_fatigue = t_s
            self.fatigue_curve.append([round(t_s, 2), self.fatigue.score()["score"]])

    def _last_accepted_frame(self) -> float:
        """Time of the most recently accepted strike (or a very old sentinel)."""
        return getattr(self, "_last_strike_t", -1.0)

    # --------------------------------------------------------------- summary --
    def summary(self, counts: Dict[str, int], duration_s: float) -> Dict[str, Any]:
        m = self.coach.metrics()
        measured = [r for r in self.reaction_samples if r and r > 0]
        reaction = (sum(measured) / len(measured)) if measured else None
        final_fatigue = self.fatigue.score()["score"] if self.fatigue_curve else None
        # "Landed" = clean technique (quality >= LANDED_QUALITY OR confidence
        # >= LANDED_CONFIDENCE) — see analytics.is_landed.
        landed = sum(1 for e in self.timeline
                     if is_landed(e.get("quality"), e.get("confidence")))
        return build_session_summary(
            total_strikes=m["total_strikes"],
            landed=landed,
            counts=counts,
            avg_quality=m.get("avg_quality", 0),
            tempo=m.get("tempo_per_s", 0),
            reaction_s=reaction,
            final_fatigue=final_fatigue,
            duration_s=duration_s,
            fatigue_curve=self.fatigue_curve,
        )

    def debug_report(self) -> Dict[str, Any]:
        return {
            "uncertain_suppressed": self.uncertain,
            "reaction_samples": len(self.reaction_samples),
            "timeline_entries": len(self.timeline),
        }


def analyze_frames_iter(pose_fn: PoseFn, frames: Iterator[Any],
                        fps: float, duration_hint: Optional[float] = None,
                        progress_cb: Optional[Callable[[float], None]] = None,
                        total_hint: Optional[int] = None,
                        calibration: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Analyse an iterator of frames (BGR numpy arrays) with a pose function.

    `progress_cb(0..100)` is called periodically for the UI progress bar.
    """
    pipe = FramePipeline(calibration=calibration)
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
        pipe.observe_camera(frame, t)
        pipe.step(kps, w, h, t)
        t += step_s
        if progress_cb and total_hint:
            progress_cb(min(100.0, (i + 1) / total_hint * 100))

    counts = dict(pipe.coach.counts)
    duration = duration_hint or t
    timeline = list(pipe.timeline)

    # ---- HARD SAFETY CAP ----------------------------------------------------
    # Even a pathological input must never report absurd totals. A human can
    # realistically throw ~2-4 strikes/s; cap at 4/s with a small minimum, and
    # if we somehow exceed it, truncate + flag (never trust the detector more
    # than human physiology).
    cap = max(8, int(round(duration * MAX_STRIKES_PER_SEC)))
    rate_limited = len(timeline) > cap
    if rate_limited:
        timeline = timeline[:cap]
        # Rebuild counts from the kept timeline so totals always agree.
        counts = {}
        for e in timeline:
            counts[e["type"]] = counts.get(e["type"], 0) + 1

    measured = [r for r in pipe.reaction_samples if r and r > 0]
    reaction = (sum(measured) / len(measured)) if measured else None
    final_fatigue = pipe.fatigue.score()["score"] if pipe.fatigue_curve else None
    landed = sum(1 for e in timeline
                 if is_landed(e.get("quality"), e.get("confidence")))
    summary = build_session_summary(
        total_strikes=len(timeline), landed=landed, counts=counts,
        avg_quality=pipe.coach.metrics().get("avg_quality", 0),
        tempo=pipe.coach.metrics().get("tempo_per_s", 0),
        reaction_s=reaction, final_fatigue=final_fatigue,
        duration_s=duration, fatigue_curve=pipe.fatigue_curve)

    return {
        "source": "video",
        "engine": "gated-v2",                     # identifies the fixed engine
        "confidence_threshold": 0.6,              # strikes below this are dropped
        "max_strikes_per_s": MAX_STRIKES_PER_SEC,
        "rate_limited": rate_limited,
        "fps": fps,
        "duration_s": round(duration, 1),
        "frames_analysed": seen,
        "timeline": timeline,
        "fatigue_curve": pipe.fatigue_curve,
        "techniques": counts,
        "debug": pipe.debug_report(),
        "summary": summary,
    }


def analyze_video_file(pose_fn: PoseFn, path: str,
                       progress_cb: Optional[Callable[[float], None]] = None,
                       calibration: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
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
                                   total_hint=total or None,
                                   calibration=calibration)
    finally:
        cap.release()


class VideoJobManager:
    """Runs video analyses in the background with progress tracking."""

    def __init__(self, pose_fn: PoseFn) -> None:
        self._pose_fn = pose_fn
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, video_path: str,
               calibration: Optional[Dict[str, float]] = None) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "status": "queued", "progress": 0.0, "error": None, "result": None}
        thread = threading.Thread(target=self._worker,
                                  args=(job_id, video_path, calibration),
                                  daemon=True)
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

    def _worker(self, job_id: str, video_path: str,
                calibration: Optional[Dict[str, float]]) -> None:
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
            result = analyze_video_file(self._pose_fn, video_path,
                                        progress_cb=progress,
                                        calibration=calibration)
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
