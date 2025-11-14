# syntax=docker/dockerfile:1
# Using Python 3.11 to match Debian bookworm's python3-soapysdr bindings
FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Allow callers to limit which SoapySDR hardware drivers are installed
# (comma-separated list such as "rtlsdr" or "rtlsdr,airspy").
ARG SOAPYSDR_DRIVERS="rtlsdr,airspy"

# Capture git commit hash at build time
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Install system dependencies required for psycopg2, GeoAlchemy, and SoapySDR
RUN --mount=type=cache,target=/var/lib/apt \
    --mount=type=cache,target=/var/cache/apt \
    set -eux; \
    apt-get update; \
    set -- build-essential \
        libpq-dev \
        ffmpeg \
        espeak \
        libespeak-ng1 \
        ca-certificates \
        libusb-1.0-0 \
        libusb-1.0-0-dev \
        python3-soapysdr \
        soapysdr-tools \
        smartmontools; \
    if [ -n "$SOAPYSDR_DRIVERS" ]; then \
        IFS=','; \
        for driver in $SOAPYSDR_DRIVERS; do \
            driver="$(printf '%s' "$driver" | tr -d '[:space:]')"; \
            if [ -n "$driver" ]; then \
                set -- "$@" "soapysdr-module-$driver"; \
            fi; \
        done; \
        unset IFS; \
    fi; \
    apt-get install -y --no-install-recommends "$@"; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/*

# Fix Python binding visibility for SoapySDR
# Debian's python3-soapysdr installs to /usr/lib/python3/dist-packages
# but /usr/local/bin/python3 doesn't search this path by default
RUN mkdir -p /usr/local/lib/python3.11/site-packages \
    && echo '/usr/lib/python3/dist-packages' > /usr/local/lib/python3.11/site-packages/_deb_distpackages.pth

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
    "--workers", "1", \
    "--threads", "2", \
    "--timeout", "300", \
    "--worker-class", "gthread", \
    "--worker-tmp-dir", "/dev/shm", \
    "--log-level", "info", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "app:app"]
