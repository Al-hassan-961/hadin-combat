# ---------------------------------------------------------------------------
# HADIN-COMBAT – app/gemini_coach.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Google Gemini global-AI coaching layer.
#
# The local coach (app/coach.py) is fast, private and works offline, but it is
# purely heuristic. This module adds an OPTIONAL "second opinion" from Google's
# Gemini Multimodal Live API: it streams camera frames (downsampled JPEG) to a
# Gemini Live session and asks it to return a structured coaching verdict for
# every frame.
#
# Structured output: Gemini is configured with a function declaration (function
# calling) whose arguments ARE the structured coaching verdict. This avoids
# fragile free-text parsing. The expected JSON shape:
#
#   {
#     "strike_type": "jab",          # or null
#     "confidence": 87,              # 0..100
#     "form_score": 78,              # 0..100
#     "feedback": "Great speed…",    # one short form cue
#     "tactical_tip": "Follow up…",  # one short tactical cue
#     "fatigue_level": 35            # 0..100
#   }
#
# GRACEFUL DEGRADATION (important):
#   * If no GEMINI_API_KEY is set, or the `google-genai` SDK is not installed,
#     or the network/model call fails, the coach reports `enabled=False` and the
#     rest of HADIN keeps working exactly as before (local coach only).
#   * A SIMULATION mode (`GEMINI_COACH_MODE=simulate`) produces the same
#     structured shape from the local pose signals, so the full UI/pipeline can
#     be demonstrated and tested with zero network and zero cost. Results are
#     tagged `"provider": "simulated"` so they are never mistaken for real AI.
#
# Recommended model: `gemini-2.0-flash-exp` (cheap, fast, supports live video).
# Requires the pure-Python `google-genai` package (see requirements-optional).
# ---------------------------------------------------------------------------
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hadin")

# ---------------------------------------------------------------------------
# Structured verdict schema (also used to validate / default simulated output).
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
# Function declaration handed to Gemini so its reply is a typed tool call.
FUNCTION_NAME = "report_coaching_verdict"
FUNCTION_SCHEMA = {
    "name": FUNCTION_NAME,
    "description": (
        "Analyze the martial-arts pose in this frame and report a concise "
        "coaching verdict. Set strike_type to null when there is no clear "
        "strike. Confidence is how sure you are of the strike type (0-100). "
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
        verdict["provider"] = raw.get("provider", "gemini")
        return verdict
    except Exception:  # noqa: BLE001
        return None


def extract_verdict_from_tool_call(message: Any) -> Optional[Dict[str, Any]]:
    """Pull the verdict out of a Gemini Live server message.

    In a live session Gemini replies with server_content / functionCall parts.
    This helper tolerates several shapes so it keeps working across SDK minor
    versions without crashing:
      * dict with {"functionCall": {"args": {...}, "name": ...}}
      * object with .function_call.args
      * dict already carrying verdict keys
    """
    if message is None:
        return None
    # Plain verdict dict already in the right shape.
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
        # google.genai response object(s).
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
        logger.warning("Gemini tool-call parse failed (%s)", exc)
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
    # Try to slice out a JSON object between the first { and last }.
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
# Simulated coach: derives a plausible verdict from the LOCAL signals so the UI
# and pipeline can be exercised without a key or network. Clearly labelled.
# ---------------------------------------------------------------------------
class _SimulatedCoach:
    """Deterministic stand-in that maps local pose/fatigue state to a verdict."""

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
                "feedback": ("Nice extension!" if q >= 70
                             else "Tighten the form."),
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
# Public coach facade.
# ---------------------------------------------------------------------------
class GeminiCoach:
    """Global-AI coaching via Google Gemini Multimodal Live API.

    Modes (env GEMINI_COACH_MODE):
      * "live"     -> real Gemini Live session (needs GEMINI_API_KEY + SDK).
      * "simulate" -> local simulated verdicts (no key, no network).
      * anything else / unset -> disabled unless a key is present.

    The coach is disabled by default. When disabled, `enabled` is False and
    every method is a safe no-op returning None, so the rest of HADIN is
    completely unaffected.
    """

    def __init__(self, api_key: Optional[str] = None,
                 model: str = DEFAULT_MODEL,
                 mode: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip() or None
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.mode = (mode or os.getenv("GEMINI_COACH_MODE", "").strip() or "").lower()
        self._client = None
        self._sim = _SimulatedCoach()
        self._last_verdict: Optional[Dict[str, Any]] = None
        self._enabled = False
        self._reason = ""

        if self.mode == "simulate":
            self._enabled = True
            self._reason = "simulation"
            return

        # "live" mode (or auto if a key is present).
        want_live = self.mode == "live" or (not self.mode and self.api_key)
        if not want_live:
            self._reason = "no api key / live not requested"
            return
        if not self.api_key:
            self._reason = "GEMINI_API_KEY not set"
            return
        try:
            from google import genai  # type: ignore

            self._client = genai.Client(api_key=self.api_key)
            self._enabled = True
            self._reason = "live"
            logger.info("GeminiCoach enabled (%s model=%s)", self._reason, self.model)
        except Exception as exc:  # noqa: BLE001
            self._enabled = False
            self._reason = f"google-genai unavailable: {exc}"
            logger.warning("GeminiCoach disabled: %s", self._reason)

    # ------------------------------------------------------------- properties
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, v: str) -> None:
        self._mode = (v or "").lower()

    @property
    def status(self) -> Dict[str, Any]:
        return {"enabled": self._enabled, "mode": self._mode,
                "reason": self._reason, "model": self.model}

    def feed_local(self, last_strike: Optional[Dict[str, Any]],
                   fatigue_score: int) -> None:
        """Feed local signals so the simulated coach can produce verdicts."""
        self._sim.update_state(last_strike, fatigue_score)

    # ------------------------------------------------------------ real (live)
    async def _live_verdict(self, jpeg_b64: str) -> Optional[Dict[str, Any]]:
        """One structured verdict from a Gemini Live session for a single frame.

        A persistent streaming session is better for continuous video; this
        opens a short frame-scoped call so the server can throttle easily. It
        sends the JPEG as a video part and requests a function call verdict.
        """
        if self._client is None:
            return None
        try:
            from google import genai  # noqa: F811
            from google.genai import types  # type: ignore

            config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                system_instruction=types.Content(
                    parts=[types.Part(text=SYSTEM_INSTRUCTION)]),
                tools=[types.Tool(
                    function_declarations=[FUNCTION_SCHEMA])],
            )
            blob = base64.b64decode(jpeg_b64)
            async with self._client.aio.live.connect(
                    model=self.model, config=config) as session:
                # Send the frame as a video/image part. Exact keyword differs
                # across SDK versions; try the common ones, else send text only.
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
            logger.warning("Gemini live call failed (%s); disabling.", exc)
            self._enabled = False
            self._reason = f"live error: {exc}"
            return None

    # ---------------------------------------------------------------- facade
    async def analyze_frame(self, bgr: Any, last_strike: Optional[Dict[str, Any]] = None,
                            fatigue_score: int = 0,
                            throttle_ms: int = 1000) -> Optional[Dict[str, Any]]:
        """Analyse one frame -> structured verdict, throttled.

        throttle_ms: minimum wall-clock between LIVE calls (rate/cost guard).
        Simulated mode always returns instantly and locally.
        """
        if not self._enabled:
            return None
        self.feed_local(last_strike, fatigue_score)

        if self._mode == "simulate":
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
        """The most recent verdict (None if never analysed)."""
        return self._last_verdict


# Convenience singleton factory (lazy; cheap because __init__ doesn't network).
_coach: Optional[GeminiCoach] = None


def get_coach() -> GeminiCoach:
    global _coach
    if _coach is None:
        _coach = GeminiCoach()
    return _coach
