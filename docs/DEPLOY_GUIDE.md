# BOSS直聘三位一体系统 - 部署指南

## 快速开始

```bash
cd ~/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system/
docker-compose up -d
```

## 访问地址

| 服务 | URL |
|------|-----|
| Web管理 | http://localhost:3101 |
| noVNC | http://localhost:6901 |
| API文档 | http://localhost:8001/docs |
| API | http://localhost:8001 |
| VNC | vnc://localhost:5901 |

## 多客户部署 (方案A)

```bash
# 启动所有客户实例
docker-compose -f docker-compose.multi.yml up -d

# 查看状态
docker-compose -f docker-compose.multi.yml ps
```

| 客户 | Web | noVNC | API |
|------|-----|-------|-----|
| 客户A | 3101 | 6901 | 8001 |
| 客户B | 3102 | 6902 | 8002 |
| 客户C | 3103 | 6903 | 8003 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 系统信息 |
| GET | `/health` | 健康检查 |
| GET | `/api/automation/status` | 自动化状态 |
| POST | `/api/automation/start` | 启动自动化 |
| POST | `/api/automation/stop` | 停止自动化 |
| GET | `/api/candidates` | 候选人列表 |
| POST | `/api/candidates` | 添加候选人 |
| GET | `/api/candidates/{id}` | 候选人详情 |
| PUT | `/api/candidates/{id}/status` | 更新状态 |

## 停止服务

```bash
docker-compose down
```
