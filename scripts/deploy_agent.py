#!/usr/bin/env python3
"""
部署 Agent: Docker 清理 → 构建 → 启动 → 健康检查
调用于 workflow stage 0_deploy，也可独立运行
"""
import subprocess
import sys
import time
import json
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
COMPOSE_FILE = "docker-compose.yml"
CONTAINER_NAME = "boss-recruitment-pro"

SERVICES = {
    "web": "http://localhost:8321/index.html",
    "novnc": "http://localhost:6901",
    "api": "http://localhost:8001",
}

CHECK_INTERVAL = 3
MAX_WAIT = 90


def run(cmd: list[str], description: str) -> bool:
    print(f"\n[DEPLOY] {description}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[FAIL] {description}\nSTDERR: {result.stderr}")
        return False
    print(f"[OK] {description}")
    return True


def clean_old_containers() -> bool:
    ok = run(
        ["docker-compose", "-f", COMPOSE_FILE, "down", "--remove-orphans"],
        "docker-compose down --remove-orphans"
    )
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
    return ok


def build_and_start() -> bool:
    return run(
        ["docker-compose", "-f", COMPOSE_FILE, "up", "-d", "--build"],
        "docker-compose up -d --build"
    )


def health_check() -> dict:
    print(f"\n[DEPLOY] 健康检查 (max {MAX_WAIT}s)...")
    results = {}
    all_healthy = True
    for name, url in SERVICES.items():
        healthy = False
        for attempt in range(1, MAX_WAIT // CHECK_INTERVAL + 1):
            try:
                req = urllib.request.Request(url, method="HEAD")
                resp = urllib.request.urlopen(req, timeout=5)
                if resp.status < 500:
                    healthy = True
                    print(f"  [{attempt * CHECK_INTERVAL}s] {name}: {resp.status}")
                    break
            except Exception:
                pass
            time.sleep(CHECK_INTERVAL)
        if not healthy:
            print(f"  [TIMEOUT] {name}: FAIL")
            all_healthy = False
        results[name] = {"url": url, "healthy": healthy}
    return {"all_healthy": all_healthy, "services": results}


def get_container_status() -> dict:
    result = subprocess.run(
        ["docker", "inspect", CONTAINER_NAME],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        info = json.loads(result.stdout)[0]
        return {
            "id": info["Id"][:12],
            "status": info["State"]["Status"],
            "started_at": info["State"]["StartedAt"],
        }
    return {"status": "not_found"}


def main():
    print("=" * 60)
    print("  BOSS直聘 - 部署 Agent")
    print("=" * 60)

    clean_old_containers()

    if not build_and_start():
        print("\n[FATAL] 构建失败")
        sys.exit(1)

    health = health_check()
    container = get_container_status()

    report = {
        "status": "healthy" if health["all_healthy"] else "partial",
        "container": container,
        "services": health["services"],
        "project_dir": str(PROJECT_DIR),
    }

    report_path = PROJECT_DIR / ".claude" / "deploy_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[DEPLOY] 报告: {report_path}")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if health["all_healthy"]:
        print("\n 部署完成，所有服务正常！")
        sys.exit(0)
    else:
        print("\n 部分服务不健康")
        sys.exit(1)


if __name__ == "__main__":
    main()
