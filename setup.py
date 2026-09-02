# ---------------------------------------------------------------------------
# HADIN-COMBAT – setup.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
#
# Installs the `app` package (python-backend/app). numpy and OpenCV are SYSTEM
# dependencies, never pip build dependencies: on Termux they come from the
# pre-built packages (`pkg install python-numpy python-opencv clang`), on
# Ubuntu CI from apt, and on desktop via the `.[native]` extra or the OS
# package manager. pip is therefore never asked to compile them.
# ---------------------------------------------------------------------------
import os
import sys

from setuptools import find_packages, setup

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
# Termux sets TERMUX_VERSION and exposes the Android data dir. We treat either
# (or sys.platform == "android") as Android/Termux.
# ---------------------------------------------------------------------------
def on_termux() -> bool:
    if os.environ.get("TERMUX_VERSION"):
        return True
    if os.path.isdir("/data/data/com.termux"):
        return True
    if sys.platform == "android":
        return True
    return False


def on_android() -> bool:
    return sys.platform == "android"


def native_from_os_packages() -> bool:
    """True when numpy/OpenCV should come from the OS package manager instead
    of pip. True on Termux (Android) and when HADIN_SYSTEM_OPENCV=1 is set
    (used on iSH/Alpine, where they are installed via `apk add py3-numpy
    py3-opencv`)."""
    if on_android() or on_termux():
        return True
    return os.environ.get("HADIN_SYSTEM_OPENCV", "").lower() in ("1", "true", "yes")


# Heavy Python packages that, on Termux, should come from `pkg` (pre-built
# binaries) rather than a pip source build.
HEAVY_TERMUX_PACKAGES = {
    "numpy": "python-numpy",
    "opencv-python": "python-opencv (or python-opencv-python)",
    "scipy": "python-scipy",
    "matplotlib": "python-matplotlib",
    "scikit-learn": "python-scikit-learn",
    "pandas": "python-pandas",
}


def install_requires() -> list:
    """Core dependencies (pure-Python wheels only).

    numpy and OpenCV are deliberately NOT listed here — they are SYSTEM
    dependencies provided by the OS package manager and must never be built
    by pip (on Android there are no ARM64 wheels for new Pythons, and a
    source build fails with ninja/highway_qsort errors):
      - Termux:     pkg install python-numpy python-opencv clang
      - Ubuntu CI:  apt install python3-numpy python3-opencv
      - Desktop:    pip install -e ".[native]"  (or your system manager)
    """
    if on_termux():
        _warn_heavy_packages()
    return [
        "fastapi>=0.110,<1",
        # Plain uvicorn (no [standard] extras) so no C/Rust extensions
        # (uvloop, httptools, watchfiles) are ever compiled. WebSockets are
        # served by the `websockets` package listed below.
        "uvicorn>=0.29,<1",
        "websockets>=12",
        "pybind11>=2.9",
        "python-dotenv>=1.0",
        "redis>=5",
        "python-multipart>=0.0.9",
    ]


def extras_require() -> dict:
    """Optional extras — nothing here is installed by default."""
    return {
        # Desktop convenience: system-class deps via wheels (never on Termux).
        "native": ["numpy>=1.24", "opencv-python>=4.8"],
        "mediapipe": ["mediapipe>=0.10"],
        "dev": ["pytest", "httpx", "ruff"],
    }


def _warn_heavy_packages() -> None:
    """On Termux, remind the user to install heavy native deps via `pkg`."""
    missing = []
    for mod, pkg in HEAVY_TERMUX_PACKAGES.items():
        try:
            __import__(mod.replace("opencv-python", "cv2"))
        except ImportError:
            missing.append(f"  - {mod:24} -> pkg install {pkg}")
    if missing:
        print("\n[HADIN] Termux detected. These native packages are provided by "
              "Termux's pre-built binaries (never pip-built):",
              file=sys.stderr)
        print("\n".join(missing), file=sys.stderr)
        print("\n[HADIN] Install them with:  pkg install python-numpy "
              "python-opencv clang   (add tur-repo first if needed)\n",
              file=sys.stderr)


setup(
    name="hadin-combat",
    version="1.0.0",
    description=(
        "HADIN-COMBAT: The AI Opponent That Learns Your Fighting DNA. "
        "Real-time martial-arts training with pose estimation, style "
        "fingerprinting, and an adaptive opponent."
    ),
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Al-hassan Shehade & Dina Balcheh",
    license="MIT",
    python_requires=">=3.10",
    packages=find_packages(where="python-backend"),
    package_dir={"": "python-backend"},
    install_requires=install_requires(),
    extras_require=extras_require(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: C++",
        "Operating System :: Android",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "Operating System :: Microsoft :: Windows",
        "Topic :: Games/Entertainment :: Simulation",
        "Topic :: Multimedia :: Video",
    ],
)
