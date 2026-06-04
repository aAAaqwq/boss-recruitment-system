#!/bin/bash
# 容器启动脚本

set -e

echo "========================================"
echo "🚀 BOSS直聘三位一体系统 - Docker启动"
echo "========================================"

# 设置VNC密码
if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p ~/.vnc
    echo "$VNC_PASSWORD" | vncpasswd -f > ~/.vnc/passwd
    chmod 600 ~/.vnc/passwd
fi

# 清理旧的锁文件
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 2>/dev/null || true
rm -f ~/.vnc/*.pid 2>/dev/null || true

# 启动VNC服务器
echo "📺 启动VNC服务器..."
vncserver :1 -geometry 1920x1080 -depth 24 -localhost no

# 等待VNC启动
sleep 2

# 启动桌面环境
echo "🖥️ 启动桌面环境..."
startxfce4 &

# 等待桌面启动
sleep 2

# 启动noVNC
echo "🌐 启动noVNC..."
/usr/share/novnc/utils/launch.sh --vnc localhost:5901 --listen 6901 &

# 启动Web API
echo "🔌 启动Web API..."
cd /app
python3 -m uvicorn app.api:app --host 0.0.0.0 --port 8001 &

# 启动Web管理界面 - 在/app目录下创建web目录
echo "📊 启动Web管理界面..."
mkdir -p /app/web

# 创建index.html文件
cat > /app/web/index.html << 'HTMLEOF'
<!DOCTYPE html>
<html>
<head>
    <title>BOSS直聘三位一体系统</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
            padding: 40px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { font-size: 2.5rem; margin-bottom: 10px; }
        .subtitle { color: #8892b0; margin-bottom: 40px; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 24px;
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.2s;
        }
        .card:hover { transform: translateY(-4px); }
        .card h3 { color: #00b0ff; margin-bottom: 12px; }
        .card p { color: #8892b0; margin-bottom: 16px; }
        .btn {
            display: inline-block;
            background: #00b0ff;
            color: white;
            padding: 10px 20px;
            border-radius: 6px;
            text-decoration: none;
            transition: background 0.2s;
        }
        .btn:hover { background: #0091ea; }
        .status {
            margin-top: 40px;
            padding: 20px;
            background: rgba(0,176,255,0.1);
            border-radius: 8px;
            border-left: 4px solid #00b0ff;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .status-item:last-child { border-bottom: none; }
        .badge {
            background: #00c853;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 BOSS直聘三位一体系统</h1>
        <p class="subtitle">AI驱动的自动化招聘解决方案</p>
        
        <div class="grid">
            <div class="card">
                <h3>🖥️ 远程桌面</h3>
                <p>通过浏览器直接访问容器内的桌面环境，查看Chrome运行状态</p>
                <a href="http://localhost:6901" class="btn" target="_blank">打开 noVNC</a>
            </div>
            <div class="card">
                <h3>📋 API 文档</h3>
                <p>查看和管理系统API接口，启动/停止自动化任务</p>
                <a href="http://localhost:8001/docs" class="btn" target="_blank">查看文档</a>
            </div>
            <div class="card">
                <h3>📊 监控面板</h3>
                <p>实时查看候选人处理进度、聊天状态、系统日志</p>
                <a href="http://localhost:8001/metrics" class="btn" target="_blank">查看指标</a>
            </div>
        </div>
        
        <div class="status">
            <h3 style="margin-bottom: 16px;">📡 系统状态</h3>
            <div class="status-item">
                <span>Web管理界面</span>
                <span class="badge">运行中</span>
            </div>
            <div class="status-item">
                <span>VNC服务器</span>
                <span class="badge">运行中</span>
            </div>
            <div class="status-item">
                <span>noVNC Web</span>
                <span class="badge">运行中</span>
            </div>
            <div class="status-item">
                <span>API服务</span>
                <span class="badge">运行中</span>
            </div>
        </div>
    </div>
</body>
</html>
HTMLEOF

# 在/app/web目录启动http.server
cd /app/web
python3 -m http.server 3001 &

echo ""
echo "========================================"
echo "✅ 系统已启动"
echo "========================================"
echo ""
echo "📺 VNC: localhost:5901"
echo "🌐 noVNC: http://localhost:6901"
echo "🔌 API: http://localhost:8001"
echo "📊 Web管理: http://localhost:3001"
echo ""
echo "========================================"

# 保持运行
tail -f /dev/null
