# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_video.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Tests for the offline video-analysis pipeline (synthetic frames, no video
file needed) and the summary builder."""

import itertools

import numpy as np
import pytest

from app.analytics import (build_session_summary, improvement_suggestions,
                           performance_score)
from app.video_analyzer import analyze_frames_iter, analyze_video_file, speed_band

W, H = 320, 240


def make_pose_px(moves=None):
    """17-keypoint pose in PIXEL coordinates (COCO layout, score 1)."""
    kps = []
    for i in range(17):
        y = int((0.05 + 0.055 * i) * H)
        kps.append({"x": float(W / 2), "y": float(min(H - 1, y)), "score": 1.0})
    for idx, (nx, ny) in (moves or {}).items():  # normalized overrides
        if 0 <= idx < 17:
            kps[idx] = {"x": float(nx * W), "y": float(ny * H), "score": 1.0}
    return kps


def jab_sequence(steps=10):
    """Base pose, then the left wrist drives down-outward (a jab), then base."""
    seq = []
    base = make_pose_px()
    seq += [base for _ in range(6)]
    for i in range(1, steps + 1):
        t = i / steps
        p = [dict(k) for k in base]
        p[9] = {"x": W * (0.5 + 0.12 * t), "y": H * (0.545 + 0.08 * t), "score": 1.0}
        seq.append(p)
    seq += [base for _ in range(20)]
    return seq


def test_analyze_frames_iter_detects_strike_and_builds_summary():
    poses = jab_sequence()
    counter = itertools.count()

    def pose_fn(frame):
        i = next(counter)
        return poses[i] if i < len(poses) else None

    frames = (np.zeros((H, W, 3), dtype=np.uint8) for _ in range(len(poses)))
    result = analyze_frames_iter(pose_fn, frames, fps=10, duration_hint=6.0)

    assert result["source"] == "video"
    # Gating: a handful of CONFIDENT strikes — never one-per-frame inflation.
    total = result["summary"]["total_strikes"]
    assert total >= 1
    assert total <= 15                       # 6s @ cooldown 0.35s ≈ max 17
    assert result["techniques"], "expected at least one technique counted"
    assert result["timeline"], "expected at least one timeline entry"
    for e in result["timeline"]:
        assert (e.get("confidence") or 0) >= 0.6   # only confident strikes shown
    assert result["timeline"][0]["t"] >= 0
    assert result["fatigue_curve"], "expected fatigue progression samples"


def test_strike_gate_cooldown_and_dedupe():
    from app.strike_detector import StrikeGate
    gate = StrikeGate(min_conf=0.6)
    d1 = {"type": "jab", "confidence": 0.8, "quality": 70}
    d2 = {"type": "cross", "confidence": 0.8, "quality": 70}
    assert gate.accept(0.0, d1, None) is True
    assert gate.accept(0.1, d1, None) is False       # cooldown
    assert gate.accept(0.5, d2, None) is True        # new type after cooldown


def test_strike_gate_low_confidence_rejected():
    from app.strike_detector import StrikeGate
    gate = StrikeGate(min_conf=0.6)
    low = {"type": "hook", "confidence": 0.4, "quality": 60}
    assert gate.pick([low]) is None                  # below 60% -> not a strike
    assert gate.accept(0.0, low, None) is False


def test_calibrate_thresholds_requires_data():
    from app.strike_detector import calibrate_thresholds
    import pytest
    with pytest.raises(ValueError):
        calibrate_thresholds([], [])
    th = calibrate_thresholds([1.0, 1.2, 0.9, 1.1, 1.0], [0.8, 0.85, 0.9, 0.8, 0.9])
    assert 0.25 <= th["min_speed"] <= 1.0
    assert th["min_conf"] >= 0.6


def test_speed_band_thresholds():
    assert speed_band(0.1) == "slow"
    assert speed_band(0.6) == "medium"
    assert speed_band(1.5) == "fast"


def test_analyze_video_file_missing_raises():
    with pytest.raises(IOError):
        analyze_video_file(lambda f: None, "/nonexistent/nope.mp4")


def test_build_session_summary_fields():
    s = build_session_summary(
        total_strikes=50, landed=40,
        counts={"jab": 25, "cross": 15, "hook": 10},
        avg_quality=82, tempo=1.4, reaction_s=0.8,
        final_fatigue=45, duration_s=180,
        fatigue_curve=[[0, 5], [60, 30], [120, 45]])
    assert s["accuracy_pct"] == 80
    assert s["most_used"] == "jab"
    assert 0 <= s["performance"] <= 100
    assert len(s["suggestions"]) <= 3
    assert len(s["fatigue_curve"]) == 3


def test_performance_and_suggestions():
    assert performance_score(1.0, 90, 2.0, 10) >= performance_score(0.2, 40, 0.2, 90)
    tips = improvement_suggestions("jab", 0.5, 70, 1.5, 60)
    assert any("clean-technique" in t or "rate" in t for t in tips)


def test_job_manager_unknown_job():
    from app.video_analyzer import VideoJobManager
    mgr = VideoJobManager(lambda f: None)
    job = mgr.get("does-not-exist")
    assert job["status"] == "missing"


def test_upload_allowed_extensions():
    from app.main import _ALLOWED_VIDEO_EXTS
    assert {".mp4", ".mov", ".avi"}.issubset(_ALLOWED_VIDEO_EXTS)
    assert ".exe" not in _ALLOWED_VIDEO_EXTS


def test_compose_summary_via_main_helpers():
    """Simulate the live-session archive path (quality_list -> landed/accuracy)."""
    from app.main import _compose_session_summary
    sess = {
        "started": __import__("time").time(),
        "frames": 100,
        "profile": "aggressive",
        "_strikes_seen": 10,
        "quality_list": [[85, 0.9], [90, 0.95], [40, 0.4], [75, 0.7]] * 2 + [[50, 0.5]],
        "fatigue_progression": [[0, 5], [30, 40], [60, 70]],
    }
    from app.coach import CoachEngine, MovementAnalyzer
    sess["coach"] = CoachEngine()
    sess["coach"].counts = {"jab": 6, "hook": 3, "front_kick": 1}
    sess["fatigue"] = type("F", (), {"score": lambda self: {"score": 70}})()
    s = _compose_session_summary("t1", sess)
    assert s["total_strikes"] == 10
    assert s["landed"] >= 6     # quality>=70 or conf>=0.6 entries
    assert s["accuracy_pct"] == round(100 * s["landed"] / 10)
    assert s["most_used"] == "jab"
    assert 0 <= s["performance"] <= 100
    assert s["source"] == "live"
