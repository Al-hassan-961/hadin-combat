# ---------------------------------------------------------------------------
# HADIN-COMBAT – Python backend Dockerfile
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Python dependencies layer (cached first)
COPY python-backend/requirements.txt /build/requirements.txt
COPY python-backend/requirements-optional.txt /build/requirements-optional.txt
# numpy + OpenCV are system-class deps; on Linux the container installs them
# via wheels (they are intentionally NOT in requirements.txt, so pip never
# builds them from source on Android).
RUN pip install --prefix=/install -r /build/requirements.txt \
    && pip install --prefix=/install "numpy>=1.24" "opencv-python>=4.8" \
    && pip install --prefix=/install -r /build/requirements-optional.txt || true

# ---- Runtime image ---------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    # The container image does NOT ship the compiled C++ core or .onnx models
    # (only model READMEs + pybind sources), so the Python-only pipeline is the
    # active engine. Pose degrades C++->MediaPipe->OpenCV automatically; to use
    # the C++ core, build cpp/ and mount models/ at runtime, then set true.
    USE_CPP_CORE=${USE_CPP_CORE:-false} \
    FALLBACK_TO_PYTHON=true \
    REDIS_URL=

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local
COPY python-backend/ /app/
COPY website/ /app/static/
COPY models/ /app/models/

# Persistent session history / uploads / preferences (bind a volume).
ENV HADIN_DATA_DIR=/app/data
RUN mkdir -p /app/data/uploads /app/data
VOLUME ["/app/data"]

EXPOSE 8000

# Python-first engine; graceful fallback C++ -> MediaPipe -> OpenCV motion.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
