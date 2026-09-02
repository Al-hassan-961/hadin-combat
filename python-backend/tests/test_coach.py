# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_coach.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Unit tests for the martial-arts movement detector and coach engine."""

from app.coach import CoachEngine, MovementAnalyzer, STRIKE_TYPES


def make_pose(moves=None):
    """A 17-keypoint COCO pose in normalized coords; override joints by index."""
    kps = []
    for i in range(17):
        y = 0.05 + 0.055 * i  # rough body column (head at top)
        kps.append({"x": 0.5, "y": min(0.95, y), "score": 1.0})
    for idx, (x, y) in (moves or {}).items():
        if 0 <= idx < 17:
            kps[idx] = {"x": x, "y": y, "score": 1.0}
    return kps


def sequence(start: list, end: dict, steps: int = 6):
    """Return poses interpolating joints from start to end positions."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        pose = [dict(k) for k in start]
        for idx, (x0, y0) in end.items():
            x1, y1 = start[idx]["x"], start[idx]["y"]
            pose[idx] = {"x": x1 + (x0 - x1) * t, "y": y1 + (y0 - y1) * t,
                         "score": 1.0}
        out.append(pose)
    return out


def detect(*seqs):
    """Analyze each sequence with its own window; return the union of detections."""
    results = []
    for seq in seqs:
        a = MovementAnalyzer(window=14)
        for pose in seq:
            a.push(pose)
        results.extend(a.analyze())
    return results


def test_detects_jab_and_cross():
    base = make_pose()
    # Jab: left wrist (9) drives down-outward (dy > 0, big dx).
    jab = sequence(base, {9: (0.62, 0.62)})
    # Cross: right wrist (10) drives down-outward to the other side.
    cross = sequence(base, {10: (0.38, 0.68)})
    dets = detect(jab, cross)
    types = {d["type"] for d in dets}
    assert "jab" in types
    assert "cross" in types


def test_detects_hook_and_uppercut():
    base = make_pose()
    # Hook: left wrist (9) sweeps laterally (big dx, tiny dy).
    hook = sequence(base, {9: (0.32, 0.515)})
    # Uppercut: right wrist (10) shoots straight upward.
    uppercut = sequence(base, {10: (0.50, 0.35)})
    dets = detect(hook, uppercut)
    types = {d["type"] for d in dets}
    assert "hook" in types
    assert "uppercut" in types


def test_detects_front_and_roundhouse_kick():
    base = make_pose()
    # Front kick: right ankle (16) rises sharply upward.
    front = sequence(base, {16: (0.52, 0.45)})
    # Roundhouse: left ankle (15) swings wide laterally at hip height.
    roundhouse = sequence(base, {15: (0.15, 0.87)})
    dets = detect(front, roundhouse)
    types = {d["type"] for d in dets}
    assert "front_kick" in types
    assert "roundhouse_kick" in types


def test_guard_detected_when_hands_up():
    guard = make_pose({9: (0.42, 0.16), 10: (0.58, 0.16)})  # fists at face height
    a = MovementAnalyzer()
    for _ in range(6):
        a.push(guard)
    dets = a.analyze()
    types = {d["type"] for d in dets}
    assert "guard" in types
    assert "stance" in types


def test_no_strike_on_static_pose():
    base = make_pose()
    a = MovementAnalyzer()
    for _ in range(8):
        a.push(base)
    dets = a.analyze()
    strike_types = {d["type"] for d in dets} & STRIKE_TYPES
    assert not strike_types


def test_coach_engine_tracks_strikes_and_advice():
    base = make_pose()
    jab = sequence(base, {9: (0.62, 0.62)})
    a = MovementAnalyzer(window=14)
    coach = CoachEngine()
    for pose in jab:
        a.push(pose)
        coach.update(a.analyze())
    assert coach.total_strikes >= 1
    assert coach.counts.get("jab", 0) >= 1
    payload = coach.update(a.analyze())
    assert "counts" in payload
    assert "advice" in payload
    assert isinstance(payload["advice"], list)


def test_coach_reset():
    coach = CoachEngine()
    base = make_pose()
    a = MovementAnalyzer()
    jab = sequence(base, {9: (0.62, 0.62)})
    for pose in jab:
        a.push(pose)
        coach.update(a.analyze())
    assert coach.total_strikes >= 1
    coach.reset()
    assert coach.total_strikes == 0
    assert coach.counts == {}
    assert coach.last is None
