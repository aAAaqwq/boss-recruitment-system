# F6 批量获取简历流程

## 触发入口

`POST /api/resume/batch` → API 线程池 → `_run_resume_in_thread()` → `collect_resumes()`

## 完整步骤

```
1. 获取浏览器任务锁
   └─ _browser_task_lock.acquire(blocking=False)
       失败 → 返回"浏览器正被 {task} 占用"

2. 连接浏览器 + 登录检查
   ├─ automation.reset_for_thread()  (线程安全重置)
   ├─ automation.connect() → nodriver CDP (port 9222)
   └─ check_login()
       ├─ 已登录 → 继续
       └─ 未登录 → 返回"请先在VNC中扫码登录"

3. 启用 CDP 下载拦截
   └─ enable_download_interception(data/resumes/)
       ├─ Page.setDownloadBehavior(behavior="allow", download_path=...)
       └─ Chrome 自动保存到 data/resumes/，不弹对话框
       失败 → 降级模式（依赖Chrome默认下载目录）

4. 导航到聊天页
   └─ 目标URL: https://www.zhipin.com/web/chat/index
       ├─ navigate_to_chat() 点击左侧"沟通"导航
       ├─ 备用: 直接导航 /web/chat/index
       └─ 获取联系人列表 (get_contacts)

5. 联系人列表为空
   └─ 备用导航 /web/chat/index → 重试 get_contacts
       仍为空 → 返回 completed (downloaded=0)

6. 主循环 (遍历 contacts[:max_count])
   │
   ├─ 6a. 点击联系人
   │      └─ automation.click(contact.x, contact.y)
   │
   ├─ 6b. 去重检查
   │      ├─ db.get_resume_ops(contact_name)
   │      └─ 已有 downloaded 记录 → 跳过
   │
   ├─ 6c. 查找简历按钮 (_JS_FIND_RESUME_BTNS)
   │      ├─ 选择器: 在聊天详情区域查找
   │      ├─ 精确匹配: '在线简历' / '附件简历' / '查看简历'
   │      └─ 无按钮 → 跳过 (no_resume_btn)
   │
   ├─ 6d. 点击"附件简历"按钮 → BOSS自动处理4种情况:
   │      │
   │      ├─ Case-1: PDF预览弹出 → 对方已发附件简历 ✅
   │      │   ├─ 等待PDF渲染完成
   │      │   ├─ 查找下载按钮 ('下载'/'保存'/'导出')
   │      │   ├─ 点击下载 → CDP拦截保存到 data/resumes/
   │      │   ├─ 验证: 对比前后文件列表
   │      │   └─ db.insert_resume_op(action="downloaded")
   │      │
   │      ├─ Case-2: "向牛人请求简历"弹窗 → 已沟通未发简历 ⏳
   │      │   ├─ 点击"确认"/"确定"按钮
   │      │   ├─ 等待: 确认后PDF可能弹出 → 走Case-1流程
   │      │   └─ 无PDF → db.insert_resume_op(action="requested")
   │      │
   │      ├─ Case-3: "附件简历请求中" → 已请求待处理 ⏭
   │      │   └─ 跳过, db.insert_resume_op(action="requested_pending")
   │      │
   │      └─ Case-4: "双方回复后可以向TA请求" → 未充分沟通 ❌
   │          └─ 跳过, db.insert_resume_op(action="need_reply")
   │
   ├─ 6e. 关闭简历预览
   │      └─ automation.press_key("Escape")
   │
   └─ 6f. 每3次操作截图一次

7. 释放浏览器任务锁
   └─ _browser_task_lock.release()

8. 返回结果
   └─ {downloaded, skipped, failed, total_scanned, details: [...]}
```

## "附件简历"按钮的4种返回状态

点击"附件简历"后，BOSS 系统会根据沟通状态返回不同结果：

```
click("附件简历")
     │
     ├─ 等待 2-3 秒
     │
     ├─ 检测到 PDF 预览 (AXWebArea + PDF) ──────── Case-1 ✅
     │   └─ 对方已上传附件 → 直接提取/下载
     │
     ├─ 检测到 "向牛人请求简历" 弹窗 ────────── Case-2 ⏳
     │   └─ 已沟通但对方未发 → 点确认索取
     │   └─ 确认后PDF弹出 → 升级为Case-1
     │
     ├─ 检测到 "附件简历请求中" ─────────────── Case-3 ⏭
     │   └─ 之前已请求，等待对方处理
     │
     ├─ 检测到 "双方回复后可以向TA请求" ──────── Case-4 ❌
     │   └─ 双方沟通不够，无法索取
     │
     └─ 其他: "简历请求已发送" / 无反应 ─────── unknown ⏭
         └─ 对方未上传附件 或 未沟通
```

| Case | 页面特征 | 含义 | 动作 | 记录 |
|------|----------|------|------|------|
| Case-1 | PDF预览弹出 | 对方已发附件 | 下载/提取 | `action="downloaded"` |
| Case-2 | "向牛人请求简历"弹窗 | 已沟通未发 | 点确认索取 | `action="requested"` |
| Case-3 | "附件简历请求中" | 已请求待处理 | 跳过 | `action="requested_pending"` |
| Case-4 | "双方回复后可以向TA请求" | 未充分沟通 | 跳过 | `action="need_reply"` |

## BOSS DOM 结构

```
聊天页 /web/chat/index (左右分栏)
├── 左侧: 联系人列表
│   └── .chat-item / .contact-item / .conversation
│       └── innerText → name / subtitle / hasUnread
│
└── 右侧: 聊天详情 (x > 450px)
    ├── 候选人信息行: 姓名 · 学历 · 学校 · 工作年限
    ├── 简历按钮区:
    │   ├── "在线简历"  → 打开在线简历页面 (HTML渲染)
    │   └── "附件简历"  → 触发上述4种情况
    │
    └── 底部操作栏:
        ├── "求简历" / "换电话" / "查看微信"
        └── "约面试" / "不合适"

附件简历预览 (Case-1 PDF弹出时)
├── AXWebArea (PDF)
│   └── 简历文本内容 (可提取)
└── 下载按钮: "下载" / "保存" / "导出"
    或 a[download] 链接

索取确认弹窗 (Case-2)
└── "向牛人请求简历"
    └── "确认" / "取消" 按钮
```

## CDP 下载拦截

```
nodriver CDP 命令: Page.setDownloadBehavior
参数:
  behavior: "allow"
  downloadPath: "/app/data/resumes/"
  eventsEnabled: true

效果:
  Chrome 跳过"保存到..."对话框
  文件直接写入 downloadPath 目录
  通过前后文件列表对比验证下载成功
```

## 去重机制

```
表: resume_operations
字段: candidate_name, action, resume_downloaded, detail, created_at

逻辑:
  1. 查询: SELECT * FROM resume_operations WHERE candidate_name = ?
  2. 检查: any(row.resume_downloaded or row.action == "downloaded")
  3. 已下载 → 跳过 (计入 skipped)
  4. 未下载 → 继续操作
```

## 参考: cua-boss-system 实现

原始CUA实现位于 `../cua-boss-system/scripts/cua_collect.py`，核心差异：

| 对比项 | CUA版本 (cua_collect.py) | 当前版本 (resume_collector.py) |
|--------|--------------------------|-------------------------------|
| 访问方式 | Apple AX树 + cua-driver | nodriver CDP + xdotool |
| 聊天页 | `/web/chat/index` | `/web/chat/index` (已对齐) |
| 4种Case处理 | 完整实现 (Case-1/2/3/4) | 需完善 (当前仅处理PDF和下载) |
| 简历提取 | PDF文本提取 → 存入DB | CDP下载到文件 |
| 候选人UID | data-id属性提取 | 用姓名(非唯一) |
| 附加操作 | 不合适→点"不合适"+ 换微信 | 仅处理简历 |

## 本次修复 (2026-06-07)

| 修复点 | 旧行为 | 新行为 |
|--------|--------|--------|
| 聊天页URL | /web/geek/chat | /web/chat/index |
| 文件下载 | 点击按钮但无CDP拦截，文件不保存 | `enable_download_interception()` + 文件验证 |
| 登录检查 | 无，直接操作 → 登录页误操作 | `check_login()` 前置检查 |
| JS选择器 | 匹配所有含"简历"文本的元素 | 精确匹配: '在线简历'/'附件简历'/'查看简历' |
| 导航 | 每次先跳首页→导入cookie→再跳聊天 | 直接 navigate_to_chat() |
| resume_operations表 | 仅在api.py init_db()创建 | Database.init_tables() 也创建（双保险） |
| 线程安全 | 直接设置 `automation._connected=False` | `reset_for_thread()` + `_browser_task_lock` |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/resume/batch` | 启动批量简历下载（需认证） |
| GET | `/api/resume/status` | 查询任务进度 |
| GET | `/api/resume/list` | 已下载简历列表 |
| GET | `/api/resume/stats` | 简历统计 |
| GET | `/api/resume/download/{id}` | 下载指定简历文件 |

## 已知问题

- Case-2 确认索取后PDF可能不弹出，只能记录 "requested"
- Case-3/4 未实现精确检测，当前仅记录为 "no_resume_btn"
- 在线简历（无附件）只能记录为 "requested"，无法下载文件
- Chrome 版本差异可能导致 `Page.setDownloadBehavior` 降级
- 候选人姓名可能重复（BOSS 显示名不是唯一标识，应提取 data-id）
