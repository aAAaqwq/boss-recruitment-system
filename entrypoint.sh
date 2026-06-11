#!/bin/bash
set -e

echo "========================================"
echo "🚀 BOSS直聘三位一体系统 - Docker启动"
echo "========================================"

# VNC密码 + xstartup 配置
mkdir -p ~/.vnc
if [ -n "$VNC_PASSWORD" ]; then
    echo "$VNC_PASSWORD" | tigervncpasswd -f > ~/.vnc/passwd
    chmod 600 ~/.vnc/passwd
fi

# 创建 xstartup 确保 XFCE 正确启动
cat > ~/.vnc/xstartup << 'XEOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
XEOF
chmod +x ~/.vnc/xstartup

# 清理旧锁文件
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true
rm -f ~/.vnc/*.pid 2>/dev/null || true

# VNC + 桌面 + noVNC
echo "📺 VNC + XFCE + noVNC..."
# 确保 DBus 系统总线运行（XFCE 依赖 dbus-launch 启动会话）
service dbus start 2>/dev/null || dbus-daemon --system --fork
sleep 1
# VNC server: 使用 VncAuth 认证，密码由前端通过 noVNC ?password= 参数自动传递
vncserver :1 -geometry 1920x1080 -depth 24 -localhost no
sleep 3
# noVNC: 优先使用 launch.sh，回退到直接 websockify
if [ -x /usr/share/novnc/utils/launch.sh ]; then
    /usr/share/novnc/utils/launch.sh --vnc localhost:5901 --listen 6901 &
else
    websockify --web=/usr/share/novnc 6901 localhost:5901 &
fi

# Dashboard (templates/index.html → port 3000 → 外部8321)
echo "📊 Dashboard: http://localhost:8321"
mkdir -p /app/dashboard
# 符号链接使 volume 挂载的模板变更实时生效
ln -sf /app/templates/index.html /app/dashboard/index.html
# 复制 noVNC JS（http.server 不跟踪 symlink）
cp -r /usr/share/novnc /app/dashboard/novnc
cd /app/dashboard
python3 -m http.server 3000 &

# Hub/总台 (web/index.html → port 3001 → 外部3101)
echo "🏠 Hub: http://localhost:3101"
cd /app/web
python3 -m http.server 3001 &

# API服务
echo "🔌 API: http://localhost:8001"
mkdir -p /app/data/chrome-profile

# 清理 Chrome 持久化 profile 中跨容器残留的陈旧 SingletonLock
# 持久化 ./data 会把上个容器的锁带到新容器; 主机名不匹配时 Chrome 拒绝回收 → CDP 端口超时
PROFILE_DIR="${CHROME_PROFILE_DIR:-/app/data/chrome-profile}"
if [ -L "$PROFILE_DIR/SingletonLock" ]; then
    target="$(readlink "$PROFILE_DIR/SingletonLock" 2>/dev/null || true)"
    lock_host="${target%-*}"   # <hostname>-<pid> → hostname
    lock_pid="${target##*-}"   # → pid
    if [ -n "$target" ] && [ "$lock_host" != "$(hostname)" ]; then
        echo "🧹 Chrome: 清理陈旧 SingletonLock (他机 $lock_host ≠ 当前 $(hostname))"
        rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonCookie" "$PROFILE_DIR/SingletonSocket"
    elif [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
        echo "🧹 Chrome: 清理陈旧 SingletonLock (PID $lock_pid 已退出)"
        rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonCookie" "$PROFILE_DIR/SingletonSocket"
    else
        echo "ℹ️  Chrome: SingletonLock 持有者存活 (PID $lock_pid), 保留"
    fi
fi

cd /app
python3 -m uvicorn app.api:app --host 0.0.0.0 --port 8001 &

echo ""
echo "========================================"
echo "✅ 系统已启动"
echo "========================================"
echo "🏠 Hub:      http://localhost:3101"
echo "📊 Dashboard: http://localhost:8321"
echo "🌐 noVNC:    http://localhost:6901"
echo "🔌 API:      http://localhost:8001/docs"
echo "📺 VNC:      localhost:5901"
echo "========================================"

tail -f /dev/null
