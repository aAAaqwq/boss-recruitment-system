# 项目开发原则

> 最后更新: 2025-06-04

## 核心原则

### 🔄 对接现成，不重复造轮子

**关键原则**: 关键在于对接现成的功能，而不是重复造轮子。越简单实现越好。

**具体要求**:
- 优先使用项目中已有的函数和模块
- 在API层添加简单的端点调用现有功能
- 避免重新实现已存在的逻辑
- 保持代码简洁，直接复用

**可用的现成模块**:

| 模块 | 功能 | 主要函数 |
|------|------|----------|
| `app/screen.py` | 浏览器控制 | `activate_chrome()`, `move_and_click()`, `screenshot()` |
| `app/vision.py` | OCR识别 | `screen_ocr()`, `click_text_ocr()` |
| `app/workflows.py` | 核心工作流 | `workflow_3_1_auto_contact()`, `workflow_3_3_chat_bot()` |
| `app/resume_collector.py` | 简历收集 | `get_resume()`, `exchange_wechat()` |
| `app/communicate_collector.py` | AI对话 | (待确认) |

**开发流程**:
1. 先查看现有模块有哪些可用函数
2. 在 `app/api.py` 中添加简单的API端点
3. 直接调用现有函数，包装返回结果
4. 不需要修改现有模块的代码

---

*记住: 对接 > 重写，简单 > 复杂*
