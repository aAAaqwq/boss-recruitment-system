"""
BOSS直聘 Chat 页面导航辅助函数
处理 SPA 导航（点击左侧"沟通"按钮进入聊天页）
"""
import asyncio
from typing import Dict

from app.automation import automation
from app.logging_config import logger

# 左侧导航栏 "沟通" 按钮的 CSS 选择器（多种fallback）
_CHAT_NAV_SELECTORS = [
    'a[href*="/web/chat"]',
    'a[href*="/web/geek/chat"]',
    '[class*="nav"] [class*="chat"]',
    '[class*="menu"] [class*="chat"]',
    '[class*="sidebar"] [class*="chat"]',
    '.nav-item-chat',
    '.chat-nav',
    'li:has(> a[href*="/web/chat"])',
]

# JS: 点击"沟通"导航
_JS_CLICK_CHAT_NAV = """
(function() {
    // 方法1: 按文本查找
    var items = document.querySelectorAll(
        'a, li, div[class*="nav"], span[class*="nav"], [class*="menu-item"], [class*="tab"]'
    );
    for (var i = 0; i < items.length; i++) {
        var t = (items[i].innerText || '').trim();
        if (t === '沟通' || t === '消息' || t === '聊天') {
            var r = items[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0 && r.x < 400) {
                items[i].click();
                return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
            }
        }
    }
    // 方法2: 按 href 查找
    var links = document.querySelectorAll('a[href*="chat"]');
    for (var j = 0; j < links.length; j++) {
        var lr = links[j].getBoundingClientRect();
        if (lr.width > 0 && lr.height > 0 && lr.x < 400) {
            links[j].click();
            return {found: true, text: 'href', x: lr.x + lr.width/2, y: lr.y + lr.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 获取左侧联系人列表（已聊过的候选人）
_JS_GET_CONTACTS = """
(function() {
    var items = document.querySelectorAll(
        '[class*="chat-item"], [class*="contact-item"], [class*="conversation"], '
        + '[class*="dialog"], [class*="user-item"], [class*="list-item"]'
    );
    var contacts = [];
    for (var i = 0; i < items.length; i++) {
        var r = items[i].getBoundingClientRect();
        var t = (items[i].innerText || '').trim();
        // 只取左侧面板（x < 450px)且合理的项目
        if (r.x < 450 && r.width > 120 && r.height > 40 && t.length > 0) {
            var lines = t.split('\\n').filter(function(l) { return l.trim().length > 0; });
            contacts.push({
                name: lines[0] || '',
                subtitle: lines[1] || '',
                text: t,
                x: r.x + r.width / 2,
                y: r.y + r.height / 2,
                w: r.width,
                h: r.height,
                hasUnread: t.indexOf('●') >= 0 || t.indexOf('未读') >= 0
            });
        }
    }
    return contacts;
})()
"""

# JS: 检查是否有未读消息
_JS_HAS_UNREAD = """
(function() {
    var badges = document.querySelectorAll(
        '[class*="badge"], [class*="unread"], [class*="dot"], [class*="count"], '
        + '[class*="notification"], [class*="new-msg"]'
    );
    for (var i = 0; i < badges.length; i++) {
        var t = (badges[i].innerText || '').trim();
        if (t && t !== '0') {
            var r = badges[i].getBoundingClientRect();
            return {hasUnread: true, count: t, x: r.x, y: r.y};
        }
    }
    // 检查是否有红点元素
    var redDots = document.querySelectorAll('[class*="red"], [style*="red"], [style*="ff0000"]');
    return {hasUnread: redDots.length > 0, count: redDots.length};
})()
"""

# JS: 获取当前聊天消息（改进版：相对定位判断发送方）
_JS_GET_MESSAGES = """
(function() {
    // 找到聊天消息容器以确定面板宽度
    var containers = document.querySelectorAll(
        '[class*="chat-content"], [class*="message-list"], [class*="msg-list"], '
        + '[class*="dialog-body"], [class*="chat-body"]'
    );
    var panelWidth = 1000; // 默认宽度
    for (var c = 0; c < containers.length; c++) {
        var cr = containers[c].getBoundingClientRect();
        if (cr.width > 300) {
            panelWidth = cr.width;
            break;
        }
    }

    var msgs = document.querySelectorAll(
        '[class*="message"], [class*="msg"], [class*="bubble"], [class*="chat-content"]'
    );
    var result = [];
    for (var i = 0; i < msgs.length; i++) {
        var t = (msgs[i].innerText || '').trim();
        var r = msgs[i].getBoundingClientRect();
        if (t.length > 3 && r.width > 50) {
            // 相对定位: 如果消息气泡在面板右半部分 → 是"我"发的
            // 同时检查 CSS class 中是否有 "self"/"mine"/"right" 等标识
            var cls = (msgs[i].className || '').toLowerCase();
            var isMeByClass = cls.indexOf('self') >= 0 || cls.indexOf('mine') >= 0
                || cls.indexOf('right') >= 0 || cls.indexOf('send') >= 0;
            var isMeByPos = r.x > panelWidth * 0.5;
            var isMe = isMeByClass || isMeByPos;
            result.push({text: t, isMe: isMe, x: r.x, y: r.y});
        }
    }
    return result;
})()
"""

# JS: 查找输入框和发送按钮
_JS_FIND_INPUT_AREA = """
(function() {
    // 输入框
    var inputs = document.querySelectorAll(
        'textarea, [contenteditable="true"], [class*="input"] textarea, '
        + '[class*="editor"], [class*="chat-input"]'
    );
    var inputInfo = null;
    for (var i = 0; i < inputs.length; i++) {
        var r = inputs[i].getBoundingClientRect();
        if (r.width > 100 && r.height > 20) {
            inputInfo = {x: r.x + r.width/2, y: r.y + r.height/2};
            break;
        }
    }
    // 发送按钮
    var btns = document.querySelectorAll(
        'button, [class*="send"], [class*="submit"], [class*="btn-send"]'
    );
    var sendBtn = null;
    for (var j = 0; j < btns.length; j++) {
        var t = (btns[j].innerText || '').trim();
        if (t === '发送' || t === '发 送' || t.indexOf('发送') >= 0 || t.indexOf('Send') >= 0) {
            var br = btns[j].getBoundingClientRect();
            if (br.width > 0 && br.height > 0) {
                sendBtn = {x: br.x + br.width/2, y: br.y + br.height/2, text: t};
                break;
            }
        }
    }
    return {input: inputInfo, send: sendBtn};
})()
"""


async def navigate_to_chat() -> Dict:
    """导航到BOSS直聘聊天页（通过点击左侧"沟通"按钮）

    Returns:
        {status: "ok"|"error", message: str, contact_count: int}
    """
    # 先确保在 zhipin.com 上
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接"}

    # 先导航到首页确保左侧导航栏可见
    await automation.navigate("https://www.zhipin.com/web/chat/recommend")
    await asyncio.sleep(3)

    # 尝试点击"沟通"导航按钮
    clicked = await automation.execute_js(_JS_CLICK_CHAT_NAV)
    # 防御: 确保返回值是 dict 而非 list
    if not isinstance(clicked, dict):
        logger.warning(f"[ChatNav] JS返回了非dict类型: {type(clicked).__name__} = {clicked!r}")
        clicked = None
    if not clicked or not clicked.get("found"):
        # 备用: 导航到推荐的页面（可能自动跳转到聊天）
        await automation.navigate("https://www.zhipin.com/web/geek/chat")
        await asyncio.sleep(3)
        clicked = await automation.execute_js(_JS_CLICK_CHAT_NAV)
        if not isinstance(clicked, dict):
            logger.warning(f"[ChatNav] JS重试也返回了非dict类型: {type(clicked).__name__}")
            clicked = None

    await asyncio.sleep(2)

    # 获取联系人列表
    contacts = await automation.execute_js(_JS_GET_CONTACTS)
    contact_count = len(contacts) if isinstance(contacts, list) else 0

    if clicked and clicked.get("found"):
        logger.info(f"[ChatNav] 已点击'沟通'，找到 {contact_count} 个联系人")
        return {"status": "ok", "message": f"已进入聊天页，{contact_count}个联系人", "contact_count": contact_count}
    else:
        logger.warning("[ChatNav] 未找到'沟通'按钮，可能已在聊天页")
        return {"status": "ok", "message": "已在聊天页(或无法确认)", "contact_count": contact_count}


async def get_contacts() -> list:
    """获取左侧联系人列表"""
    result = await automation.execute_js(_JS_GET_CONTACTS)
    return result if isinstance(result, list) else []


async def get_messages() -> list:
    """获取当前聊天消息"""
    result = await automation.execute_js(_JS_GET_MESSAGES)
    return result if isinstance(result, list) else []


async def find_input() -> dict:
    """查找输入框和发送按钮位置"""
    result = await automation.execute_js(_JS_FIND_INPUT_AREA)
    return result if isinstance(result, dict) else {"input": None, "send": None}


async def has_unread() -> dict:
    """检查是否有未读消息"""
    result = await automation.execute_js(_JS_HAS_UNREAD)
    return result if isinstance(result, dict) else {"hasUnread": False, "count": 0}


async def click_contact(name: str, x: float, y: float) -> bool:
    """点击指定联系人"""
    try:
        await automation.click(int(x), int(y))
        await asyncio.sleep(2)
        return True
    except Exception as e:
        logger.warning(f"[ChatNav] 点击联系人失败: {e}")
        return False


async def type_and_send(message: str) -> Dict:
    """在输入框中输入消息并点击发送"""
    input_info = await find_input()
    send_info = input_info.get("send")
    input_pos = input_info.get("input")

    if not input_pos:
        return {"status": "error", "message": "未找到输入框"}

    try:
        # 点击输入框
        await automation.click(int(input_pos["x"]), int(input_pos["y"]))
        await asyncio.sleep(0.5)

        # 清空并输入消息
        await automation.type_text(message)
        await asyncio.sleep(0.5)

        # 点击发送或按Enter
        if send_info:
            await automation.click(int(send_info["x"]), int(send_info["y"]))
        else:
            await automation.press_key("Return")

        await asyncio.sleep(1)
        return {"status": "ok", "message": "已发送"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
