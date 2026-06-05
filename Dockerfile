# syntax=docker/dockerfile:1.4
# ============================================================
# Multi-stage Dockerfile for BOSS Recruitment System
# Stage 1 (deps)    : System packages + pip dependencies
# Stage 2 (browser) : Playwright Chromium + symlinks
# Stage 3 (runtime) : Final image with app code
# ============================================================

# ----------------------
# Stage 1: deps
# - System apt packages (rarely change, cached longest)
# - pip dependencies via requirements.txt
# ----------------------
FROM ubuntu:22.04 AS deps

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl git vim \
    python3 python3-pip python3-venv python3-tk \
    gnupg ca-certificates \
    dbus-x11 \
    xfce4 xfce4-terminal xterm \
    tigervnc-standalone-server tigervnc-common tigervnc-tools \
    novnc websockify \
    scrot imagemagick \
    supervisor net-tools xclip \
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
    fonts-wqy-zenhei fonts-wqy-microhei \
    xdotool \
    && rm -rf /var/lib/apt/lists/*

# pip dependencies as a separate layer (changes less than app code)
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ----------------------
# Stage 2: browser
# - Playwright Chromium (very heavy, rarely changes)
# ----------------------
FROM deps AS browser

RUN pip3 install --no-cache-dir playwright && \
    python3 -m playwright install chromium --with-deps && \
    PLAYWRIGHT_CHROME=$(find /root/.cache/ms-playwright -name 'chrome' -o -name 'chromium' 2>/dev/null | head -1) && \
    ln -sf "$PLAYWRIGHT_CHROME" /usr/bin/google-chrome && \
    ln -sf "$PLAYWRIGHT_CHROME" /usr/bin/chrome && \
    ln -sf "$PLAYWRIGHT_CHROME" /usr/bin/chromium-browser && \
    echo "Chromium installed: $PLAYWRIGHT_CHROME"

# ----------------------
# Stage 3: runtime
# - Final image: copy everything from browser stage, add app code
# ----------------------
FROM browser AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:1
ENV CUSTOMER_ID=default
ENV PYTHONUNBUFFERED=1
# VNC_PASSWORD / API_SECRET_KEY / API_PASSWORD must be passed via docker-compose

WORKDIR /app

# Application code (changes most often, layered last for cache reuse)
COPY app/ /app/app/
COPY web/ /app/web/
COPY templates/ /app/templates/
COPY static/ /app/static/
COPY boss.py /app/
COPY config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    mkdir -p ~/.vnc /var/log/supervisor

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

EXPOSE 5901 6901 8001 3001 3000
ENTRYPOINT ["/entrypoint.sh"]
