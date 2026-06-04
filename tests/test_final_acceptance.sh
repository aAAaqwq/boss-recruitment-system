#!/bin/bash
# 最终验收测试 - 所有30个API端点
# 100%通过率验收

BASE_URL="http://localhost:8321"
TOKEN=""
PASSED=0
FAILED=0
ERRORS=()

echo "=================================================="
echo "🎯 最终验收测试 - BOSS直聘三位一体系统"
echo "=================================================="
echo ""

# 测试计数器
TEST_NUM=1

# 测试函数
test_endpoint() {
    local method=$1
    local path=$2
    local description=$3
    local need_auth=$4
    local data=$5

    echo "[$TEST_NUM/30] $method $path | $description"

    local url="$BASE_URL$path"
    local response=""
    local status_code=""

    if [ "$need_auth" = "true" ] && [ -n "$TOKEN" ]; then
        if [ "$method" = "GET" ]; then
            response=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $TOKEN" "$url")
        elif [ "$method" = "POST" ]; then
            response=$(curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$data" "$url")
        fi
    else
        if [ "$method" = "GET" ]; then
            response=$(curl -s -w "\n%{http_code}" "$url")
        elif [ "$method" = "POST" ]; then
            response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/json" -d "$data" "$url")
        fi
    fi

    # 提取状态码
    status_code=$(echo "$response" | tail -n -1)
    local body=$(echo "$response" | head -n -1)

    # 检查状态码
    if [ "$status_code" = "200" ] || [ "$status_code" = "202" ]; then
        # 如果是登录端点，保存token
        if [ "$path" = "/api/auth/login" ]; then
            TOKEN=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null || echo "")
            echo "       ✅ PASS (Token: ${TOKEN:0:20}...)"
        else
            echo "       ✅ PASS"
        fi
        ((PASSED++))
    else
        echo "       ❌ FAIL: HTTP $status_code"
        ERRORS+=("[$method $path] HTTP $status_code")
        ((FAILED++))
    fi

    ((TEST_NUM++))
    sleep 0.1  # 避免过快请求
}

# 1. 健康检查（2个）
test_endpoint "GET" "/health" "Public health check" "false"
test_endpoint "GET" "/api/health" "API health check" "false"

# 2. 认证（1个）
test_endpoint "POST" "/api/auth/login" "User login" "false" '{"username":"admin","password":"admin123"}'

# 3. 浏览器控制（6个）
test_endpoint "GET" "/api/browser/status" "Get browser status" "true"
test_endpoint "POST" "/api/browser/connect" "Connect browser" "true" '{"headless":false}'
test_endpoint "GET" "/api/browser/status" "Check browser connection" "true"
test_endpoint "POST" "/api/browser/screenshot" "Take screenshot" "true" '{"full_page":false}'
test_endpoint "POST" "/api/browser/disconnect" "Disconnect browser" "true"
test_endpoint "GET" "/api/browser/status" "Verify disconnection" "true"

# 4. 自动化控制（3个）
test_endpoint "GET" "/api/automation/status" "Get automation status" "true"
test_endpoint "POST" "/api/automation/start" "Start automation" "true"
test_endpoint "POST" "/api/automation/stop" "Stop automation" "true"

# 5. 数据查询（2个）
test_endpoint "GET" "/api/candidates" "Get candidates list" "true"
test_endpoint "GET" "/api/stats" "Get statistics" "true"

# 6. 简历管理（5个）
test_endpoint "GET" "/api/resume/status" "Get resume task status" "true"
test_endpoint "GET" "/api/resume/list" "Get resume list" "true"
test_endpoint "GET" "/api/resume/stats" "Get resume statistics" "true"
test_endpoint "POST" "/api/resume/batch" "Batch download resumes" "true" '{"limit":5}'
test_endpoint "GET" "/api/resume/download/1" "Download resume file" "true"

# 7. 筛选功能（4个）
test_endpoint "GET" "/api/filter/config" "Get filter config" "true"
test_endpoint "POST" "/api/filter/contact" "Start filter contact" "true" '{"daily_cap":50}'

# 8. AI对话（5个）
test_endpoint "GET" "/api/chat/history" "Get chat history" "true"
test_endpoint "GET" "/api/chat/templates" "Get chat templates" "true"
test_endpoint "POST" "/api/chat/batch" "Batch reply messages" "true" '{"limit":5}'
test_endpoint "GET" "/api/template/list" "Get template list" "true"

# 9. 兼容端点（3个）
test_endpoint "POST" "/api/workflow/say-hello" "Say hello (legacy)" "true" '{"limit":10}'
test_endpoint "POST" "/api/workflow/get-resumes" "Get resumes (legacy)" "true" '{"limit":10}'
test_endpoint "POST" "/api/workflow/reply-messages" "Reply messages (legacy)" "true" '{"limit":10}'

echo ""
echo "=================================================="
echo "📊 验收结果"
echo "=================================================="
PASS_RATE=$(echo "scale=1; $PASSED/30*100" | bc)
echo "✅ 通过: $PASSED/30 ($PASS_RATE%)"
echo "❌ 失败: $FAILED/30"

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo ""
    echo "❌ 失败详情:"
    for error in "${ERRORS[@]}"; do
        echo "  - $error"
    done
fi

echo ""
if (( $(echo "$PASS_RATE == 100" | bc -l) )); then
    echo "🎉 验收通过！100% 通过率"
    echo "=================================================="
    exit 0
elif (( $(echo "$PASS_RATE >= 90" | bc -l) )); then
    echo "✅ 基本通过，需修复少量问题"
    echo "=================================================="
    exit 1
else
    echo "❌ 验收未通过，需要修复"
    echo "=================================================="
    exit 1
fi