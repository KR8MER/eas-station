# syntax=docker/dockerfile:1
# Using Python 3.11 to match Debian bookworm's python3-soapysdr bindings
FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies required for psycopg2, GeoAlchemy, and SoapySDR
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        ffmpeg \
        espeak \
        libespeak-ng1 \
        ca-certificates \
        libusb-1.0-0 \
        libusb-1.0-0-dev \
        python3-soapysdr \
        soapysdr-module-rtlsdr \
        soapysdr-module-airspy \
        soapysdr-tools \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create and set working directory
WORKDIR /app

# Install Python dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source into the image
COPY . ./

# Copy and set up the entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose default Flask port and start Gunicorn
EXPOSE 5000

ENTRYPOINT ["docker-entrypoint.sh"]

CMD ["gunicorn", \
    "--bind", "0.0.0.0:5000", \
    "--workers", "4", \
    "--timeout", "120", \
    "--worker-class", "sync", \
    "--worker-tmp-dir", "/dev/shm", \
    "--log-level", "info", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "app:app"]
