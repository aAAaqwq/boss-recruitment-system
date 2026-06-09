# F6 + F7 测试策略

> 生成时间: 2026-06-08
> 状态: 完成

## 覆盖概览

| 模块 | 文件 | 现有测试 | 新增测试 | 总测试数 | 覆盖目标 |
|------|------|---------|---------|---------|---------|
| F6 简历收集 | `test_f6_resume_collection.py` | 0 | 55+ | 55+ | 80%+ |
| F7 批量回复 | `test_f7_batch_reply.py` | 0 | 50+ | 50+ | 80%+ |
| F7 对话阶段 | `test_f7_chat_pipeline.py` | 27 | — | 27 | 85%+ ✅ |
| F7 现有API | `test_chat_api.py` | 7 | — | 7 | 烟雾 ✅ |
| 简历端点 | `test_resume_endpoints.py` | 4 | — | 4 | DB层 ✅ |

## 测试分层

### L1: 纯逻辑测试 (无 mock，无 I/O)
- JS 脚本格式验证 (IIFE, 选择器, 返回值)
- 关键词列表覆盖验证
- 字符串常量完整性检查
- 数据转换函数 (_build_history_from_messages, _merge_histories)

### L2: Mock 单元测试 (mock 外部依赖)
- `collect_resumes` 主流程各路径
- `_batch_reply_impl` 主流程各路径
- `_detect_resume_case` 4种Case
- `_handle_case1_download` 下载确认
- `_handle_case2_confirm` 弹窗确认
- `chat_service.generate_reply` HTTP mock
- 所有边界/错误路径

### L3: 集成测试 (DB + 真实依赖)
- `load_candidate_context` DB 查询
- `_record_resume_op` DB 写入
- `save_conversation` DB 持久化
- 去重跳过逻辑

### L4: 视觉验收测试 (浏览器)
- 聊天页加载 + 联系人列表
- 简历按钮检测 + 4种Case
- 下载确认流程
- 限制弹窗检测
- 消息发送确认

## 新增文件

```
tests/
├── test_f6_resume_collection.py   # F6 单元+集成测试 (55+ tests)
├── test_f7_batch_reply.py         # F7 单元+集成测试 (50+ tests)
└── run_visual_checks.py           # 视觉验收验证脚本

docs/tests/
├── f6-f7-test-strategy.md         # 本文档
├── f6-resume-collection-visual.md # F6 视觉验收清单
├── f7-batch-reply-visual.md       # F7 视觉验收清单
└── f6-f7-integration-visual.md    # F6+F7 集成视觉验收
```

## 优先级矩阵

| 优先级 | 内容 | 原因 |
|--------|------|------|
| P0 | L1 JS脚本验证 | 零依赖，秒级运行 |
| P0 | L2 错误路径 (未登录/浏览器断开) | 最常见失败场景 |
| P0 | L2 主流程 mock (collect_resumes, _batch_reply_impl) | 核心业务逻辑 |
| P1 | L2 AI降级/冗余检测 | 关键质量保证 |
| P1 | L3 DB集成测试 | 数据完整性 |
| P2 | L4 浏览器视觉验收 | 需要真实环境 |

## 运行方式

```bash
# 运行所有 F6+F7 测试
python3 -m pytest tests/test_f6_resume_collection.py tests/test_f7_batch_reply.py tests/test_f7_chat_pipeline.py -v

# 运行视觉验证脚本
python3 tests/run_visual_checks.py

# 带覆盖率
python3 -m pytest tests/test_f6_resume_collection.py tests/test_f7_batch_reply.py \
  tests/test_f7_chat_pipeline.py --cov=app.resume_collector --cov=app.chat_workflow \
  --cov=app.chat_stage --cov=app.chat_service --cov=app.chat_nav --cov-report=term-missing
```
