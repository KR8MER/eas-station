# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG REPO_URL
ARG REPO_REF=main

# Install system dependencies required for psycopg2, GeoAlchemy, and git
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone the NOAA Alerts repository inside the image. Providing REPO_URL is
# required so the build knows which remote to fetch.
RUN if [ -z "$REPO_URL" ]; then \
        echo "ERROR: Provide --build-arg REPO_URL=<git repository URL>"; \
        exit 1; \
    fi; \
    git clone --depth=1 --branch "$REPO_REF" "$REPO_URL" /app \
    && rm -rf /app/.git

# Create and set working directory
WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose default Flask port
EXPOSE 5000

# Default environment variables
ENV FLASK_APP=app.py \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=5000

# Use Gunicorn for production-ready serving
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
