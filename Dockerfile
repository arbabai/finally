# Stage 1: Build Next.js static export
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy backend project files and install dependencies
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --frozen

# Copy backend source code
COPY backend/ ./

# Copy frontend static export (Next.js output: 'export' produces out/)
COPY --from=frontend-builder /app/frontend/out ./static

# Create db directory for SQLite volume mount
RUN mkdir -p /app/db

# Set explicit DB path so the backend writes to the volume-mounted directory
ENV DB_PATH=/app/db/finally.db

EXPOSE 8000

# Single worker required: PriceCache and market_source are in-memory per-process.
# Multiple workers would give each worker an independent cache, breaking SSE and API consistency.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
