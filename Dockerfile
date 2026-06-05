FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:1
ENV CUSTOMER_ID=default
# VNC_PASSWORD / API_SECRET_KEY / API_PASSWORD 必须通过 docker-compose 传入

# ============================================================
# 系统依赖 (合并为1层，避免多次apt-get update)
# ============================================================
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

# 安装 Chromium 浏览器（通过 Playwright，支持 ARM64 + AMD64）
RUN pip3 install --no-cache-dir playwright && \
    python3 -m playwright install chromium --with-deps && \
    PLAYWRIGHT_CHROME=$(find /root/.cache/ms-playwright -name 'chrome' -o -name 'chromium' 2>/dev/null | head -1) && \
    ln -sf "$PLAYWRIGHT_CHROME" /usr/bin/google-chrome && \
    ln -sf "$PLAYWRIGHT_CHROME" /usr/bin/chrome && \
    ln -sf "$PLAYWRIGHT_CHROME" /usr/bin/chromium-browser && \
    echo "Chromium installed: $PLAYWRIGHT_CHROME"

# ============================================================
# Python 依赖 (先COPY requirements, 仅依赖变更时重建此层)
# ============================================================
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# ============================================================
# 应用代码 (频繁变更放最后，复用上面的层缓存)
# ============================================================
WORKDIR /app
COPY app/ /app/app/
COPY web/ /app/web/
COPY templates/ /app/templates/
COPY static/ /app/static/
COPY boss.py /app/
COPY config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    mkdir -p ~/.vnc /var/log/supervisor

EXPOSE 5901 6901 8001 3001 3000
ENTRYPOINT ["/entrypoint.sh"]
