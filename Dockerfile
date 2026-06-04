FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:1
ENV VNC_PASSWORD=boss123
ENV CUSTOMER_ID=default

# ============================================================
# 安装系统依赖
# ============================================================
RUN apt-get update && apt-get install -y \
    # 基础工具
    wget curl git vim \
    # Python
    python3 python3-pip python3-venv python3-tk \
    # Chrome
    gnupg \
    # 桌面环境
    xfce4 xfce4-terminal xterm \
    # VNC
    tigervnc-standalone-server tigervnc-common \
    # noVNC
    novnc websockify \
    # 图像处理
    scrot imagemagick \
    # 其他
    supervisor net-tools xclip \
    # OCR
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# 安装中文支持
# ============================================================
RUN apt-get update && apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei && \
    rm -rf /var/lib/apt/lists/*

# ============================================================
# 安装 Chromium (arm64/amd64兼容)
# ============================================================
RUN apt-get update && apt-get install -y \
    chromium-browser chromium-codecs-ffmpeg-extra \
    && rm -rf /var/lib/apt/lists/*

# 创建Chrome兼容快捷方式
RUN ln -sf /usr/bin/chromium-browser /usr/bin/chrome && \
    ln -sf /usr/bin/chromium-browser /usr/bin/google-chrome && \
    ln -sf /usr/bin/chromium-browser /usr/bin/google-chrome-stable

# ============================================================
# 安装Python依赖
# ============================================================
RUN pip3 install --no-cache-dir \
    pyautogui \
    opencv-python-headless \
    numpy \
    pillow \
    fastapi \
    uvicorn \
    python-multipart \
    requests \
    httpx \
    pytesseract \
    python-dotenv \
    nodriver \
    websockify \
    scikit-learn \
    scikit-image \
    aiofiles \
    websockets \
    python-jose \
    passlib \
    bcrypt \
    sqlalchemy \
    alembic \
    openpyxl \
    pandas

# ============================================================
# 设置工作目录
# ============================================================
WORKDIR /app

# 安装 Playwright + Chromium（arm64 兼容版本，替代 snap）
RUN pip3 install --no-cache-dir playwright && \
    python3 -m playwright install chromium && \
    CHROMIUM=$(find /root/.cache/ms-playwright -name "chrome" -type f 2>/dev/null | head -1) && \
    ln -sf "$CHROMIUM" /usr/bin/chromium-browser && \
    ln -sf "$CHROMIUM" /usr/bin/chrome && \
    ln -sf "$CHROMIUM" /usr/bin/google-chrome && \
    ln -sf "$CHROMIUM" /usr/bin/google-chrome-stable && \
    echo "✅ Playwright Chromium linked"

# 复制应用代码
COPY app/ /app/app/
COPY web/ /app/web/
COPY run_chat_and_resume.py /app/
COPY run_linux.py /app/
COPY test_nodriver.py /app/
COPY start.sh /app/
COPY stop.sh /app/

# ============================================================
# 配置VNC
# ============================================================
RUN mkdir -p ~/.vnc && \
    echo "$VNC_PASSWORD" | vncpasswd -f > ~/.vnc/passwd && \
    chmod 600 ~/.vnc/passwd

# VNC启动脚本
RUN echo '#!/bin/bash\n\
vncserver :1 -geometry 1920x1080 -depth 24\n\
startxfce4 &\n\
/usr/share/novnc/utils/launch.sh --vnc localhost:5901 --listen 6901' > /app/start-vnc.sh && \
    chmod +x /app/start-vnc.sh

# ============================================================
# 配置Supervisor
# ============================================================
RUN mkdir -p /var/log/supervisor

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# ============================================================
# 暴露端口
# ============================================================
EXPOSE 5901 6901 8001 3001

# ============================================================
# 启动脚本
# ============================================================
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
