# Multi-stage Dockerfile for Ad System Architecture
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_CACHE_DIR=/tmp/uv-cache

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Development stage
FROM base as development

# Install development dependencies
RUN uv sync --frozen

# Copy source code
COPY . .

# Expose ports for all services
EXPOSE 8001 8002 8003 8004 8005

# Default command for development
CMD ["python", "scripts/start_services.py"]

# Production stage
FROM base as production

# Copy source code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

# Default command for production
CMD ["python", "scripts/start_services.py"]