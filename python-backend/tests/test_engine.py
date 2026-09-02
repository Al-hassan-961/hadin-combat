# ---------------------------------------------------------------------------
# HADIN-COMBAT – test_engine.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Unit tests for the pure-Python AI engine (works with no C++/models)."""

import random

from app.engine import (
    PurePythonCoEvolution,
    PurePythonOpponentGenerator,
    PurePythonStyleEncoder,
)


def make_pose(arms_up=False):
    """A static 17-keypoint COCO pose."""
    x = 0.5
    kps = [{"x": x, "y": 0.05, "score": 0.9}]  # nose
    # shoulders (5,6)
    kps += [{"x": x - 0.15, "y": 0.2, "score": 0.9},
            {"x": x + 0.15, "y": 0.2, "score": 0.9}]
    # elbows (7,8)
    kps += [{"x": x - 0.2, "y": 0.35, "score": 0.9},
            {"x": x + 0.2, "y": 0.35, "score": 0.9}]
    # wrists (9,10)
    arm_y = 0.15 if arms_up else 0.5
    kps += [{"x": x - 0.25, "y": arm_y, "score": 0.9},
            {"x": x + 0.25, "y": arm_y, "score": 0.9}]
    # hips (11,12)
    kps += [{"x": x - 0.12, "y": 0.55, "score": 0.9},
            {"x": x + 0.12, "y": 0.55, "score": 0.9}]
    # knees (13,14)
    kps += [{"x": x - 0.12, "y": 0.72, "score": 0.9},
            {"x": x + 0.12, "y": 0.72, "score": 0.9}]
    # ankles (15,16)
    kps += [{"x": x - 0.1, "y": 0.92, "score": 0.9},
            {"x": x + 0.1, "y": 0.92, "score": 0.9}]
    return kps


def test_style_encoder_latent_shape_and_tags():
    enc = PurePythonStyleEncoder(latent_dim=64, window=8)
    pose = make_pose()
    for _ in range(5):
        enc.push(pose)
    latent, tags = enc.encode()
    assert len(latent) == 64
    assert isinstance(tags, list) and len(tags) <= 4


def test_style_encoder_returns_neutral_when_empty():
    enc = PurePythonStyleEncoder()
    latent, tags = enc.encode()
    assert latent == [0.0] * 64
    assert tags == ["neutral"]


def test_opponent_mirrors_horizontally():
    random.seed(7)  # deterministic jitter
    gen = PurePythonOpponentGenerator()
    pose = make_pose()
    opp = gen.generate(pose, difficulty=0.5)
    assert len(opp) == len(pose)
    # Mirror: opponent nose x ≈ 1 - athlete nose x (within jitter).
    nose = [k for k in pose if k["y"] == 0.05][0]
    opp_nose = opp[0]
    assert abs(opp_nose["x"] - (1.0 - nose["x"])) < 0.12
    for k in opp:
        assert 0.0 <= k["x"] <= 1.0
        assert 0.0 <= k["y"] <= 1.0


def test_opponent_empty_when_no_pose():
    gen = PurePythonOpponentGenerator()
    assert gen.generate([], 0.5) == []


def test_coevolution_stays_in_bounds():
    evo = PurePythonCoEvolution()
    profile = {"win_rate": 0.9, "progress_score": 0.6, "total_sessions": 10}
    for _ in range(20):
        d = evo.step(profile, 0.4)
        assert 0.0 <= d <= 1.0
