# ---- Stage 1: build the React /home bundle (frontend/) ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: application image ----
# Lightweight image for local development/testing
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system deps for Playwright and audio processing if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt; fi

COPY . /app
# frontend/ is the single source dir for all frontend files; the backend
# serves this build output directly (config.FRONTEND_DIST_DIR) - see the
# repo README's "Frontend" section.
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["uvicorn", "voice_transcriber.server:app", "--host", "0.0.0.0", "--port", "8000"]