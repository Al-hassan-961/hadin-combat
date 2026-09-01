# ---------------------------------------------------------------------------
# HADIN-COMBAT – camera_processor.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Frame preprocessing and drawing helpers shared by the pose pipeline.
# ---------------------------------------------------------------------------
from __future__ import annotations

import base64
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# 17-keypoint COCO bone connections used for skeleton drawing.
COCO_BONES: List[Tuple[int, int]] = [
    (0, 1), (0, 2), (1, 3), (2, 4),          # face/neck to shoulders/arms
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10), # arms
    (5, 11), (6, 12), (11, 12),              # torso
    (11, 13), (13, 15), (12, 14), (14, 16),  # legs
]


def decode_jpeg_frame(data: bytes) -> Optional[np.ndarray]:
    """Decode a raw JPEG byte payload into a BGR numpy frame."""
    if not data:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return frame if frame is not None else None


def preprocess_frame(frame: np.ndarray, size: int = 224) -> np.ndarray:
    """Normalize a BGR frame into a float NCHW tensor for ONNX input."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    rgb = resized.astype(np.float32) / 255.0
    # RGB -> CHW, mean/std normalized (standard ImageNet stats).
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    chw = np.transpose(rgb, (2, 0, 1))
    chw = (chw - mean[:, None, None]) / std[:, None, None]
    return np.expand_dims(chw, axis=0).astype(np.float32)


def _draw_bone(frame: np.ndarray, pts: Sequence[Tuple[float, float]],
               a: int, b: int, color: Tuple[int, int, int], lw: int) -> None:
    if a >= len(pts) or b >= len(pts):
        return
    pa, pb = pts[a], pts[b]
    if pa[0] < 0 or pb[0] < 0:
        return
    cv2.line(frame, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), color, lw)


def draw_skeleton(
    frame: np.ndarray,
    keypoints: Sequence[Dict[str, float]],
    color: Tuple[int, int, int] = (0, 255, 200),
    conf_threshold: float = 0.3,
) -> np.ndarray:
    """Draw a 17-keypoint skeleton onto the frame (in place) and return it.

    keypoints is a list of dicts: {"x": float, "y": float, "score": float}.
    Coordinates are in raw pixel space.
    """
    pts: List[Tuple[float, float]] = []
    for kp in keypoints:
        if kp.get("score", 0.0) < conf_threshold:
            pts.append((-1.0, -1.0))
        else:
            pts.append((kp["x"], kp["y"]))

    h, w = frame.shape[:2]
    for a, b in COCO_BONES:
        _draw_bone(frame, pts, a, b, color, lw=max(2, min(6, w // 200)))

    for x, y in pts:
        if x < 0:
            continue
        cv2.circle(frame, (int(x), int(y)), max(2, w // 300), color, -1)
    return frame


def overlay_text(
    frame: np.ndarray,
    text: str,
    origin: Tuple[int, int] = (20, 40),
    color: Tuple[int, int, int] = (0, 255, 200),
    scale: float = 0.7,
) -> np.ndarray:
    """Draw a semi-transparent status bar and a text label."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 64), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)
    return frame


def draw_opponent(
    frame: np.ndarray,
    opponent_pose: Sequence[Dict[str, float]],
    color: Tuple[int, int, int] = (255, 40, 90),
) -> np.ndarray:
    """Draw the AI opponent as a semi-transparent ghost overlay."""
    overlay = frame.copy()
    pts: List[Tuple[float, float]] = []
    for kp in opponent_pose:
        pts.append((kp.get("x", -1.0), kp.get("y", -1.0)))

    h, w = frame.shape[:2]
    for a, b in COCO_BONES:
        _draw_bone(overlay, pts, a, b, color, lw=max(2, min(6, w // 160)))
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

    for x, y in pts:
        if x < 0:
            continue
        cv2.circle(frame, (int(x), int(y)), max(3, w // 200), color, -1)
    return frame


def scale_keypoints_to_frame(
    keypoints: Sequence[Dict[str, float]],
    frame_w: int,
    frame_h: int,
    norm: bool = True,
) -> List[Dict[str, float]]:
    """Rescale normalized [0..1] keypoints to raw pixel coordinates."""
    out: List[Dict[str, float]] = []
    for kp in keypoints:
        out.append({
            "x": kp["x"] * frame_w if norm else kp["x"],
            "y": kp["y"] * frame_h if norm else kp["y"],
            "score": kp.get("score", 1.0),
        })
    return out


def jpeg_bytes(frame: np.ndarray, quality: int = 70) -> bytes:
    """Encode a frame to JPEG bytes for WebSocket transport."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""
