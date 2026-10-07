# syntax=docker/dockerfile:1
# Word Work – byggs helt på Chainguards Wolfi-baserade images.

# ---------- 1. Frontend ----------
FROM cgr.dev/chainguard/node:latest-dev AS frontend
USER root
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Rättigheter från värddatorn följer med vid COPY – gör allt läsbart för alla.
RUN npm run build \
 && chmod -R a+rX,go-w dist

# ---------- 2. Python-beroenden ----------
FROM cgr.dev/chainguard/python:latest-dev AS backend
USER root
WORKDIR /app
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && mkdir -p /data && chown 65532:65532 /data
COPY backend/app /app/app
COPY backend/resources /app/resources
# Containern kör som nonroot (65532). Filrättigheter från värden (t.ex. 600)
# följer med vid COPY, så normalisera dem här.
RUN chmod -R a+rX,go-w /app/app /app/resources /app/venv

# ---------- 3. Körning (distroless, kör som nonroot) ----------
FROM cgr.dev/chainguard/python:latest
WORKDIR /app
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WW_DATA_DIR=/data \
    WW_STATIC_DIR=/app/static
COPY --from=backend --chown=65532:65532 /app/venv /app/venv
COPY --from=backend --chown=65532:65532 /data /data
COPY --from=backend /app/app /app/app
COPY --from=backend /app/resources /app/resources
COPY --from=frontend /build/dist /app/static
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s \
  CMD ["/app/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"]
ENTRYPOINT ["/app/venv/bin/python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
