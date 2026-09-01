# HADIN-COMBAT Setup Guide

Manual setup for Linux, macOS, and Termux (Android). For the fastest path,
use the one-command quickstart scripts:

- **Termux:** `bash scripts/termux_quickstart.sh`
- **iSH (iOS):** `bash scripts/ish_quickstart.sh`
- **Linux/macOS dev:** `bash scripts/setup_dev.sh`

---

## Prerequisites

- **Python 3.10+** and `pip`
- **CMake ≥ 3.16** and a C++17 compiler (for the C++ core)
- [ONNX Runtime](https://onnxruntime.ai/) (optional — falls back to MediaPipe)
- Git

---

## Linux

```bash
# 1. Clone
git clone https://github.com/Al-hassan-961/hadin-combat.git
cd hadin-combat

# 2. Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r python-backend/requirements.txt

# 3. (Recommended) Build the C++ core
pip install onnxruntime pybind11
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
# On failure: echo "USE_CPP_CORE=false" > python-backend/.env

# 4. Copy models
#   Place pose.onnx (and optional models) under models/

# 5. Run
cd python-backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

---

## macOS

Same as Linux, with two caveats:

```bash
brew install cmake python
# For ONNX Runtime headers, set the env for cmake:
export ONNXRUNTIME_ROOT="$(python -c 'import onnxruntime,os;print(os.path.dirname(onnxruntime.__file__))')"
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

> If the C++ build fails, set `USE_CPP_CORE=false` and MediaPipe takes over.

---

## Termux (Android)

```bash
pkg update -y && pkg upgrade -y
pkg install -y git python clang cmake opencv onnxruntime
git clone https://github.com/Al-hassan-961/hadin-combat.git
cd hadin-combat
bash scripts/termux_quickstart.sh
```

The script handles venv creation, C++ build, `.env` writing, and server start.

---

## iSH (iOS / Alpine)

```bash
apk update && apk add python3 py3-pip cmake make g++
git clone https://github.com/Al-hassan-961/hadin-combat.git
cd hadin-combat
bash scripts/ish_quickstart.sh
```

---

## Docker

```bash
docker-compose up --build
# http://localhost:8000
```

Environment variables can be overridden via a `.env` file or the compose file.

---

## Environment Variables

See `python-backend/.env.example`. Key variables:

| Variable | Default | Description |
|---|---|---|
| `USE_CPP_CORE` | `true` | Use the C++ ONNX core when available. |
| `FALLBACK_TO_PYTHON` | `true` | Fall back to MediaPipe when C++ is unavailable. |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Optional Redis for shared sessions. |
| `POSE_MODEL_PATH` | `models/pose.onnx` | Pose ONNX model path. |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Server bind address/port. |

---

## Verification

1. Open the printed URL in a browser.
2. Tap **Start** and allow camera access.
3. You should see a neon skeleton overlay and live feedback.

To confirm the active backend:
```bash
curl http://<host>:8000/api/stats
# {"backend":"cpp", ...}
```
