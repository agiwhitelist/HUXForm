# ============================
# Stage 1: API Build
# ============================
FROM python:3.11-slim AS api

WORKDIR /app/apps/api

# Install dependencies
COPY apps/api/pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy source
COPY apps/api/src ./src

EXPOSE 8001

# ============================
# Stage 2: Web Build
# ============================
FROM node:20-alpine AS web

WORKDIR /app/apps/web

COPY apps/web/package*.json ./
RUN npm ci

COPY apps/web/ ./

# Build for production
RUN npm run build

# ============================
# Stage 3: Production
# ============================
FROM python:3.11-slim AS production

# Install nginx
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Copy API
COPY --from=api /app/apps/api ./apps/api
WORKDIR /app/apps/api
RUN pip install --no-cache-dir -e .

# Copy web build
COPY --from=web /app/apps/web/dist ./apps/web/dist

# Copy nginx config
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80 8001

CMD ["sh", "-c", "nginx && uvicorn src.main:app --host 0.0.0.0 --port 8001"]
