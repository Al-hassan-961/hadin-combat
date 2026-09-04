# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/gemini_free.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Silent global-AI coaching via Google's OFFICIAL Gemini API free tier.
#
# This module adds an optional, invisible second opinion to the local coach
# (app/coach.py). It is designed to "just work":
#   * It auto-activates in the background at startup — no popups and no user
#     interaction are required.
#   * If a valid key is present and the `google-genai` SDK is installed it uses
#     the real (free-tier) API.
#   * If the API is unavailable for any reason (no key, no SDK, network error)
#     it reports `enabled=False` and the rest of HADIN silently falls back to
#     the local ML engine exactly as before.
#   * The word "Gemini" never appears in the UI; the coach only enriches the
#     existing strike / form / fatigue feedback.
#
# Structured output: the model is asked (via a function declaration) to return a
# typed coaching verdict:
#
#   { "strike_type": "jab"|null, "confidence": 87, "form_score": 78,
#     "feedback": "…", "tactical_tip": "…", "fatigue_level": 35 }
#
# Privacy / key handling:
#   * The key is read ONLY from the GEMINI_API_KEY environment variable (or the
#     constructor). It is never logged, sent to the browser, or embedded in the
#     frontend.
#   * Frames are downscaled + JPEG-compressed before leaving the server and a
#     wall-clock throttle guards cost/latency.
#
# Recommended model: `gemini-2.0-flash-exp` (free tier, fast). Requires the
# pure-Python `google-genai` package (see requirements-optional / scripts).
# ---------------------------------------------------------------------------
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("hadin")

# ---------------------------------------------------------------------------
# Structured verdict schema.
# ---------------------------------------------------------------------------
VERDICT_FIELDS = ("strike_type", "confidence", "form_score", "feedback",
                  "tactical_tip", "fatigue_level")

STRIKE_CHOICES = [
    "jab", "cross", "hook", "uppercut",
    "front_kick", "roundhouse_kick", "knee_raise",
    "superman_punch", "spinning_backfist", "axe_kick",
    "question_mark_kick", "guard", "stance", None,
]

DEFAULT_MODEL = "gemini-2.0-flash-exp"
FUNCTION_NAME = "report_coaching_verdict"
FUNCTION_SCHEMA = {
    "name": FUNCTION_NAME,
    "description": (
        "Analyze the martial-arts pose in this frame and report a concise "
        "coaching verdict. Set strike_type to null when there is no clear "
        "strike. confidence is how sure you are of the strike type (0-100). "
        "form_score rates technique quality (0-100). feedback is ONE short "
        "form cue. tactical_tip is ONE short strategic cue. fatigue_level is "
        "0-100 estimated athlete fatigue."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "strike_type": {
                "type": "string", "enum": STRIKE_CHOICES,
                "description": "Detected technique or null.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 100},
            "form_score": {"type": "number", "minimum": 0, "maximum": 100},
            "feedback": {"type": "string"},
            "tactical_tip": {"type": "string"},
            "fatigue_level": {"type": "number", "minimum": 0, "maximum": 100},
        },
        "required": ["strike_type", "confidence", "form_score", "feedback",
                     "tactical_tip", "fatigue_level"],
    },
}

SYSTEM_INSTRUCTION = (
    "You are HADIN-COMBAT's real-time martial-arts coach. Watch the fighter in "
    "the video frames. For each frame call " + FUNCTION_NAME + " once with a "
    "short, actionable verdict. Keep feedback and tactical_tip to at most 8 "
    "words each. If the phone/camera is clearly moving and no stable pose is "
    "visible, report fatigue_level ~50, form_score 0 and feedback "
    "'Hold the phone still'."
)


def _coerce_verdict(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise an arbitrary dict into a valid verdict, or None if unusable."""
    try:
        verdict: Dict[str, Any] = {}
        st = raw.get("strike_type")
        verdict["strike_type"] = st if st in STRIKE_CHOICES else None
        verdict["confidence"] = int(max(0, min(100, float(raw.get("confidence", 0)))))
        verdict["form_score"] = int(max(0, min(100, float(raw.get("form_score", 0)))))
        verdict["feedback"] = str(raw.get("feedback", "")).strip()[:80]
        verdict["tactical_tip"] = str(raw.get("tactical_tip", "")).strip()[:80]
        verdict["fatigue_level"] = int(
            max(0, min(100, float(raw.get("fatigue_level", 0)))))
        verdict["provider"] = raw.get("provider", "live")
        return verdict
    except Exception:  # noqa: BLE001
        return None


def extract_verdict_from_tool_call(message: Any) -> Optional[Dict[str, Any]]:
    """Pull the verdict out of a model server message (tolerant of SDK shapes)."""
    if message is None:
        return None
    if isinstance(message, dict) and "strike_type" in message:
        return _coerce_verdict(message)
    try:
        if isinstance(message, dict):
            sc = message.get("serverContent", message)
            if isinstance(sc, dict):
                fc = sc.get("functionCall") or sc.get("function_call") or {}
                args = fc.get("args") or fc.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                if isinstance(args, dict):
                    return _coerce_verdict(args)
            return None
        parts = getattr(message, "parts", None)
        if parts is not None:
            for p in parts:
                fc = getattr(p, "function_call", None)
                if fc is not None:
                    args = getattr(fc, "args", None)
                    if isinstance(args, str):
                        args = json.loads(args)
                    if isinstance(args, dict):
                        return _coerce_verdict(args)
                t = getattr(p, "text", None)
                if t:
                    d = _parse_json_in_text(t)
                    if d:
                        return _coerce_verdict(d)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI tool-call parse failed (%s)", exc)
        return None


def _parse_json_in_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object embedded in a text reply."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:  # noqa: BLE001
        return None


def _jpeg_b64_from_bgr(bgr: Any, quality: int = 40, width: int = 320) -> str:
    """Downscale + JPEG-encode a BGR frame to a base64 data string."""
    try:
        import cv2

        if bgr is None:
            return ""
        h, w = bgr.shape[:2]
        if w > width:
            nh = max(1, int(h * width / w))
            bgr = cv2.resize(bgr, (width, nh), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return ""
        return base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Local simulated coach (only used for offline testing/demo; clearly internal).
# ---------------------------------------------------------------------------
class _LocalSimCoach:
    """Deterministic stand-in mapping local signals to a verdict shape."""

    def __init__(self) -> None:
        self._last = {"type": None, "quality": 0, "confidence": 0.0}

    def update_state(self, last_strike: Optional[Dict[str, Any]],
                     fatigue_score: int) -> None:
        if last_strike:
            self._last = {"type": last_strike.get("type"),
                          "quality": int(last_strike.get("quality", 0) or 0),
                          "confidence": float(last_strike.get("confidence", 0) or 0)}

    def verdict(self, fatigue_score: int) -> Dict[str, Any]:
        t = self._last.get("type")
        q = self._last.get("quality", 0)
        conf = self._last.get("confidence", 0.0)
        fatigue = int(max(0, min(100, fatigue_score)))
        if t:
            return _coerce_verdict({
                "strike_type": t,
                "confidence": int(max(0, min(100, round(conf * 100)))),
                "form_score": q,
                "feedback": ("Nice extension!" if q >= 70 else "Tighten the form."),
                "tactical_tip": "Follow up with a counter.",
                "fatigue_level": fatigue,
                "provider": "simulated",
            })
        return _coerce_verdict({
            "strike_type": None,
            "confidence": 0,
            "form_score": 0,
            "feedback": "Ready — throw a technique.",
            "tactical_tip": "Work your footwork angles.",
            "fatigue_level": fatigue,
            "provider": "simulated",
        })


# ---------------------------------------------------------------------------
# Public silent coach facade.
# ---------------------------------------------------------------------------
class SilentCoach:
    """Silent global-AI coach.

    Auto-detects availability at construction:
      * simulate mode (AI_COACH_MODE=simulate) -> local simulation.
      * a valid GEMINI_API_KEY + google-genai -> real free-tier live calls.
      * otherwise -> disabled (silent no-op fallback to the local ML engine).

    `enabled` is False whenever it is not usable, so callers can always proceed
    with local analysis. No UI string or popup ever references the provider.
    """

    def __init__(self, api_key: Optional[str] = None,
                 model: str = DEFAULT_MODEL,
                 mode: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip() or None
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.mode = (mode or os.getenv("AI_COACH_MODE", "").strip()
                     or os.getenv("GEMINI_COACH_MODE", "").strip() or "").lower()
        self._client = None
        self._sim = _LocalSimCoach()
        self._last_verdict: Optional[Dict[str, Any]] = None
        self._enabled = False
        self._reason = "disabled"

        if self.mode == "simulate":
            self._enabled = True
            self._reason = "simulation"
            return

        want_live = self.mode == "live" or (not self.mode and self.api_key)
        if not want_live:
            self._reason = "no API key configured"
            return
        if not self.api_key:
            self._reason = "GEMINI_API_KEY not set"
            return
        try:
            from google import genai  # type: ignore

            self._client = genai.Client(api_key=self.api_key)
            self._enabled = True
            self._reason = "live"
            logger.info("Global-AI coach enabled (model=%s)", self.model)
        except Exception as exc:  # noqa: BLE001
            self._enabled = False
            self._reason = f"AI SDK unavailable: {exc}"
            logger.info("Global-AI coach disabled: %s", self._reason)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def status(self) -> Dict[str, Any]:
        """Silent status used only by the backend/logs — never shown in the UI."""
        return {"enabled": self._enabled, "mode": self.mode,
                "reason": self._reason, "model": self.model}

    def feed_local(self, last_strike: Optional[Dict[str, Any]],
                   fatigue_score: int) -> None:
        self._sim.update_state(last_strike, fatigue_score)

    async def _live_verdict(self, jpeg_b64: str) -> Optional[Dict[str, Any]]:
        if self._client is None:
            return None
        try:
            from google import genai  # noqa: F811
            from google.genai import types  # type: ignore

            config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                system_instruction=types.Content(
                    parts=[types.Part(text=SYSTEM_INSTRUCTION)]),
                tools=[types.Tool(function_declarations=[FUNCTION_SCHEMA])],
            )
            blob = base64.b64decode(jpeg_b64)
            async with self._client.aio.live.connect(
                    model=self.model, config=config) as session:
                sent = False
                for kw in ("input_video", "image", "video"):
                    try:
                        await session.send(
                            **{kw: types.Blob(data=blob, mime_type="image/jpeg")})
                        sent = True
                        break
                    except TypeError:
                        continue
                if not sent:
                    await session.send(text="Coach this frame.")
                async for msg in session.receive():
                    v = extract_verdict_from_tool_call(msg)
                    if v:
                        return v
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Global-AI live call failed (%s); disabling.", exc)
            self._enabled = False
            self._reason = "live error"
            return None

    async def analyze_frame(self, bgr: Any,
                            last_strike: Optional[Dict[str, Any]] = None,
                            fatigue_score: int = 0,
                            throttle_ms: int = 1000) -> Optional[Dict[str, Any]]:
        """Analyse one frame -> structured verdict, throttled. Safe no-op if off."""
        if not self._enabled:
            return None
        self.feed_local(last_strike, fatigue_score)
        if self.mode == "simulate":
            self._last_verdict = self._sim.verdict(fatigue_score)
            return self._last_verdict
        now_ms = time.time() * 1000.0
        if now_ms - getattr(self, "_last_live_ms", 0.0) < throttle_ms:
            return self._last_verdict
        self._last_live_ms = now_ms
        jpeg = _jpeg_b64_from_bgr(bgr)
        if not jpeg:
            return self._last_verdict
        verdict = await self._live_verdict(jpeg)
        if verdict:
            self._last_verdict = verdict
        return verdict or self._last_verdict

    def latest(self) -> Optional[Dict[str, Any]]:
        return self._last_verdict


_coach: Optional[SilentCoach] = None


def get_coach() -> SilentCoach:
    """Lazy singleton (construction never blocks on the network)."""
    global _coach
    if _coach is None:
        _coach = SilentCoach()
    return _coach
