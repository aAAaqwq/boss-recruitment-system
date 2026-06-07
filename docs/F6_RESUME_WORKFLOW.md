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
   └─ navigate_to_chat()
       ├─ 点击左侧"沟通"导航按钮
       ├─ 备用: 直接导航 /web/geek/chat
       └─ 获取联系人列表 (get_contacts)

5. 联系人列表为空
   └─ 备用导航 /web/geek/chat → 重试 get_contacts
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
   ├─ 6d. 点击简历按钮
   │      └─ 等待3秒 (简历预览加载)
   │
   ├─ 6e. 查找下载按钮 (_JS_FIND_DOWNLOAD_BTN)
   │      ├─ 精确匹配: '下载' / '保存' / '导出'
   │      ├─ Fallback: a[download] 链接
   │      └─ 无下载按钮 → 记录 "在线简历已请求"
   │
   ├─ 6f. 点击下载 + 验证
   │      ├─ 记录下载前 data/resumes/ 文件列表
   │      ├─ automation.click(dl.x, dl.y)
   │      ├─ 等待4秒
   │      ├─ 对比文件列表: 有新文件 → file_verified=True
   │      └─ db.insert_resume_op(action="downloaded")
   │
   ├─ 6g. 关闭简历预览
   │      └─ automation.press_key("Escape")
   │
   └─ 6h. 每3次操作截图一次

7. 释放浏览器任务锁
   └─ _browser_task_lock.release()

8. 返回结果
   └─ {downloaded, skipped, failed, total_scanned, details: [...]}
```

## BOSS DOM 结构

```
聊天页 (左右分栏)
├── 左侧: 联系人列表
│   └── .chat-item / .contact-item / .conversation
│       └── innerText → name / subtitle / hasUnread
│
└── 右侧: 聊天详情 (x > 450px)
    └── 简历按钮
        ├── "在线简历"  → 打开在线简历预览
        └── "附件简历"  → 可能直接触发下载

简历预览层
└── 下载按钮: "下载" / "保存" / "导出"
    或 a[download] 链接
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

## 本次修复 (2026-06-07)

| 修复点 | 旧行为 | 新行为 |
|--------|--------|--------|
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

- 在线简历（无附件）只能记录为"requested"，无法下载文件
- Chrome 版本差异可能导致 `Page.setDownloadBehavior` 降级
- 候选人姓名可能重复（BOSS 显示名不是唯一标识）
