# HADIN-COMBAT Architecture

> *The AI Opponent That Learns Your Fighting DNA.*

This document details the end-to-end data flow, latency budget, threading
model, and graceful-degradation fallback mechanisms of HADIN-COMBAT.

---

## 1. High-Level Overview

```mermaid
flowchart TB
    subgraph Client[Browser - Mobile First]
        CAM[getUserMedia] --> CAP[capture loop 15fps]
        CAP -->|JPEG frames over WebSocket| WS
        WS -->|JSON {keypoints, opponent, feedback, debug_frame}| REND[Canvas overlay]
        REND --> DISP[Neon skeleton + ghost opponent]
    end

    subgraph Server[Starlette / uvicorn]
        WS[WebSocket gateway]
        WS --> DEC[decode_jpeg_frame]
        DEC --> PPE[Pose Estimation]
        PPE --> SE[Style Encoder]
        SE --> OG[Opponent Generator]
        OG --> CE[Co-Evolution memory]
        FB[Coach Feedback heuristic]
        PPE --> FB
    end

    subgraph Inference[Core]
        PPE -->|CPP path| CPP[ONNX Runtime via pybind11]
        PPE -->|Fallback path| MP[MediaPipe]
        SE --> CPP
        OG --> CPP
        CE --> CPP
    end
```

---

## 2. Data Flow

1. **Capture** — `app.js` reads the camera via `getUserMedia` and runs a
   ~15 fps capture loop. Each frame is drawn to an off-screen canvas (to
   un-mirror the view), then compressed to JPEG (`quality 0.7`) and sent over
   a **binary WebSocket** message.

2. **Decode** — `camera_processor.decode_jpeg_frame` decodes the JPEG bytes to
   a BGR `numpy` frame with OpenCV.

3. **Pose estimation** — keypoints `(x, y, score)` are extracted by the active
   backend (C++ ONNX Runtime **or** MediaPipe).

4. **Style encoding** — a rolling window of recent poses is passed to the
   autoencoder bottleneck, producing a **Fighting-DNA latent vector**.

5. **Opponent generation** — the latent plus a difficulty scalar is fed to the
   diffusion generator, producing a normalized opponent pose.

6. **Co-evolution** — cumulative athlete stats update the difficulty for the
   next step, so the opponent improves with the athlete.

7. **Feedback** — a lightweight heuristic grades posture/alignment and returns
   coaching notes.

8. **Render** — the server returns a `debug_frame` (skeleton already drawn) plus
   the opponent pose; the client overlays the ghost opponent and updates the HUD.

---

## 3. Latency Budget

| Stage | C++ core | MediaPipe fallback | OpenCV motion |
|---|---|---|---|
| JPEG decode | ~2 ms | ~2 ms | ~2 ms |
| Pose inference | ~10–40 ms | ~25–80 ms | ~5 ms (crude) |
| Style encode | ~2 ms | ~1 ms | ~1 ms |
| Opponent generate | ~3 ms | ~1 ms | ~1 ms |
| JSON serialize + network | ~10 ms | ~10 ms | ~10 ms |
| **Total server-side** | **~25–55 ms** | **~40–100 ms** | **~20 ms** |

The design targets **sub-50 ms** server inference on mobile-class hardware
using the C++ core and **sub-100 ms** end-to-end at 15 fps with MediaPipe.

The client-side capture loop runs at 15 fps regardless of backend; the server
processes frames asynchronously so the UI never blocks on a slow backend.

---

## 4. Threading & Concurrency

- **uvicorn** runs the ASGI app. Each WebSocket connection is an independent
  coroutine; Starlette's event loop never blocks on I/O.
- **ONNX Runtime** `IntraOpNumThreads = 2` bounds CPU contention inside the
  C++ core, keeping inference off the critical asyncio path per request.
- **SessionManager** is an in-memory dict keyed by `client_id`. In production,
  use **Redis** (already wired in `docker-compose`) to share session state
  across uvicorn workers.
- Model loading happens **once at startup** (`AICore`), not per request.

---

## 5. Fallback Mechanism (Graceful Degradation)

The `AICore` class resolves the active backend in this order:

```mermaid
flowchart LR
    A[Start] --> B{USE_CPP_CORE?}
    B -- no --> D{MediaPipe?\nimport available}
    B -- yes --> C{import hadin_core\n&& pose.is_ready()}
    C -- ok --> CPP[Backend = cpp]
    C -- fail --> F{FALLBACK_TO_PYTHON?}
    F -- no --> N[Backend = none]
    F -- yes --> D
    D -- yes --> MP[Backend = mediapipe]
    D -- no --> O[Backend = opencv\nmotion fallback]
```

- The **C++ core** is a pure accelerator. The **opponent, style and
  co-evolution** logic has a full pure-Python implementation in
  `app/engine.py`, so those work even without C++ or ONNX models.
- **Pose** resolves C++ → MediaPipe → OpenCV motion fallback → none. The
  OpenCV motion fallback synthesizes a crude skeleton so the app keeps
  producing keypoints and feedback on any device.
- If the C++ library fails to build or load, `USE_CPP_CORE=false` is written
  to `.env` by the quickstart script, and the server runs entirely on Python.
- The active backend is reported to the client in the `hello` message and via
  `GET /api/stats`, and surfaced as a colored pill in the UI.

---

## 6. Security & Privacy

- Inference runs locally on the server/device; **no cloud dependence**.
- WebSocket endpoints accept any `client_id`; add token auth for production.
- The camera stream is never stored or persisted.
