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


def test_adversarial_noise_is_bounded():
    """Extreme frame-to-frame motion (worst-case jitter) can NEVER produce one
    strike per frame - the gate + hard cap keep totals physiologically sane."""
    poses_a = make_pose_px({9: (0.2, 0.2), 10: (0.8, 0.8)})
    poses_b = make_pose_px({9: (0.8, 0.8), 10: (0.2, 0.2)})
    frames = [np.zeros((H, W, 3), dtype=np.uint8) for _ in range(100)]  # 10s @10fps
    idx = [0]

    def pose_fn(frame):
        pose = poses_a if idx[0] % 2 == 0 else poses_b
        idx[0] += 1
        return pose

    result = analyze_frames_iter(pose_fn, iter(frames), fps=10, duration_hint=10.0)
    total = result["summary"]["total_strikes"]
    assert result["engine"] == "gated-v2"
    assert total <= 8 + int(10 * 4)          # hard cap = 48 max for 10 s
    assert total < 50
    assert "rate_limited" in result
    assert all((e.get("confidence") or 0) >= 0.6 for e in result["timeline"])


# ---------------------------------------------------------------------------
# Regression: ONE physical technique must be counted exactly ONCE.
# Before this fix an axe kick (which rises like a front kick, then drops) was
# reported as front_kick + axe_kick (and even repeated across sliding windows),
# and a superman punch as superman_punch + jab + hook. See strike_detector's
# _same_event (family dedupe) and FramePipeline's one-strike-per-run model.
# ---------------------------------------------------------------------------
def _run(frames, label=None):
    idx = [0]
    def pose_fn(frame):
        f = frames[idx[0]] if idx[0] < len(frames) else frames[-1]
        idx[0] += 1
        return f
    dur = len(frames) / 10.0
    return analyze_frames_iter(pose_fn,
                               iter([np.zeros((H, W, 3), dtype=np.uint8)
                                     for _ in frames]),
                               fps=10, duration_hint=dur)


def _base_px():
    return make_pose_px()


def _axe_motion(rest=22):
    """One continuous axe kick: ankle rises high, then slams straight down."""
    base = _base_px()
    fr = [base for _ in range(8)]
    for i in range(1, 6):
        p = [dict(k) for k in fr[-1]]
        p[16] = {"x": W * 0.5, "y": H * (0.5 - 0.4 * (i / 6)), "score": 1.0}
        fr.append(p)
    for i in range(1, 5):
        p = [dict(k) for k in fr[-1]]
        p[16] = {"x": W * 0.5, "y": H * (0.1 + 0.4 * (i / 5)), "score": 1.0}
        fr.append(p)
    fr += [base for _ in range(rest)]
    return fr


def _hook_motion(hand=9, rest=22):
    """One clean punch: wrist drives laterally out, holds, then returns."""
    base = _base_px()
    fr = [base for _ in range(6)]
    for i in range(1, 6):
        p = [dict(k) for k in fr[-1]]
        t = i / 6
        p[hand] = {"x": W * (0.5 + (0.25 * t if hand == 9 else -0.25 * t)),
                   "y": H * 0.51, "score": 1.0}
        fr.append(p)
    for _ in range(5):
        fr.append([dict(k) for k in fr[-1]])
    for i in range(1, 7):
        p = [dict(k) for k in fr[-1]]
        t = i / 7
        p[hand] = _base_px()[hand]
        fr.append(p)
    fr += [base for _ in range(rest)]
    return fr


def test_one_axe_kick_counts_once():
    res = _run(_axe_motion())
    assert res["summary"]["total_strikes"] == 1, res["timeline"]
    types = [e["type"] for e in res["timeline"]]
    assert types == ["axe_kick"], types          # NOT front_kick + axe_kick


def test_one_punch_counts_once():
    res = _run(_hook_motion())
    assert res["summary"]["total_strikes"] == 1, res["timeline"]
    # Every timeline entry must carry a confident strike type.
    assert all((e.get("confidence") or 0) >= 0.6 for e in res["timeline"])


def test_three_separate_punches_count_three():
    res = _run(_hook_motion(hand=9) + _hook_motion(hand=10) + _hook_motion(hand=9))
    assert res["summary"]["total_strikes"] == 3, res["timeline"]
    types = [e["type"] for e in res["timeline"]]
    assert types == ["hook", "cross", "hook"], types


def test_same_event_family_dedupe():
    from app.strike_detector import _same_event
    # An axe kick is also a front kick until the drop; superman also a punch.
    assert _same_event("front_kick", "axe_kick") is True
    assert _same_event("axe_kick", "front_kick") is True
    assert _same_event("jab", "superman_punch") is True
    # Genuinely different techniques are NOT the same event.
    assert _same_event("jab", "cross") is False
    assert _same_event("jab", "axe_kick") is False
