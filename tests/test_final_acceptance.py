#!/usr/bin/env python3
"""
最终验收测试 - 所有30个API端点
100%通过率验收
"""
import requests
import json
from typing import Dict, List, Any

BASE_URL = "http://localhost:8321"
AUTH_TOKEN = None

# 端点列表（30个）
ENDPOINTS = [
    # 健康检查（2个）
    ("GET", "/health", "Public health check", False),
    ("GET", "/api/health", "API health check", False),

    # 认证（1个）
    ("POST", "/api/auth/login", "User login", False, {"username": "admin", "password": "admin123"}),

    # 浏览器控制（6个）
    ("GET", "/api/browser/status", "Get browser status", True),
    ("POST", "/api/browser/connect", "Connect browser", True, {"headless": False}),
    ("GET", "/api/browser/status", "Check browser connection", True),
    ("POST", "/api/browser/screenshot", "Take screenshot", True, {"full_page": False}),
    ("POST", "/api/browser/disconnect", "Disconnect browser", True),
    ("GET", "/api/browser/status", "Verify disconnection", True),

    # 自动化控制（3个）
    ("GET", "/api/automation/status", "Get automation status", True),
    ("POST", "/api/automation/start", "Start automation", True),
    ("POST", "/api/automation/stop", "Stop automation", True),

    # 数据查询（2个）
    ("GET", "/api/candidates", "Get candidates list", True),
    ("GET", "/api/stats", "Get statistics", True),

    # 简历管理（5个）
    ("GET", "/api/resume/status", "Get resume task status", True),
    ("GET", "/api/resume/list", "Get resume list", True),
    ("GET", "/api/resume/stats", "Get resume statistics", True),
    ("POST", "/api/resume/batch", "Batch download resumes", True, {"limit": 5}),
    ("GET", "/api/resume/download/1", "Download resume file", True),

    # 筛选功能（4个）
    ("GET", "/api/filter/config", "Get filter config", True),
    ("POST", "/api/filter/contact", "Start filter contact", True, {"daily_cap": 50}),

    # AI对话（5个）
    ("GET", "/api/chat/history", "Get chat history", True),
    ("GET", "/api/chat/templates", "Get chat templates", True),
    ("POST", "/api/chat/batch", "Batch reply messages", True, {"limit": 5}),
    ("GET", "/api/template/list", "Get template list", True),

    # 兼容端点（3个）
    ("POST", "/api/workflow/say-hello", "Say hello (legacy)", True, {"limit": 10}),
    ("POST", "/api/workflow/get-resumes", "Get resumes (legacy)", True, {"limit": 10}),
    ("POST", "/api/workflow/reply-messages", "Reply messages (legacy)", True, {"limit": 10}),
]

results = {
    "passed": 0,
    "failed": 0,
    "errors": [],
    "warnings": []
}

def make_request(method: str, path: str, data: Dict = None, need_auth: bool = False) -> tuple:
    """发送HTTP请求并返回结果"""
    global AUTH_TOKEN

    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}

    if need_auth and AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data if data else {}, timeout=10)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data if data else {}, timeout=10)
        else:
            return False, f"Unsupported method: {method}"

        # 检查状态码
        if response.status_code in [200, 202]:
            # 尝试解析JSON响应
            try:
                json_data = response.json()
                # 如果是登录端点，保存token
                if path == "/api/auth/login" and "access_token" in json_data:
                    AUTH_TOKEN = json_data["access_token"]
                return True, json_data
            except json.JSONDecodeError:
                return True, response.text
        elif response.status_code == 401:
            return False, "Unauthorized - 认证失败"
        elif response.status_code == 404:
            return False, "Not Found - 端点不存在"
        elif response.status_code == 405:
            return False, "Method Not Allowed - 方法不允许"
        elif response.status_code == 500:
            return False, f"Internal Server Error - {response.text[:200]}"
        else:
            return False, f"Unexpected status {response.status_code}: {response.text[:200]}"

    except requests.exceptions.Timeout:
        return False, "Timeout - 请求超时"
    except requests.exceptions.ConnectionError:
        return False, "Connection Error - 无法连接"
    except Exception as e:
        return False, f"Exception: {str(e)}"

def run_acceptance_test():
    """运行完整验收测试"""
    print("=" * 60)
    print("🎯 最终验收测试 - BOSS直聘三位一体系统")
    print("=" * 60)
    print()

    for i, (method, path, description, need_auth, *args) in enumerate(ENDPOINTS, 1):
        data = args[0] if args else None

        print(f"[{i:2d}/30] {method:4s} {path:35s} | {description}")

        success, result = make_request(method, path, data, need_auth)

        if success:
            results["passed"] += 1
            print(f"       ✅ PASS")
        else:
            results["failed"] += 1
            results["errors"].append({
                "endpoint": f"{method} {path}",
                "error": result
            })
            print(f"       ❌ FAIL: {result}")

    print()
    print("=" * 60)
    print("📊 验收结果")
    print("=" * 60)
    print(f"✅ 通过: {results['passed']}/30 ({results['passed']/30*100:.1f}%)")
    print(f"❌ 失败: {results['failed']}/30")

    if results["errors"]:
        print()
        print("❌ 失败详情:")
        for error in results["errors"]:
            print(f"  - {error['endpoint']}: {error['error']}")

    print()
    pass_rate = results["passed"] / 30 * 100
    if pass_rate == 100:
        print("🎉 验收通过！100% 通过率")
    elif pass_rate >= 90:
        print("✅ 基本通过，需修复少量问题")
    else:
        print("❌ 验收未通过，需要修复")

    print("=" * 60)

    return pass_rate == 100

if __name__ == "__main__":
    success = run_acceptance_test()
    exit(0 if success else 1)