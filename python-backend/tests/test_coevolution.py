# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_coevolution.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Verifies session-over-session co-evolution: the athlete profile is derived
# from completed HISTORY and persists to JSON, so the opponent difficulty
# genuinely grows with the athlete.
# ---------------------------------------------------------------------------

import json
import time

import pytest

import app.main as m
from app.coach import CoachEngine


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    """Redirect profile persistence to a temp file + clean global state."""
    saved_file = m.ATHLETE_PROFILE_FILE
    m.ATHLETE_PROFILE_FILE = tmp_path / "athlete_profile.json"
    m.HISTORY.clear()
    m.athlete_profile.update({
        "total_sessions": 0, "total_rounds": 0, "win_rate": 0.5,
        "avg_response_ms": 0.0, "progress_score": 0.0})
    yield
    m.ATHLETE_PROFILE_FILE = saved_file
    m.HISTORY.clear()


def _fake_sess(total, landed, perf, fatigue=20, reaction=0.4):
    sess = {
        "started": time.time(),
        "frames": 100,
        "profile": "balanced",
        "_strikes_seen": total,
        "quality_list": [[90, 0.9]] * landed + [[40, 0.4]] * (total - landed),
        "fatigue_progression": [[0, 5], [30, fatigue]],
    }
    sess["coach"] = CoachEngine()
    sess["coach"].counts = {"jab": total}
    sess["fatigue"] = type("F", (), {"score": lambda self: {"score": fatigue}})()
    summ = m._compose_session_summary("c", sess)
    summ["performance"] = perf
    summ["reaction_s"] = reaction if reaction is not None else summ.get("reaction_s")
    return summ


def test_profile_derived_from_history_and_persisted():
    m.HISTORY.append(_fake_sess(50, 45, 92, fatigue=25, reaction=0.3))
    m.HISTORY.append(_fake_sess(60, 52, 90, fatigue=30, reaction=0.35))
    m._recompute_athlete_profile()
    assert m.athlete_profile["total_sessions"] == 2
    assert m.athlete_profile["win_rate"] > 0.8          # high clean ratio
    assert 0.0 <= m.athlete_profile["progress_score"] <= 1.0
    assert m.athlete_profile["progress_score"] > 0.5
    assert m.athlete_profile["avg_response_ms"] > 0
    assert m.ATHLETE_PROFILE_FILE.exists()
    data = json.loads(m.ATHLETE_PROFILE_FILE.read_text())
    assert data["total_sessions"] == 2


def test_profile_resets_when_no_history():
    m._recompute_athlete_profile()
    assert m.athlete_profile["total_sessions"] == 0
    assert m.athlete_profile["win_rate"] == 0.5


def test_profile_loads_previous_run():
    m.HISTORY.append(_fake_sess(40, 36, 88))
    m._recompute_athlete_profile()
    # Simulate a restart: re-load from disk.
    m.athlete_profile = m._load_athlete_profile()
    assert m.athlete_profile["total_sessions"] == 1
    assert m.athlete_profile["win_rate"] > 0.8
