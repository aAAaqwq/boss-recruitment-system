#!/bin/bash
# 最终验收测试 - 简化版
BASE_URL="http://localhost:8321"
TOKEN=""

echo "🎯 最终验收测试 - BOSS直聘三位一体系统"
echo "=================================================="

# 第一步：登录并获取token
echo "[1/30] POST /api/auth/login | User login"
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "       ❌ FAIL: 无法获取认证令牌"
    exit 1
else
    echo "       ✅ PASS (Token: ${TOKEN:0:20}...)"
fi

# 测试函数
test_auth_endpoint() {
    local method=$1
    local path=$2
    local description=$3
    local data=$4
    local test_num=$5

    echo "[$test_num/30] $method $path | $description"

    local response=""
    local status_code=""

    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE_URL$path")
    elif [ "$method" = "POST" ]; then
        response=$(curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$data" "$BASE_URL$path")
    fi

    status_code=$(echo "$response" | tail -n -1)

    if [ "$status_code" = "200" ] || [ "$status_code" = "202" ]; then
        echo "       ✅ PASS"
        return 0
    else
        echo "       ❌ FAIL: HTTP $status_code"
        return 1
    fi
}

test_public_endpoint() {
    local method=$1
    local path=$2
    local description=$3
    local data=$4
    local test_num=$5

    echo "[$test_num/30] $method $path | $description"

    local response=""
    local status_code=""

    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$BASE_URL$path")
    elif [ "$method" = "POST" ]; then
        response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/json" -d "$data" "$BASE_URL$path")
    fi

    status_code=$(echo "$response" | tail -n -1)

    if [ "$status_code" = "200" ] || [ "$status_code" = "202" ]; then
        echo "       ✅ PASS"
        return 0
    else
        echo "       ❌ FAIL: HTTP $status_code"
        return 1
    fi
}

PASSED=1  # 已通过登录
FAILED=0
TEST_NUM=2

# 健康检查（2个）
test_public_endpoint "GET" "/health" "Public health check" "" "2" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_public_endpoint "GET" "/api/health" "API health check" "" "3" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# 浏览器控制（6个）
test_auth_endpoint "GET" "/api/browser/status" "Get browser status" "" "4" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/browser/connect" "Connect browser" '{"headless":false}' "5" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/browser/status" "Check browser connection" "" "6" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/browser/screenshot" "Take screenshot" '{"full_page":false}' "7" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/browser/disconnect" "Disconnect browser" "" "8" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/browser/status" "Verify disconnection" "" "9" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# 自动化控制（3个）
test_auth_endpoint "GET" "/api/automation/status" "Get automation status" "" "10" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/automation/start" "Start automation" "" "11" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/automation/stop" "Stop automation" "" "12" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# 数据查询（2个）
test_auth_endpoint "GET" "/api/candidates" "Get candidates list" "" "13" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/stats" "Get statistics" "" "14" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# 简历管理（5个）
test_auth_endpoint "GET" "/api/resume/status" "Get resume task status" "" "15" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/resume/list" "Get resume list" "" "16" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/resume/stats" "Get resume statistics" "" "17" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/resume/batch" "Batch download resumes" '{"limit":5}' "18" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/resume/download/1" "Download resume file" "" "19" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# 筛选功能（4个）
test_auth_endpoint "GET" "/api/filter/config" "Get filter config" "" "20" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/filter/contact" "Start filter contact" '{"daily_cap":50}' "21" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# AI对话（5个）
test_auth_endpoint "GET" "/api/chat/history" "Get chat history" "" "22" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/chat/templates" "Get chat templates" "" "23" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "POST" "/api/chat/batch" "Batch reply messages" '{"limit":5}' "24" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_auth_endpoint "GET" "/api/template/list" "Get template list" "" "25" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

# 兼容端点（3个）
test_public_endpoint "POST" "/api/workflow/say-hello" "Say hello (legacy)" '{"limit":10}' "26" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_public_endpoint "POST" "/api/workflow/get-resumes" "Get resumes (legacy)" '{"limit":10}' "27" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))
test_public_endpoint "POST" "/api/workflow/reply-messages" "Reply messages (legacy)" '{"limit":10}' "28" && ((PASSED++)) || ((FAILED++))
((TEST_NUM++))

echo ""
echo "=================================================="
echo "📊 验收结果"
echo "=================================================="
PASS_RATE=$(echo "scale=1; $PASSED/30*100" | bc)
echo "✅ 通过: $PASSED/30 ($PASS_RATE%)"
echo "❌ 失败: $FAILED/30"
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