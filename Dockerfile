FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    STORAGE_DIR=/app/storage

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY tools/ ./tools/
COPY data/seed.json ./data/seed.json
COPY data/gildong_diaries_2026.json ./data/gildong_diaries_2026.json
COPY data/faces/ ./storage/faces/
COPY data/voice/reference.wav ./data/voice/reference.wav
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/storage

EXPOSE 8000

CMD ["python", "tools/start.py"]
