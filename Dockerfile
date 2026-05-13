# syntax=docker/dockerfile:1.6
#
# AGUI image. Multi-stage:
#   api  — Python backend (FastAPI / uvicorn)
#   web  — Vite build of the React shell
#   prod — nginx serves /, proxies /api -> uvicorn on :8001

FROM python:3.11-slim AS api
WORKDIR /app/apps/api
COPY apps/api/pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY apps/api/src ./src
EXPOSE 8001
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]

FROM node:20-alpine AS web
WORKDIR /app/apps/web
COPY apps/web/package*.json ./
RUN npm install --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM python:3.11-slim AS production
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=api /app/apps/api ./apps/api
RUN pip install --no-cache-dir -e ./apps/api
COPY --from=web /app/apps/web/dist ./apps/web/dist
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80 8001
CMD ["sh", "-c", "nginx && uvicorn --app-dir ./apps/api src.main:app --host 0.0.0.0 --port 8001"]
