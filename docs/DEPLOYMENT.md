# Deployment Guide

## Docker Deployment

### Quick Start

```bash
# Development (with hot reload)
docker-compose up --build

# Production
docker-compose -f docker-compose.yml up --build -d
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| nginx   | 80   | Reverse proxy and static file server |
| api     | 8001 | FastAPI backend server |
| web     | 5173 | Vite dev server (development only) |

## Environment Variables

No environment variables are required for the default configuration. The application uses sensible defaults.

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYTHONUNBUFFERED` | `1` | Enable unbuffered Python output |

## Port Configuration

| External Port | Internal Port | Service |
|---------------|---------------|---------|
| 80            | 80            | Nginx reverse proxy |
| 8001          | 8001          | API (direct access) |
| 5173          | 5173          | Web dev server |

### Access Points

- **Web Application**: http://localhost
- **API Endpoint**: http://localhost/api/v1/
- **Health Check**: http://localhost/health

## Production Nginx Setup

The production Dockerfile builds a multi-stage image that combines the API, web build, and nginx into a single container.

```bash
# Build production image
docker build -t agui:latest --target production .

# Run production container
docker run -p 80:80 -p 8001:8001 agui:latest
```

### Nginx Configuration

The production nginx configuration (`nginx.conf`) provides:

- **Static file serving**: Serves web assets from `/app/apps/web/dist`
- **API proxy**: Routes `/api/` requests to the API service
- **WebSocket support**: Handles WebSocket upgrade headers
- **Health endpoint**: Proxies `/health` to the API

### Production Recommendations

1. **Use a reverse proxy** (nginx, Traefik) in front of the container if exposing publicly
2. **Enable HTTPS** via Let's Encrypt or a similar certificate provider
3. **Set up logging** to stdout/stderr for container log aggregation
4. **Configure resource limits** in container runtime (CPU, memory)

## Troubleshooting

### Container fails to start

```bash
# Check container logs
docker logs <container_name>

# Verify ports are not in use
netstat -an | grep 80
```

### API returns 502 Bad Gateway

- Ensure the API container is running and healthy
- Check that nginx can reach the API on port 8001
- Verify `proxy_pass` URL in nginx.conf matches API port

### Web assets not loading

- Ensure the web build completed successfully (`npm run build`)
- Verify `dist/` folder exists in the container at `/app/apps/web/dist`
- Check nginx `root` directive points to the correct path

### Hot reload not working (development)

- Verify volumes are mounted correctly: `./apps/api:/app/apps/api`
- Check that `npm run dev` is running in the web container
- Ensure host ports match container ports in docker-compose.yml

### Permission denied errors

```bash
# Fix volume permissions on Linux/macOS
sudo chown -R $(id -u):$(id -g) ./apps/api ./apps/web
```
