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

> **Zero compilation:** numpy and OpenCV are **system dependencies** on Termux —
> installed via `pkg` pre-built binaries, **never** via `pip` (no ARM64 wheels
> for new Pythons; source builds fail with the ninja `highway_qsort` crash).

```bash
pkg update -y && pkg upgrade -y

# 0. (Optional) extra repos, then pre-built native binaries:
pkg install -y x11-repo tur-repo
pkg update
pkg install -y python-numpy python-opencv clang

# 1. Clone and run the one-command setup:
git clone https://github.com/Al-hassan-961/hadin-combat.git
cd hadin-combat
bash scripts/termux_quickstart.sh
```

The script creates a **`--system-site-packages` venv** (so the pkg-installed
numpy/OpenCV are visible), runs `pip install -e .` (setup.py never lists
numpy/OpenCV, so pip compiles nothing), writes `.env`, and starts the server.

### Manual alternative

```bash
pkg install -y python-numpy python-opencv clang
python -m venv --system-site-packages .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e .            # no numpy/OpenCV in install_requires (system deps)
cd python-backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## iSH (iOS / Alpine)

```bash
apk update
# Pre-built numpy + OpenCV:
apk add python3 py3-pip py3-numpy py3-opencv cmake make g++
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
| `GEMINI_COACH_MODE` | *(empty)* | `live` (real Gemini) or `simulate` (local demo). Empty = disabled. |
| `GEMINI_API_KEY` | *(empty)* | Google AI Studio key for live Gemini coaching. |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Gemini model used for live coaching. |

### Enabling the optional Gemini global-AI coach

The coach is **off by default** and the app works fully without it (local coach
only). To enable **live** Gemini coaching:

```bash
pip install -r python-backend/requirements-optional.txt   # adds google-genai
# then set in python-backend/.env:
#   GEMINI_COACH_MODE=live
#   GEMINI_API_KEY=<your Google AI Studio key>
#   GEMINI_MODEL=gemini-2.0-flash-exp
```

To demo the AI-coach UI/pipeline **without a key or network** (clearly labelled
as simulated):

```bash
# python-backend/.env:
#   GEMINI_COACH_MODE=simulate
```

On the training page, enable it with the **🤖 AI Coach** toggle. When no coach
is available the button is disabled and the local coach continues as normal.

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
