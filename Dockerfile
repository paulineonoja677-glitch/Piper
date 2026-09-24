FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIPER_MODEL_DIR=/app/voices

# espeak-ng: required by Piper for phonemization.
# libsndfile1 / ffmpeg: audio codec support used by some Piper voice pipelines.
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng \
        libespeak-ng1 \
        ffmpeg \
        libsndfile1 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN mkdir -p /app/voices

# Render sets $PORT at runtime; 10000 is Render's default for web services.
ENV PORT=10000
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-10000}/health || exit 1

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]

