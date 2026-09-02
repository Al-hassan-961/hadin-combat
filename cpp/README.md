# HADIN-COMBAT C++ Core

The C++17 core (`libhadin_core.so`) delivers sub-50ms ONNX Runtime inference
for pose estimation, style encoding, opponent generation, and co-evolution.
It is exposed to Python through **pybind11**.

```
cpp/
├── CMakeLists.txt
├── include/
│   ├── PoseEstimator.hpp
│   ├── StyleEncoder.hpp
│   ├── OpponentGenerator.hpp
│   └── CoEvolution.hpp
└── src/
    ├── PoseEstimator.cpp
    ├── StyleEncoder.cpp
    ├── OpponentGenerator.cpp
    ├── CoEvolution.cpp
    └── bindings.cpp
```

## Prerequisites

- CMake ≥ 3.16
- A C++17 compiler (GCC ≥ 9, Clang ≥ 10)
- Python 3.10+ with development headers
- [ONNX Runtime](https://onnxruntime.ai/) (shared library + headers)
- [pybind11](https://pybind11.readthedocs.io/) ≥ 2.9

## Linux / macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install onnxruntime pybind11

cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

On macOS you may need `-DCMAKE_SYSTEM_PROCESSOR` left default and
`export ONNXRUNTIME_ROOT=$(python -c 'import onnxruntime,os;print(os.path.dirname(onnxruntime.__file__))')`.

## Android / Termux

```bash
pkg update -y && pkg install -y clang cmake python opencv onnxruntime
pip install pybind11
cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j4
```

The build automatically applies ARM64/NEON optimizations.

## Output

The build copies `hadin_core.so` into `../python-backend/app/` so the Starlette
server can import it as:

```python
import hadin_core  # numpy-backed bindings
```

> **Note:** If compilation fails, the backend transparently falls back to
> MediaPipe. See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
