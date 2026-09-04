# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/test_gemini_coach.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Tests for the optional Google Gemini global-AI coaching layer
# (app/gemini_coach.py): graceful no-key disable, simulation mode, structured
# verdict coercion, and tool-call parsing.
# ---------------------------------------------------------------------------
import asyncio
import os
from unittest import mock

import pytest

from app.gemini_coach import (GeminiCoach, _coerce_verdict,
                              extract_verdict_from_tool_call)


def _unset_gemini_env():
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GEMINI_MODEL", None)
    os.environ.pop("GEMINI_COACH_MODE", None)


def test_disabled_without_key():
    _unset_gemini_env()
    c = GeminiCoach(api_key=None)
    assert c.enabled is False
    assert asyncio.run(c.analyze_frame(None)) is None
    assert c.latest() is None


def test_simulate_mode_produces_structured_verdict():
    _unset_gemini_env()
    os.environ["GEMINI_COACH_MODE"] = "simulate"
    c = GeminiCoach()
    assert c.enabled is True and c.mode == "simulate"
    c.feed_local({"type": "hook", "quality": 88, "confidence": 0.8}, fatigue_score=40)
    v = asyncio.run(c.analyze_frame(None, fatigue_score=40))
    assert v is not None
    assert v["strike_type"] == "hook"
    assert v["provider"] == "simulated"     # never mistaken for real AI
    for f in ("confidence", "form_score", "fatigue_level"):
        assert 0 <= v[f] <= 100
    assert isinstance(v["feedback"], str)
    assert isinstance(v["tactical_tip"], str)


def test_live_mode_needs_sdk_or_key():
    _unset_gemini_env()
    # No key -> live not initialised, disabled.
    c = GeminiCoach(api_key=None, mode="live")
    assert c.enabled is False
    assert "GEMINI_API_KEY" in c.status["reason"] or c.status["reason"]


def test_coerce_clamps_and_rejects():
    v = _coerce_verdict({"strike_type": "nonsense", "confidence": 999,
                         "form_score": -5, "feedback": "x", "tactical_tip": "y",
                         "fatigue_level": 200})
    assert v["strike_type"] is None
    assert v["confidence"] == 100
    assert v["form_score"] == 0
    assert v["fatigue_level"] == 100
    assert _coerce_verdict({"confidence": "oops"}) is None


def test_extract_from_tool_call_dict():
    msg = {"serverContent": {"functionCall": {
        "args": {"strike_type": "cross", "confidence": 90, "form_score": 80,
                 "feedback": "ok", "tactical_tip": "tip", "fatigue_level": 20}}}}
    v = extract_verdict_from_tool_call(msg)
    assert v and v["strike_type"] == "cross" and v["confidence"] == 90


def test_extract_from_object_parts():
    # Simulate google.genai objects (attribute-based API).
    def _fc(args):
        o = type("FC", (), {})()
        o.args = args
        return o

    def _part():
        o = type("P", (), {})()
        o.function_call = _fc({"strike_type": "jab", "confidence": 87,
                               "form_score": 75, "feedback": "f",
                               "tactical_tip": "t", "fatigue_level": 30})
        o.text = None
        return o

    msg = type("R", (), {})()
    msg.parts = [_part()]
    v = extract_verdict_from_tool_call(msg)
    assert v and v["strike_type"] == "jab" and v["fatigue_level"] == 30


def test_extract_from_text_json():
    msg = type("R", (), {})()
    msg.parts = []
    # JSON embedded in text
    from app.gemini_coach import _parse_json_in_text
    parsed = _parse_json_in_text(
        'Sure: {"strike_type":"roundhouse_kick","confidence":70,'
        '"form_score":66,"feedback":"pivot more","tactical_tip":"chamber the knee",'
        '"fatigue_level":50}')
    assert parsed and parsed["strike_type"] == "roundhouse_kick"
