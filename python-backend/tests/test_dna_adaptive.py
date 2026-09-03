# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_dna_adaptive.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Exercises the canonical Fighting-DNA / adaptive-opponent / co-evolution /
# fatigue modules under their documented, publicly-named entry points.
# ---------------------------------------------------------------------------

from app.adaptive_opponent import AdaptiveOpponent, build_opponent
from app.coevolution import CoEvolutionPolicy
from app.dna_encoder import FightingDNAEncoder
from app.fatigue import FatigueTracker


def make_pose(moves=None):
    kps = []
    for i in range(17):
        y = 0.05 + 0.055 * i
        kps.append({"x": 0.5, "y": min(0.95, y), "score": 1.0})
    for idx, (x, y) in (moves or {}).items():
        if 0 <= idx < 17:
            kps[idx] = {"x": x, "y": y, "score": 1.0}
    return kps


def test_dna_encoder_returns_latent_and_tags():
    enc = FightingDNAEncoder(latent_dim=64)
    for _ in range(10):
        enc.push(make_pose({9: (0.7, 0.6), 10: (0.6, 0.6)}))  # hands up
    latent, tags = enc.encode()
    assert len(latent) == 64
    assert isinstance(tags, list) and tags


def test_dna_encoder_reset():
    enc = FightingDNAEncoder()
    enc.push(make_pose())
    enc.reset()
    latent, _ = enc.encode()
    assert all(v == 0.0 for v in latent)


def test_adaptive_opponent_mirrors_and_shapes():
    op = AdaptiveOpponent()
    pose = make_pose({5: (0.45, 0.25), 6: (0.55, 0.25)})
    opponent = build_opponent(pose, "defensive", 0.5)
    assert len(opponent) == 17
    assert all(0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0 for p in opponent)
    # Opponent mirrors the athlete's horizontal position.
    assert abs(opponent[0]["x"] - (1.0 - pose[0]["x"])) < 0.15


def test_coevolution_policy_raises_difficulty_with_progress():
    pol = CoEvolutionPolicy()
    gentle = pol.step({"win_rate": 0.3, "progress_score": 0.1, "total_sessions": 1}, 0.4)
    strong = pol.step({"win_rate": 0.9, "progress_score": 0.9, "total_sessions": 20}, 0.4)
    assert strong >= gentle
    assert 0.05 <= gentle <= 0.95 and 0.05 <= strong <= 0.95


def test_fatigue_tracker_via_named_module():
    ft = FatigueTracker()
    t = 0.0
    for _ in range(6):
        t += 0.5
        ft.observe_strike(0.85, t)
        ft.observe_stance(make_pose(), t)
    s = ft.score()
    assert 0 <= s["score"] <= 100
    assert "level" in s and "advice" in s
