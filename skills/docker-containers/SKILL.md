---
name: docker-containers
description: |
  Docker, containers, Dockerfile, docker-compose, images, volumes,
  networking, multi-stage builds, container optimization, debugging,
  registry, deployment, orchestration, container security.

  Trigger phrases: docker, container, Dockerfile, docker-compose,
  build image, run container, docker volume, docker network,
  multi-stage build, optimize image, container logs, docker exec,
  push image, pull image, container debugging, docker ps.
---

# Docker & Containers

Tools for containerization workflows.

## Primary Tools

### docker-analyzer Agent
```bash
Task(subagent_type="docker-analyzer", prompt="Analyze Dockerfile at <path>")
```
Security issues, size optimization, layer caching analysis.

## Docker Commands

### Container Management
```bash
# Run container
docker run -d -p 3000:3000 --name myapp image:tag

# List containers
docker ps -a

# Stop/Remove
docker stop myapp && docker rm myapp

# Logs
docker logs -f myapp

# Shell into container
docker exec -it myapp /bin/sh
```

### Image Management
```bash
# Build
docker build -t myapp:latest .

# List images
docker images

# Remove
docker rmi image:tag

# Push to registry
docker push registry/myapp:latest
```

## Dockerfile Best Practices

### Multi-stage Build
```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/index.js"]
```

### Layer Optimization
```dockerfile
# Good: Dependencies cached separately
COPY package*.json ./
RUN npm ci
COPY . .

# Bad: Cache invalidated on any change
COPY . .
RUN npm ci
```

### Security
```dockerfile
# Run as non-root
RUN adduser -D appuser
USER appuser

# Use specific versions
FROM node:20.10-alpine

# Don't include secrets in image
# Use build args or runtime env vars
```

## Docker Compose

```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgres://db:5432
    depends_on:
      - db
  db:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### Commands
```bash
docker-compose up -d      # Start
docker-compose down       # Stop
docker-compose logs -f    # Logs
docker-compose exec app sh  # Shell
```

## Debugging

```bash
# Container processes
docker top myapp

# Resource usage
docker stats

# Inspect container
docker inspect myapp

# Check why container exited
docker logs myapp --tail 100
```

## Image Size Reduction

- Use Alpine base images
- Multi-stage builds
- Remove dev dependencies
- Clean package manager cache
- Use .dockerignore
