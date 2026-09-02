# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_advanced.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Tests for complex-technique detection, fatigue analysis and sparring
profiles."""

from app.coach import MovementAnalyzer
from app.fatigue import FatigueTracker, stance_wobble
from app.profiles import build_opponent, difficulty_for, PROFILES


def make_pose(moves=None):
    kps = []
    for i in range(17):
        y = 0.05 + 0.055 * i
        kps.append({"x": 0.5, "y": min(0.95, y), "score": 1.0})
    for idx, (x, y) in (moves or {}).items():
        if 0 <= idx < 17:
            kps[idx] = {"x": x, "y": y, "score": 1.0}
    return kps


def feed_all(phases):
    """Push several pose phases through ONE analyzer (multi-phase motions)."""
    a = MovementAnalyzer(window=14)
    for phase in phases:
        for pose in phase:
            a.push(pose)
    return a.analyze()


def _phase(frames_to: dict, steps: int = 5):
    """A pose sequence interpolating given joint moves (list of move dicts)."""
    seq = []
    start = make_pose()
    cur = [dict(p) for p in start]
    for m in frames_to:
        target = [dict(p) for p in cur]
        for idx, (x, y) in m.items():
            target[idx] = {"x": x, "y": y, "score": 1.0}
        for i in range(1, steps + 1):
            t = i / steps
            out = [dict(p) for p in cur]
            for idx, mpos in m.items():
                sx, sy = cur[idx]["x"], cur[idx]["y"]
                out[idx] = {"x": sx + (mpos[0] - sx) * t,
                            "y": sy + (mpos[1] - sy) * t, "score": 1.0}
            seq.append(out)
        cur = target
    return seq


def motion(*moves, steps: int = 4):
    """A single continuous pose stream applying moves sequentially (multi-phase
    motions like axe kicks / question-mark kicks need one connected sequence)."""
    a = MovementAnalyzer(window=14)
    cur = make_pose()
    a.push(cur)
    for m in moves:
        for i in range(1, steps + 1):
            t = i / steps
            out = [dict(p) for p in cur]
            for idx, (x, y) in m.items():
                sx, sy = cur[idx]["x"], cur[idx]["y"]
                out[idx] = {"x": sx + (x - sx) * t,
                            "y": sy + (y - sy) * t, "score": 1.0}
            a.push(out)
            cur = [dict(p) for p in out]
    return a


def test_axe_kick_detected():
    # Right ankle (16) rises very high then slams straight down.
    dets = motion({16: (0.5, 0.14)}, {16: (0.5, 0.5)}).analyze()
    types = {d["type"] for d in dets}
    assert "axe_kick" in types


def test_question_mark_kick_detected():
    # Left ankle (15) rises, then sweeps laterally while staying high.
    dets = motion({15: (0.46, 0.30)}, {15: (0.20, 0.30)}).analyze()
    types = {d["type"] for d in dets}
    assert "question_mark_kick" in types


def test_detections_have_confidence():
    dets = motion({9: (0.30, 0.51)}).analyze()
    assert dets, "expected some detection"
    for d in dets:
        assert "confidence" in d
        assert 0.0 <= d["confidence"] <= 1.0


def test_fatigue_low_when_fresh():
    ft = FatigueTracker()
    kps = make_pose()
    t = 1000.0
    for _ in range(4):  # warmup, few strikes
        t += 0.5
        ft.observe_stance(kps)
        ft.observe_strike(0.8, t)
    assert ft.score()["score"] < 35


def test_fatigue_rises_with_speed_decay():
    ft = FatigueTracker()
    kps = make_pose()
    t = 1000.0
    for i in range(6):
        t += 0.5
        ft.observe_strike(0.85, t)          # fresh baseline
        ft.observe_stance(kps, t)
    for i in range(12):
        t += 0.5
        ft.observe_strike(0.28, t)          # speed drops sharply
        ft.observe_stance(kps, t)
    s = ft.score()
    assert s["score"] >= 30
    assert s["components"]["snap"] > 20
    assert s["advice"], "should give recovery advice when fatigued"


def test_stance_wobble():
    steady = make_pose()
    # shoulders shifted well off the hip centre -> detectable wobble
    off = make_pose({5: (0.38, 0.30), 6: (0.44, 0.30)})
    assert stance_wobble(off) > stance_wobble(steady)


def test_profiles_difficulty_bias():
    base = 0.5
    assert difficulty_for("aggressive", base) > base
    assert difficulty_for("defensive", base) < base
    assert difficulty_for("balanced", base) == base


def test_build_opponent_shapes_guard():
    pose = make_pose({5: (0.45, 0.25), 6: (0.55, 0.25),
                      9: (0.42, 0.6), 10: (0.58, 0.6)})  # hands low
    defensive = build_opponent(pose, "defensive", 0.5)
    balanced = build_opponent(pose, "balanced", 0.5)
    # Defensive raises wrists toward the chin (smaller y than balanced).
    assert defensive[9]["y"] < balanced[9]["y"]
    assert all(0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0
               for p in defensive)
    assert len(defensive) == 17


def test_opponent_empty_when_no_pose():
    assert build_opponent([], "aggressive", 0.5) == []
