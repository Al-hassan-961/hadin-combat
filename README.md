# 🥋 HADIN-COMBAT

> **The AI Opponent That Learns Your Fighting DNA** — *"Unlock the hidden techniques within you"*

![Build Passing](https://img.shields.io/badge/build-passing-brightgreen)
![CI](https://github.com/Al-hassan-961/hadin-combat/actions/workflows/ci.yml/badge.svg)
![C++17](https://img.shields.io/badge/C%2B%2B-17-blue)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB)
![HTML5](https://img.shields.io/badge/HTML5-Mobile%20First-E34F26)
![License](https://img.shields.io/badge/License-MIT-green)
![Termux](https://img.shields.io/badge/Termux-Compatible-success)

**HADIN** = **HA**ssan + **DIN**a — a perfect fusion of our names, just as HADIN-COMBAT fuses human skill with machine intelligence. Created by **Al-hassan Shehade & Dina Balcheh**.

---

## 📖 The HADIN Philosophy

Every fighter has a **fighting DNA** — a unique combination of stance, timing, rhythm, footwork, and instincts. Traditional training partners repeat patterns; they don't adapt to *you*. HADIN-COMBAT is the first platform whose **AI opponent actually learns your movements**, extracts your signature style, and evolves to challenge the *specific* weaknesses in your game.

- **It watches.** Real-time pose estimation captures your skeleton from a phone camera.
- **It understands.** A neural style autoencoder compresses your movement into a latent "fighting DNA" fingerprint.
- **It adapts.** An opponent generator turns that fingerprint into an adversary calibrated to your level and tendencies.
- **It grows with you.** Co-evolution drives both you and the AI to improve across training sessions.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    subgraph Client["📱 Mobile Browser (HTML5)"]
        C[Camera getUserMedia] --> CV[Canvas Overlay]
        CV -->|JPEG WebSocket| S
        FB[Real-time Feedback] <-->|JSON WebSocket| S
    end

    subgraph Server["🖥️ Backend (FastAPI)"]
        S[WebSocket Gateway] --> PP[Pose Estimation]
        PP --> SE[Style Encoder]
        SE --> OG[Opponent Generator]
        OG --> CE[Co-Evolution Memory]
        PP -. C++ / MediaPipe fallback .-> ORT[ONNX Runtime / MediaPipe]
    end

    S <--> R[(Redis Cache)]
    S --> DB[(Model Registry)]
```

- **C++17/20 core** (`hadin_core`) — sub-50ms ONNX Runtime inference on mobile-class devices, exposed to Python via pybind11.
- **Pure-Python fallback** — if C++ compilation fails on a device, the backend transparently falls back to MediaPipe. The app keeps working.
- **Zero-install frontend** — any phone browser (Android or iOS) opens the server URL and trains immediately.

---

## ✨ Features

- 🧬 **Fighting DNA Extraction** — your movement style is encoded into a reusable latent fingerprint.
- 🥊 **Adaptive Opponent** — the AI opponent adapts stance, tempo, and defense to counter you.
- 🔄 **Co-Evolution** — both you and the AI improve session over session.
- 📱 **Mobile-First** — thumb-friendly neon UI, works on any browser.
- 🚀 **One-Command Setup** on Android (Termux) — no manual steps.
- 📡 **Real-Time WebSockets** — sub-100ms latency for pose → opponent → feedback.
- 🧯 **Graceful Degradation** — if C++ compilation fails, the backend falls
  back to MediaPipe and then an OpenCV motion fallback. Opponent, style and
  co-evolution are pure Python (`app/engine.py`), so **the app is fully
  functional with no C++ and no ONNX models**. The C++ core is an optional
  accelerator for sub-50ms inference.
- 🧠 **Local & Private** — inference runs on your device/server; no cloud dependence.
- 🐳 **Docker Ready** — one command to deploy the full stack.

---

## 🚀 Quick Start

### 📱 Android (Termux)

```bash
# 1. Pre-built native binaries (never compiled on Android):
pkg install -y python-numpy python-opencv-python

# 2. Clone and run the one-command setup:
git clone https://github.com/Al-hassan-961/hadin-combat.git
cd hadin-combat
bash scripts/termux_quickstart.sh
```

> 🔧 **Zero compilation on Android.** `numpy` and OpenCV are installed as
> Termux's pre-built packages; `setup.py` detects Termux (via `TERMUX_VERSION`,
> `/data/data/com.termux`, or `sys.platform == 'android'`) and **skips** them
> in `pip install -e .`, so pip never triggers a C source build (which would
> fail because Android's Bionic libc lacks `ctanh`). All other dependencies
> are pure-Python wheels.

The script installs dependencies, starts the server, and prints:

```
✅ Server running at http://<local-ip>:8000 – open this URL in your browser!
```

### 📱 iOS

No installation needed. Run the server on any machine (Termux, laptop, or Docker), then open the printed URL in Safari. The web app works out of the box.

> iSH Shell (Alpine Linux) users: `bash scripts/ish_quickstart.sh`

### 🐳 Docker

```bash
docker-compose up --build
```

Then open `http://localhost:8000`.

### 💻 Linux / macOS (development)

```bash
bash scripts/setup_dev.sh
```

---

## 🧭 Next Steps

- **[Setup Guide](docs/SETUP.md)** — manual install on Linux, macOS, and Termux.
- **[Architecture](docs/ARCHITECTURE.md)** — data flow, latency, threading, and fallback mechanics.
- **[API Reference](docs/API_REFERENCE.md)** — WebSocket JSON schemas and REST endpoints.
- **[AI Models](docs/AI_MODELS.md)** — training the autoencoder, diffusion model, and PPO policy.
- **[Contribute](docs/CONTRIBUTING.md)** — code style, commit conventions, and PR process.

---

## 🧬 Models

Pre-trained ONNX models (pose, style encoder, opponent generator, co-evolution) can be downloaded from the [models directory](models/README.md). Place them under `models/` before first run, or the backend falls back to pure Python pose estimation so the app still works.

---

## 👥 Creators

| | |
|---|---|
| **Al-hassan Shehade** | [GitHub](https://github.com/Al-hassan-961) |
| **Dina Balcheh** | [GitHub](https://github.com/) |

> *"Just as HADIN fuses Hassan and Dina, this platform fuses human intuition with machine intelligence."*

---

## 📄 License

Released under the **MIT License**. Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh. See [LICENSE](LICENSE).

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Core AI inference | C++17/20 · ONNX Runtime · pybind11 |
| Backend | Python 3.10+ · FastAPI · WebSockets · OpenCV · MediaPipe |
| Frontend | HTML5 · CSS · JavaScript · Canvas · getUserMedia |
| Deployment | Docker Compose · uvicorn · Redis |
