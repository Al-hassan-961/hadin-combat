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
    USE_CPP_CORE=${USE_CPP_CORE:-true} \
    FALLBACK_TO_PYTHON=${FALLBACK_TO_PYTHON:-true} \
    REDIS_URL=redis://redis:6379/0

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local
COPY python-backend/ /app/
COPY website/ /app/static/
COPY models/ /app/models/

EXPOSE 8000

# Prefer the C++ core when built; gracefully falls back to MediaPipe.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
