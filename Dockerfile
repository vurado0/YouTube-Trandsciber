# Transcript Study — container image for a persistent host (Fly.io, Railway, Render).
#
# Build with offline transcription included:
#   docker build --build-arg WITH_WHISPER=1 -t transcript-study .
FROM python:3.12-slim

ARG WITH_WHISPER=0

# ffmpeg does the audio conversion for MP3 export and for Whisper.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-whisper.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$WITH_WHISPER" = "1" ]; then pip install --no-cache-dir -r requirements-whisper.txt; fi

COPY backend/ backend/
COPY frontend/ frontend/

# Writable scratch space for cached transcripts and prepared downloads.
ENV WORK_DIR=/data
RUN mkdir -p /data && useradd -m -u 10001 app && chown -R app /data /app
USER app

# Shared-instance defaults. Override per deployment.
ENV PORT=8000 \
    TRUST_PROXY=1 \
    ENABLE_WHISPER=0 \
    ENABLE_DOWNLOADS=0 \
    MAX_CONCURRENT_JOBS=2 \
    RATE_LIMIT_PER_HOUR=40 \
    MAX_DURATION_SECONDS=2700

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app:app --app-dir backend --host 0.0.0.0 --port ${PORT}"]
