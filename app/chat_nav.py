"""
BOSS直聘 Chat 页面导航辅助函数
处理 SPA 导航（通过 URL 直达 + iframe 穿透）
BOSS直聘 /web/chat/ 页面内容在 iframe 内，所有 JS 需穿透
"""
import asyncio
import json
from typing import Dict, List, Optional, Any

from app.automation import automation
from app.logging_config import logger

# iframe 穿透前缀 — 聊天页内容在 .frame-box iframe 内
_GET_DOC = """
var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
"""

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
# 聊天页内容在主文档中（非iframe），使用 .geek-item-wrap 选择器
_JS_GET_CONTACTS = """
(function() {
    try {
        // 从DOM提取BOSS平台唯一ID（增强版：扫描React props + 所有属性 + 链接）
        function extractBossId(el) {
            // 辅助：如果值是 "数字-数字" 格式（如 data-id="28717495-0"），提取数字部分
            function cleanId(v) {
                if (!v) return v;
                var m = v.match(/^(\d+)-\d+$/);
                return m ? m[1] : v;
            }
            // 1. 扫描元素自身所有属性（含 data-uid, data-security-id, data-id 等）
            for (var a = 0; a < (el.attributes || []).length; a++) {
                var an = el.attributes[a].name;
                var av = el.attributes[a].value;
                if (!av || av.length < 5) continue;
                if (/^(data-)?(uid|userid|user-id|securityid|security-id|encryptid|encrypt-id|encrypt_uid|eid|geekid|chatid|id)$/i.test(an)) {
                    return cleanId(av);
                }
            }
            // 2. 从链接href提取 (例: /web/chat/geek?securityId=xxx 或 /chat/xxx)
            var links = el.querySelectorAll('a[href]');
            for (var l = 0; l < links.length; l++) {
                var h = links[l].getAttribute('href') || '';
                var m = h.match(/[?&](securityId|encryptId|encryptBossId|uid|userId|bossId)=([^&?#]+)/i);
                if (m && m[2]) return m[2];
                // 路径中的ID: /geek/abc123 或 /chat/abc123
                var pm = h.match(/\/(geek|chat|boss|user)\/([a-zA-Z0-9_-]{10,})/i);
                if (pm && pm[2]) return pm[2];
            }
            // 3. 扫描所有子元素的属性（2层深度）
            var kids = el.querySelectorAll('[data-uid],[data-security-id],[data-encrypt-id],[data-id],[data-user-id]');
            for (var k = 0; k < kids.length; k++) {
                for (var b = 0; b < (kids[k].attributes || []).length; b++) {
                    var kan = kids[k].attributes[b].name;
                    var kav = kids[k].attributes[b].value;
                    if (!kav || kav.length < 5) continue;
                    if (/^(data-)?(uid|userid|securityid|security-id|encryptid|encrypt-id|encrypt_uid|eid|geekid|chatid|id)$/i.test(kan)) {
                        return cleanId(kav);
                    }
                }
            }
            // 4. 扫描父元素（向上3层）
            for (var p = el.parentElement, d = 0; p && d < 3; p = p.parentElement, d++) {
                for (var c = 0; c < (p.attributes || []).length; c++) {
                    var pn = p.attributes[c].name;
                    var pv = p.attributes[c].value;
                    if (!pv || pv.length < 5) continue;
                    if (/^(data-)?(uid|userid|securityid|security-id|encryptid|encrypt-id|encrypt_uid|eid|geekid|chatid|id)$/i.test(pn)) {
                        return cleanId(pv);
                    }
                }
            }
            // 5. React内部状态 (__reactFiber / __reactProps)
            try {
                var fiberKey = Object.keys(el).find(function(k) { return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'); });
                if (fiberKey) {
                    var fiber = el[fiberKey];
                    // 遍历fiber树查找memoizedProps中的用户ID
                    for (var ff = fiber, fd = 0; ff && fd < 10; ff = ff.return || ff._debugOwner, fd++) {
                        var mp = ff.memoizedProps;
                        if (mp) {
                            var idSource = mp.securityId || mp.encryptId || mp.encryptBossId || mp.uid || mp.userId || mp.bossId || mp.geekId;
                            if (idSource && typeof idSource === 'string' && idSource.length > 5) return idSource;
                            // 检查children中是否包含ID字段
                            if (mp.children && typeof mp.children === 'object') {
                                var cid = mp.children.securityId || mp.children.encryptId || mp.children.uid;
                                if (cid && typeof cid === 'string' && cid.length > 5) return cid;
                            }
                        }
                    }
                }
            } catch(e) {}
            return null;
        }
        var contacts = [];
        var items = document.querySelectorAll('.geek-item-wrap');
        // 诊断：打印第一个联系人的完整DOM信息
        if (items.length > 0) {
            var diag = items[0];
            var diagInfo = {tag: diag.tagName, classes: diag.className, attrCount: diag.attributes.length};
            var attrs = [];
            for (var da = 0; da < diag.attributes.length; da++) {
                attrs.push(diag.attributes[da].name + '=' + (diag.attributes[da].value || '').substring(0, 80));
            }
            diagInfo.attrs = attrs;
            diagInfo.innerText = (diag.innerText || '').substring(0, 100);
            // 检查React属性
            var reactKeys = Object.keys(diag).filter(function(k) { return k.startsWith('__react'); });
            diagInfo.reactKeys = reactKeys;
            // 内部链接
            var dLinks = diag.querySelectorAll('a[href]');
            var dHrefs = [];
            for (var dl = 0; dl < Math.min(dLinks.length, 3); dl++) {
                dHrefs.push(dLinks[dl].getAttribute('href'));
            }
            diagInfo.linkHrefs = dHrefs;
            contacts.push({name: '__DIAG__', subtitle: JSON.stringify(diagInfo), text: '', x: 0, y: 0, w: 0, h: 0, hasUnread: false, boss_id: null});
        }
        for (var i = 0; i < items.length; i++) {
            try {
                var r = items[i].getBoundingClientRect();
                var t = (items[i].innerText || '').trim();
                if (r.width > 80 && r.height > 30 && t.length > 0) {
                    var parts = t.split(/[\\n]+/).filter(function(l) { return l.trim().length > 0; });
                    var name = parts[0] || '';
                    var subtitle = parts.length > 1 ? parts[parts.length - 1] : '';
                    var topEl = items[i].querySelector('.geek-item-top');
                    if (topEl) {
                        var topText = (topEl.innerText || '').trim();
                        var topParts = topText.split(/[\\n]+/);
                        if (topParts[0]) name = topParts[0].trim();
                        if (topParts.length > 1) subtitle = topParts.slice(1).join(' ').trim();
                    }
                    var bossId = extractBossId(items[i]);
                    contacts.push({
                        name: name,
                        subtitle: subtitle,
                        text: t,
                        x: r.x + r.width / 2,
                        y: r.y + r.height / 2,
                        w: r.width,
                        h: r.height,
                        hasUnread: t.indexOf('\\u25cf') >= 0 || t.indexOf('未读') >= 0,
                        boss_id: bossId
                    });
                }
            } catch(e2) {}
        }
        return JSON.stringify(contacts);
    } catch(e) {
        return JSON.stringify({error: 'JS_EXCEPTION', message: e.message || String(e), line: e.lineNumber});
    }
})()
"""

# JS: 检查是否有未读消息 — 在主文档和iframe中搜索
_JS_HAS_UNREAD = """
(function() {
    // 策略1: 主文档中搜索
    var badges = document.querySelectorAll(
        '[class*="badge"], [class*="unread"], [class*="dot"], [class*="count"], '
        + '[class*="notification"], [class*="new-msg"], [class*="red"]'
    );
    for (var i = 0; i < badges.length; i++) {
        var t = (badges[i].innerText || '').trim();
        if (t && t !== '0') {
            var r = badges[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                return {hasUnread: true, count: t, x: Math.round(r.x), y: Math.round(r.y)};
            }
        }
    }
    // 策略2: iframe中搜索
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var doc = iframe.contentDocument;
        var ibadges = doc.querySelectorAll('[class*="badge"], [class*="unread"], [class*="dot"], [class*="red"]');
        for (var j = 0; j < ibadges.length; j++) {
            var it = (ibadges[j].innerText || '').trim();
            if (it && it !== '0') {
                var ir = ibadges[j].getBoundingClientRect();
                if (ir.width > 0 && ir.height > 0) {
                    return {hasUnread: true, count: it, x: Math.round(ir.x), y: Math.round(ir.y)};
                }
            }
        }
    }
    return {hasUnread: false, count: 0};
})()
"""

# JS: 获取当前聊天消息 — 精准定位 .chat-conversation 消息容器
# BOSS直聘聊天页结构: .chat-user(左侧联系人,x=444-804) + .chat-conversation(右侧消息,x=804+)
_JS_GET_MESSAGES = """
(function() {
    var vw = Math.max(window.innerWidth, 1000);
    var result = [];
    var seen = {};

    function isMe(el, r, cls) {
        if (cls.indexOf('self') >= 0 || cls.indexOf('mine') >= 0
            || cls.indexOf('right') >= 0 || cls.indexOf('send') >= 0
            || cls.indexOf('boss') >= 0) return true;
        if (r.x > vw * 0.58) return true;
        return false;
    }

    // 精准定位消息容器
    var chatBox = document.querySelector('.chat-conversation');
    if (!chatBox) {
        return JSON.stringify([]);
    }
    // 排除空状态
    if (chatBox.querySelector('.conversation-no-data')) {
        return JSON.stringify([]);
    }

    function tryCapture(el, text) {
        if (text.length < 2 || text.length > 600) return;
        var r = el.getBoundingClientRect();
        if (r.width < 10 || r.height < 10 || r.width > 650) return;
        var cls = (el.className || '').toString().toLowerCase();
        if (cls.indexOf('input') >= 0 || cls.indexOf('editor') >= 0) return;
        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') return;
        // 排除输入框附近区域（系统快捷回复等UI元素，Y > chatBox底部-100px）
        var chatBottom = chatBox.getBoundingClientRect().bottom;
        if (r.y > chatBottom - 120) return;
        var key = text.substring(0, 40) + '@' + Math.round(r.y / 5);
        if (seen[key]) return;
        seen[key] = true;
        result.push({
            text: text, isMe: isMe(el, r, cls),
            x: Math.round(r.x), y: Math.round(r.y)
        });
    }

    function walk(el) {
        // 先捕获文本节点
        for (var i = 0; i < el.childNodes.length; i++) {
            var node = el.childNodes[i];
            if (node.nodeType === 3) {
                var t = (node.textContent || '').trim();
                if (t) tryCapture(el, t);
            }
        }
        // 叶子元素：捕获完整文本
        if (el.children.length === 0) {
            var full = (el.textContent || '').trim();
            if (full) tryCapture(el, full);
            return;
        }
        // 递归子元素
        for (var j = 0; j < el.children.length; j++) {
            walk(el.children[j]);
        }
    }
    walk(chatBox);

    // 按Y排序
    result.sort(function(a, b) { return a.y - b.y; });
    return JSON.stringify(result);
})()
"""

# JS: 查找输入框和发送按钮 — 优先主文档，回退iframe
_JS_FIND_INPUT_AREA = """
(function() {
    function findInDoc(doc) {
        var inputs = doc.querySelectorAll(
            'textarea, [contenteditable="true"], [class*="input"] textarea, '
            + '[class*="editor"], [class*="chat-input"], [class*="input-area"], '
            + '[class*="send-area"], [class*="type-area"]'
        );
        var inputInfo = null;
        for (var i = 0; i < inputs.length; i++) {
            var r = inputs[i].getBoundingClientRect();
            if (r.width > 100 && r.height > 20) {
                inputInfo = {x: r.x + r.width/2, y: r.y + r.height/2}; break;
            }
        }
        var btns = doc.querySelectorAll(
            'button, [class*="send"], [class*="submit"], [class*="btn-send"]'
        );
        var sendBtn = null;
        for (var j = 0; j < btns.length; j++) {
            var t = (btns[j].innerText || '').trim();
            if (t === '发送' || t === '发 送' || t.indexOf('发送') >= 0 || t.indexOf('Send') >= 0) {
                var br = btns[j].getBoundingClientRect();
                if (br.width > 0 && br.height > 0) {
                    sendBtn = {x: br.x + br.width/2, y: br.y + br.height/2, text: t}; break;
                }
            }
        }
        return {input: inputInfo, send: sendBtn};
    }

    // 先搜索主文档
    var result = findInDoc(document);
    if (result.input || result.send) return result;

    // 回退: iframe
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var ifResult = findInDoc(iframe.contentDocument);
        if (ifResult.input || ifResult.send) return ifResult;
    }
    return result;
})()
"""

# 限制弹窗关键词 — 检测 BOSS "已达上限" 等限制提示
LIMIT_KEYWORDS = [
    "已达上限", "次数已用完", "今日已达", "已达每日",
    "沟通人数已达", "打招呼次数", "超出限制",
    "今日上限", "已达当天",
    "每天最多", "上限了", "用完了", "今日沟通",
    "权益不足", "开料次数", "剩余次数", "次数不足",
    "会员权益", "升级会员", "额度不足", "免费次数",
    "今日剩余",
]

# JS: 检测限制弹窗 — 扫描可见弹窗/对话框/提示中的关键词
_JS_CHECK_LIMIT_POPUP = """
(function() {
    var keywords = %s;
    var texts = [];
    document.querySelectorAll(
        '[class*=toast], [class*=popup], [class*=modal], [class*=dialog], '
        + '[class*=notice], [class*=tip], [class*=message], [class*=snackbar], '
        + '[class*=alert], [class*=confirm], [class*=overlay], [class*=mask], '
        + '[class*=backdrop], [class*=wrapper]'
    ).forEach(function(el) {
        var style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        var rect = el.getBoundingClientRect();
        if (rect.width < 50 || rect.height < 10) return;
        var t = (el.textContent || '').trim();
        if (t.length > 2 && t.length < 200) texts.push(t);
    });
    for (var i = 0; i < texts.length; i++) {
        for (var j = 0; j < keywords.length; j++) {
            if (texts[i].indexOf(keywords[j]) >= 0) {
                return JSON.stringify({hit: true, keyword: keywords[j], text: texts[i]});
            }
        }
    }
    return JSON.stringify({hit: false});
})()
""" % json.dumps(LIMIT_KEYWORDS)

# JS: 关闭弹窗 — 移除 fixed 定位的遮罩层
_JS_DISMISS_POPUP = """
(function() {
    var removed = 0;
    document.querySelectorAll(
        '.dialog-wrap, [class*=overlay], [class*=mask], [class*=backdrop], '
        + '.boss-popup__wrapper, [class*=modal]'
    ).forEach(function(el) {
        var s = getComputedStyle(el);
        if ((s.position === 'fixed' || parseInt(s.zIndex) > 100) && s.display !== 'none') {
            el.remove(); removed++;
        }
    });
    return removed;
})()
"""

# JS: 清空输入框 — 聚焦 + 全选 + 删除，优先主文档，兼容 React/Vue
_JS_CLEAR_INPUT = """
(function() {
    function clearInDoc(doc) {
        var el = doc.querySelector(
            'textarea, [contenteditable="true"], [class*="chat-input"], [class*="input-box"]'
        );
        if (!el) return false;
        el.focus();
        el.dispatchEvent(new Event('focus', {bubbles: true}));
        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
            el.setSelectionRange(0, el.value.length);
        } else if (el.contentEditable === 'true') {
            var range = document.createRange();
            range.selectNodeContents(el);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }
        return true;
    }

    if (clearInDoc(document)) return JSON.stringify({ok: true});

    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument && clearInDoc(iframe.contentDocument)) {
        return JSON.stringify({ok: true});
    }
    return JSON.stringify({ok: false, reason: 'not_found'});
})()
"""


# JS: 点击"未读"筛选标签 — 聊天页在主文档中，.chat-message-filter-left 内的 span
_JS_CLICK_UNREAD = """
(function() {
    // 策略1: 直接找 .chat-message-filter-left 内的"未读"文本
    var filterArea = document.querySelector('.chat-message-filter-left');
    if (filterArea) {
        var spans = filterArea.querySelectorAll('span');
        for (var i = 0; i < spans.length; i++) {
            var t = (spans[i].innerText || '').trim();
            if (t === '未读') {
                var r = spans[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    spans[i].click();
                    return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
        }
    }

    // 策略2: 全局搜索"未读"文本的span
    var allSpans = document.querySelectorAll('span');
    for (var j = 0; j < allSpans.length; j++) {
        var st = (allSpans[j].innerText || '').trim();
        if (st === '未读') {
            var sr = allSpans[j].getBoundingClientRect();
            if (sr.width > 0 && sr.height > 0 && sr.y < 300) {
                allSpans[j].click();
                return {found: true, text: st, x: sr.x + sr.width/2, y: sr.y + sr.height/2};
            }
        }
    }

    // 策略3: 在iframe中搜索(回退)
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var idoc = iframe.contentDocument;
        var ispans = idoc.querySelectorAll('span');
        for (var k = 0; k < ispans.length; k++) {
            if ((ispans[k].innerText || '').trim() === '未读') {
                var ir = ispans[k].getBoundingClientRect();
                if (ir.width > 0 && ir.height > 0) {
                    ispans[k].click();
                    return {found: true, text: 'iframe-未读', x: ir.x + ir.width/2, y: ir.y + ir.height/2};
                }
            }
        }
    }

    return {found: false};
})()
"""


# JS: 综合DOM诊断 — 扫描聊天页所有关键元素的class/结构/文本
_JS_DUMP_CHAT_DOM = """
(function() {
    var report = {};

    // 1. 所有iframe
    var iframes = document.querySelectorAll('iframe');
    report.iframes = [];
    for (var i = 0; i < iframes.length; i++) {
        var f = iframes[i];
        var r = f.getBoundingClientRect();
        report.iframes.push({
            index: i,
            src: (f.src || '').substring(0, 120),
            className: f.className || '',
            id: f.id || '',
            width: r.width, height: r.height,
            visible: r.width > 0 && r.height > 0
        });
    }

    // 2. 主文档和iframe内的结构扫描
    var targets = [{label: 'main', doc: document}];
    for (var j = 0; j < iframes.length; j++) {
        try {
            var d = iframes[j].contentDocument;
            if (d) targets.push({label: 'iframe[' + j + ']', doc: d});
        } catch(e) {}
    }

    report.panels = [];
    for (var t = 0; t < targets.length; t++) {
        var doc = targets[t].doc;
        var label = targets[t].label;

        // 扫描所有有className的可见div/section/ul/li
        var all = doc.querySelectorAll('div, section, ul, li, nav, aside, a, span, button');
        for (var k = 0; k < all.length; k++) {
            var el = all[k];
            var rect = el.getBoundingClientRect();
            var cls = el.className || '';
            var tag = el.tagName.toLowerCase();
            var text = (el.innerText || '').trim().substring(0, 80);
            // 只收集有意义的元素: 有class且可见
            if (cls && rect.width > 60 && rect.height > 15 && text.length > 0) {
                report.panels.push({
                    source: label,
                    tag: tag,
                    cls: typeof cls === 'string' ? cls.substring(0, 100) : '',
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                    text: text.replace(/\\n/g, ' | ')
                });
            }
        }
    }

    // 3. 扫描包含"未读"文字的元素
    report.unreadElements = [];
    for (var t2 = 0; t2 < targets.length; t2++) {
        var doc2 = targets[t2].doc;
        var items = doc2.querySelectorAll('*');
        for (var m = 0; m < items.length; m++) {
            var txt = (items[m].innerText || '').trim();
            if (txt === '未读' || txt.indexOf('未读') === 0) {
                var r2 = items[m].getBoundingClientRect();
                report.unreadElements.push({
                    source: targets[t2].label,
                    tag: items[m].tagName.toLowerCase(),
                    cls: (items[m].className || '').toString().substring(0, 100),
                    x: Math.round(r2.x), y: Math.round(r2.y),
                    w: Math.round(r2.width), h: Math.round(r2.height),
                    text: txt.substring(0, 60)
                });
            }
        }
    }

    // 4. 扫描左侧区域(x<500)的列表项
    report.leftSideItems = [];
    for (var t3 = 0; t3 < targets.length; t3++) {
        var doc3 = targets[t3].doc;
        var leftItems = doc3.querySelectorAll('li, div, a');
        for (var n = 0; n < leftItems.length; n++) {
            var el3 = leftItems[n];
            var r3 = el3.getBoundingClientRect();
            var txt3 = (el3.innerText || '').trim();
            if (r3.x < 500 && r3.width > 100 && r3.height > 40 && txt3.length > 2) {
                report.leftSideItems.push({
                    source: targets[t3].label,
                    tag: el3.tagName.toLowerCase(),
                    cls: (el3.className || '').toString().substring(0, 100),
                    x: Math.round(r3.x), y: Math.round(r3.y),
                    w: Math.round(r3.width), h: Math.round(r3.height),
                    text: txt3.substring(0, 100).replace(/\\n/g, ' | ')
                });
            }
        }
    }

    // 5. 页面URL
    report.url = window.location.href;

    // 限制每个数组最大条目数，避免返回过大
    report.panels = report.panels.slice(0, 80);
    report.leftSideItems = report.leftSideItems.slice(0, 40);

    return JSON.stringify(report);
})()
"""


async def dump_chat_dom() -> Dict:
    """诊断工具: 扫描聊天页DOM结构，返回关键元素的class/text/位置。

    用于调试JS选择器不匹配的问题。返回JSON报告包含:
      - iframes: 所有iframe信息
      - panels: 所有有className的可见容器
      - unreadElements: 包含"未读"文字的元素
      - leftSideItems: 左侧区域(x<500)的列表项
      - url: 当前页面URL
    """
    raw = await automation.execute_js(_JS_DUMP_CHAT_DOM)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"error": "parse_failed", "raw": raw[:500]}
    return raw if isinstance(raw, dict) else {"error": "unexpected_type", "raw": str(raw)[:500]}


async def click_unread_filter() -> Dict:
    """点击聊天页"未读"筛选标签，过滤出有未读消息的会话。

    Returns:
        {status: "ok"|"not_found", message: str}
    """
    result = await automation.execute_js(_JS_CLICK_UNREAD)
    if not isinstance(result, dict):
        result = {}
    if result.get("found"):
        await asyncio.sleep(1.5)  # 等待列表刷新
        logger.info(f"[ChatNav] 已点击'未读'筛选: {result.get('text')}")
        return {"status": "ok", "message": f"已筛选未读消息"}
    else:
        logger.warning("[ChatNav] 未找到'未读'筛选按钮")
        return {"status": "not_found", "message": "未找到未读筛选按钮"}


# JS: 点击"沟通中"筛选标签 — 只显示有沟通记录的联系人（才有简历权限）
_JS_CLICK_COMMUNICATING = """
(function() {
    // 策略1: .chat-message-filter-left 内找"沟通中"
    var filterArea = document.querySelector('.chat-message-filter-left');
    if (filterArea) {
        var spans = filterArea.querySelectorAll('span');
        for (var i = 0; i < spans.length; i++) {
            var t = (spans[i].innerText || '').trim();
            if (t === '沟通中') {
                var r = spans[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    spans[i].click();
                    return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
        }
        var ft = (filterArea.innerText || '').trim();
        if (ft.indexOf('沟通中') >= 0) {
            var fr = filterArea.getBoundingClientRect();
            filterArea.click();
            return {found: true, text: 'filter-click', x: fr.x + fr.width/2, y: fr.y + fr.height/2};
        }
    }
    // 策略2: 全局搜索
    var allSpans = document.querySelectorAll('span');
    for (var j = 0; j < allSpans.length; j++) {
        var st = (allSpans[j].innerText || '').trim();
        if (st === '沟通中') {
            var sr = allSpans[j].getBoundingClientRect();
            if (sr.width > 0 && sr.height > 0 && sr.y < 300) {
                allSpans[j].click();
                return {found: true, text: st, x: sr.x + sr.width/2, y: sr.y + sr.height/2};
            }
        }
    }
    // 策略3: iframe回退
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var idoc = iframe.contentDocument;
        var ispans = idoc.querySelectorAll('span');
        for (var k = 0; k < ispans.length; k++) {
            if ((ispans[k].innerText || '').trim() === '沟通中') {
                var ir = ispans[k].getBoundingClientRect();
                if (ir.width > 0 && ir.height > 0) {
                    ispans[k].click();
                    return {found: true, text: 'iframe-沟通中', x: ir.x + ir.width/2, y: ir.y + ir.height/2};
                }
            }
        }
    }
    return {found: false};
})()
"""


async def click_communicating_filter() -> Dict:
    """点击聊天页"沟通中"筛选标签，只显示有沟通记录的联系人。

    只有"沟通中"的联系人才能请求/下载简历。

    Returns:
        {status: "ok"|"not_found", message: str}
    """
    result = await automation.execute_js(_JS_CLICK_COMMUNICATING)
    if not isinstance(result, dict):
        result = {}
    if result.get("found"):
        await asyncio.sleep(2)  # 等待列表刷新
        logger.info(f"[ChatNav] 已点击'沟通中'筛选: {result.get('text')}")
        return {"status": "ok", "message": f"已筛选沟通中"}
    else:
        logger.warning("[ChatNav] 未找到'沟通中'筛选按钮")
        return {"status": "not_found", "message": "未找到沟通中筛选按钮"}


_JS_CLICK_NEW_GREET = """
(function() {
    var filterArea = document.querySelector('.chat-message-filter-left');
    if (filterArea) {
        var spans = filterArea.querySelectorAll('span');
        for (var i = 0; i < spans.length; i++) {
            var t = (spans[i].innerText || '').trim();
            if (t === '新招呼') {
                var r = spans[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    spans[i].click();
                    return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
        }
        var ft = (filterArea.innerText || '').trim();
        if (ft.indexOf('新招呼') >= 0) {
            var fr = filterArea.getBoundingClientRect();
            filterArea.click();
            return {found: true, text: 'filter-click', x: fr.x + fr.width/2, y: fr.y + fr.height/2};
        }
    }
    var allSpans = document.querySelectorAll('span');
    for (var j = 0; j < allSpans.length; j++) {
        var st = (allSpans[j].innerText || '').trim();
        if (st === '新招呼') {
            var sr = allSpans[j].getBoundingClientRect();
            if (sr.width > 0 && sr.height > 0 && sr.y < 300) {
                allSpans[j].click();
                return {found: true, text: st, x: sr.x + sr.width/2, y: sr.y + sr.height/2};
            }
        }
    }
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var idoc = iframe.contentDocument;
        var ispans = idoc.querySelectorAll('span');
        for (var k = 0; k < ispans.length; k++) {
            if ((ispans[k].innerText || '').trim() === '新招呼') {
                var ir = ispans[k].getBoundingClientRect();
                if (ir.width > 0 && ir.height > 0) {
                    ispans[k].click();
                    return {found: true, text: 'iframe-新招呼', x: ir.x + ir.width/2, y: ir.y + ir.height/2};
                }
            }
        }
    }
    return {found: false};
})()
"""


async def click_new_greet_filter() -> Dict:
    """点击聊天页"新招呼"筛选标签，显示新打招呼的联系人。

    这些联系人还未建立沟通，直接请求简历即可，无需数据库去重检查。

    Returns:
        {status: "ok"|"not_found", message: str}
    """
    result = await automation.execute_js(_JS_CLICK_NEW_GREET)
    if not isinstance(result, dict):
        result = {}
    if result.get("found"):
        await asyncio.sleep(2)
        logger.info(f"[ChatNav] 已点击'新招呼'筛选: {result.get('text')}")
        return {"status": "ok", "message": "已筛选新招呼"}
    else:
        logger.warning("[ChatNav] 未找到'新招呼'筛选按钮")
        return {"status": "not_found", "message": "未找到新招呼筛选按钮"}


_JS_CLICK_RECEIVED_RESUME = """
(function() {
    var filterArea = document.querySelector('.chat-message-filter-left');
    if (filterArea) {
        var spans = filterArea.querySelectorAll('span');
        for (var i = 0; i < spans.length; i++) {
            var t = (spans[i].innerText || '').trim();
            if (t === '已获取简历') {
                var r = spans[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    spans[i].click();
                    return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
                }
            }
        }
    }
    var allSpans = document.querySelectorAll('span');
    for (var j = 0; j < allSpans.length; j++) {
        var st = (allSpans[j].innerText || '').trim();
        if (st === '已获取简历') {
            var sr = allSpans[j].getBoundingClientRect();
            if (sr.width > 0 && sr.height > 0 && sr.y < 300) {
                allSpans[j].click();
                return {found: true, text: st, x: sr.x + sr.width/2, y: sr.y + sr.height/2};
            }
        }
    }
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var idoc = iframe.contentDocument;
        var ispans = idoc.querySelectorAll('span');
        for (var k = 0; k < ispans.length; k++) {
            if ((ispans[k].innerText || '').trim() === '已获取简历') {
                var ir = ispans[k].getBoundingClientRect();
                if (ir.width > 0 && ir.height > 0) {
                    ispans[k].click();
                    return {found: true, text: 'iframe-已获取简历', x: ir.x + ir.width/2, y: ir.y + ir.height/2};
                }
            }
        }
    }
    return {found: false};
})()
"""


async def click_received_resume_filter() -> Dict:
    """点击聊天页"已获取简历"筛选标签，显示已同意分享简历的联系人。"""
    result = await automation.execute_js(_JS_CLICK_RECEIVED_RESUME)
    if not isinstance(result, dict):
        result = {}
    if result.get("found"):
        await asyncio.sleep(2)
        logger.info(f"[ChatNav] 已点击'已获取简历'筛选: {result.get('text')}")
        return {"status": "ok", "message": "已筛选已获取简历"}
    else:
        logger.warning("[ChatNav] 未找到'已获取简历'筛选按钮")
        return {"status": "not_found", "message": "未找到已获取简历筛选按钮"}


async def navigate_to_chat(filter_unread: bool = False) -> Dict:
    """导航到BOSS直聘聊天页。

    必须先加载 SPA shell (/web/chat/recommend)，再点击"沟通"导航。
    聊天页内容在 MAIN document 中（非 iframe），使用 .geek-item-wrap 选择器。

    Args:
        filter_unread: True=先点"未读"筛选再拉取联系人，F7批量回复使用

    Returns:
        {status: "ok"|"error", message: str, contact_count: int, contacts: list}
    """
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接"}

    # 1. 加载 SPA shell（推荐页）
    await automation.navigate("https://www.zhipin.com/web/chat/recommend")
    await asyncio.sleep(4)

    # 2. 点击左侧"沟通"导航（JS DOM点击，触发SPA路由）
    clicked = await automation.execute_js(_JS_CLICK_CHAT_NAV)
    if not isinstance(clicked, dict):
        logger.warning(f"[ChatNav] JS返回了非dict类型: {type(clicked).__name__}")
        clicked = None

    if clicked and clicked.get("found"):
        logger.info(f"[ChatNav] 已点击'沟通': {clicked.get('text')}")
    else:
        logger.warning("[ChatNav] 未找到'沟通'按钮，尝试直接导航到index")
        await automation.navigate("https://www.zhipin.com/web/chat/index")
        await asyncio.sleep(4)

    # 3. 等待联系人列表渲染（BOSS直聘异步加载，需要充足时间）
    await asyncio.sleep(5)

    # 4. 如果筛选未读，先点"未读"再等待列表刷新
    if filter_unread:
        await click_unread_filter()
        await asyncio.sleep(3)

    # 5. 获取联系人列表
    contacts = await get_contacts()
    contact_count = len(contacts) if contacts else 0
    logger.info(f"[ChatNav] 找到 {contact_count} 个联系人{' (未读筛选)' if filter_unread else ''}")
    return {
        "status": "ok",
        "message": f"已进入聊天页",
        "contact_count": contact_count,
        "contacts": contacts,
    }


async def get_contacts() -> List[Dict[str, Any]]:
    """获取左侧联系人列表"""
    result = await automation.execute_js(_JS_GET_CONTACTS)
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and parsed.get("error"):
                logger.error(f"[ChatNav] get_contacts JS异常: {parsed.get('message')} at line {parsed.get('line')}")
            return []
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(result, list):
        return result
    return []


async def get_messages() -> List[Dict[str, Any]]:
    """获取当前聊天消息"""
    result = await automation.execute_js(_JS_GET_MESSAGES)
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            pass
    return result if isinstance(result, list) else []


async def find_input() -> Dict[str, Any]:
    """查找输入框和发送按钮位置"""
    result = await automation.execute_js(_JS_FIND_INPUT_AREA)
    return result if isinstance(result, dict) else {"input": None, "send": None}


async def has_unread() -> Dict[str, Any]:
    """检查是否有未读消息"""
    result = await automation.execute_js(_JS_HAS_UNREAD)
    return result if isinstance(result, dict) else {"hasUnread": False, "count": 0}


async def check_limit_popup() -> Optional[str]:
    """检测限制弹窗（BOSS "已达上限" 等提示）

    扫描页面中所有可见弹窗/对话框/提示，匹配 20+ 限制关键词。

    Returns:
        匹配到的关键词，或 None 表示无限制弹窗
    """
    raw = await automation.execute_js(_JS_CHECK_LIMIT_POPUP)
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    elif isinstance(raw, dict):
        result = raw
    else:
        return None

    if result.get("hit"):
        keyword = result.get("keyword", "")
        logger.warning(f"[ChatNav] 检测到限制弹窗: {keyword}")
        return keyword
    return None


async def dismiss_popup() -> None:
    """关闭弹窗 — 移除 fixed 定位的遮罩层 + 按 Escape"""
    try:
        await automation.execute_js(_JS_DISMISS_POPUP)
        await asyncio.sleep(0.3)
        await automation.press_key("Escape")
        await asyncio.sleep(0.3)
    except Exception as e:
        logger.warning(f"[ChatNav] 关闭弹窗失败: {e}")


async def clear_input() -> bool:
    """清空聊天输入框（兼容 React/Vue 受控组件）

    先用 JS 聚焦输入框并全选内容，再用 Cmd+A + Delete 删除。
    比 el.value='' 更可靠，能触发框架内部状态更新。

    Returns:
        True 表示清空成功
    """
    try:
        # JS 层面聚焦 + 全选
        raw = await automation.execute_js(_JS_CLEAR_INPUT)
        if isinstance(raw, str):
            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                result = {}
        elif isinstance(raw, dict):
            result = raw
        else:
            result = {}

        if not result.get("ok"):
            logger.debug(f"[ChatNav] 清空输入框: {result.get('reason', 'unknown')}")
            return False

        # 系统级删除（JS已全选，BackSpace清空选中内容）
        await automation.press_key("BackSpace")
        await asyncio.sleep(0.2)
        return True
    except Exception as e:
        logger.warning(f"[ChatNav] 清空输入框失败: {e}")
        return False


async def click_contact(name: str, x: float, y: float) -> bool:
    """点击指定联系人（CDP视口坐标，不受Chrome窗口偏移影响）"""
    try:
        ok = await automation.cdp_click_viewport(float(x), float(y))
        await asyncio.sleep(2)
        return ok
    except Exception as e:
        logger.warning(f"[ChatNav] 点击联系人失败: {e}")
        return False


async def type_and_send(message: str) -> Dict:
    """在输入框中输入消息并点击发送（先清空残留文本）"""
    input_info = await find_input()
    send_info = input_info.get("send")
    input_pos = input_info.get("input")

    if not input_pos:
        return {"status": "error", "message": "未找到输入框"}

    try:
        # 点击输入框
        await automation.click(int(input_pos["x"]), int(input_pos["y"]))
        await asyncio.sleep(0.3)

        # 清空残留文本（兼容 React/Vue 受控组件）
        await clear_input()
        await asyncio.sleep(0.2)

        # 输入消息
        await automation.type_text(message)
        await asyncio.sleep(0.5)

        # 按Enter发送
        await automation.press_key("Return")

        await asyncio.sleep(1)
        return {"status": "ok", "message": "已发送"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== 共享工具：逐次查找联系人 + 滚动 =====

_JS_FIND_CONTACT_BY_NAME = """
(function() {
    var targetName = {NAME_PLACEHOLDER};
    var vw = Math.max(window.innerWidth, 1000);

    function findInDoc(doc) {
        var items = doc.querySelectorAll('.geek-item-wrap');
        if (items.length > 0) {
            for (var i = 0; i < items.length; i++) {
                var t = (items[i].innerText || '').trim();
                if (t.indexOf(targetName) >= 0) {
                    var r = items[i].getBoundingClientRect();
                    if (r.width > 80 && r.height > 30) {
                        var parts = t.split(/[\\n]+/).filter(function(l) { return l.trim().length > 0; });
                        var name = parts[0] || '';
                        var topEl = items[i].querySelector('.geek-item-top');
                        if (topEl) {
                            var topText = (topEl.innerText || '').trim();
                            var topParts = topText.split(/[\\n]+/);
                            if (topParts[0]) name = topParts[0].trim();
                        }
                        return {
                            name: name, text: t,
                            x: r.x + r.width / 2, y: r.y + r.height / 2,
                            visible: r.y > 0 && r.y < window.innerHeight
                        };
                    }
                }
            }
        }
        var leftBoundary = vw * 0.45;
        var allEls = doc.querySelectorAll('div, li, a');
        for (var j = 0; j < allEls.length; j++) {
            var rr = allEls[j].getBoundingClientRect();
            var tt = (allEls[j].innerText || '').trim();
            if (rr.x >= 0 && rr.x < leftBoundary
                && rr.width > 60 && rr.height > 20
                && tt.length > 1 && tt.indexOf(targetName) >= 0) {
                return {
                    name: (tt.split('\\n')[0] || '').trim(), text: tt,
                    x: rr.x + rr.width / 2, y: rr.y + rr.height / 2,
                    visible: rr.y > 0 && rr.y < window.innerHeight
                };
            }
        }
        return null;
    }

    var result = findInDoc(document);
    if (result) return result;
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var ifResult = findInDoc(iframe.contentDocument);
        if (ifResult) return ifResult;
    }
    return null;
})()
"""

_JS_SCROLL_TO_CONTACT = """
(function() {
    var targetName = {NAME_PLACEHOLDER};
    var items = document.querySelectorAll('.geek-item-wrap');
    for (var i = 0; i < items.length; i++) {
        var t = (items[i].innerText || '').trim();
        if (t.indexOf(targetName) >= 0) {
            items[i].scrollIntoView({block: 'nearest', behavior: 'instant'});
            return {scrolled: true, name: (t.split('\\n')[0] || '').trim()};
        }
    }
    return {scrolled: false};
})()
"""


async def refind_contact(contact_name: str) -> Optional[Dict]:
    """逐次提取单个联系人的最新坐标（解决一次性提取过期问题）。"""
    try:
        safe_name = json.dumps(contact_name)
        script = _JS_FIND_CONTACT_BY_NAME.replace("{NAME_PLACEHOLDER}", safe_name)
        result = await automation.execute_js(script)
        if isinstance(result, dict) and result.get("x") is not None:
            return result
    except Exception as e:
        logger.debug(f"[ChatNav] refind_contact({contact_name}) 失败: {e}")
    return None


async def scroll_contact_into_view(contact_name: str) -> None:
    """滚动联系人列表使目标联系人落入视口。"""
    try:
        safe_name = json.dumps(contact_name)
        script = _JS_SCROLL_TO_CONTACT.replace("{NAME_PLACEHOLDER}", safe_name)
        result = await automation.execute_js(script)
        if isinstance(result, dict) and result.get("scrolled"):
            logger.info(f"[ChatNav] 已滚动列表至: {contact_name}")
    except Exception as e:
        logger.debug(f"[ChatNav] 滚动失败: {e}")
