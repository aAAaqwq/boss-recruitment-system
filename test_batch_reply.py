#!/usr/bin/env python3
"""批量AI回复 - 基于test_llm.py完全一致的消息提取+LLM调用逻辑"""
import json, re, os, sys, time, random
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

API_BASE = 'http://localhost:8002'
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

# ===== JS片段 =====

_JS_GET_MESSAGES = """(function(){
    var vw=Math.max(window.innerWidth,1000);
    var result=[];
    var seen={};
    function isMe(el,r,cls){
        if(cls.indexOf("self")>=0||cls.indexOf("mine")>=0||cls.indexOf("right")>=0||cls.indexOf("send")>=0||cls.indexOf("boss")>=0)return true;
        if(r.x>vw*0.58)return true;
        return false;
    }
    var chatBox=document.querySelector(".chat-conversation");
    if(!chatBox)return JSON.stringify([]);
    if(chatBox.querySelector(".conversation-no-data"))return JSON.stringify([]);
    function tryCapture(el,text){
        if(text.length<2||text.length>600)return;
        var r=el.getBoundingClientRect();
        if(r.width<10||r.height<10||r.width>650)return;
        var cls=(el.className||"").toString().toLowerCase();
        if(cls.indexOf("input")>=0||cls.indexOf("editor")>=0)return;
        if(el.tagName==="TEXTAREA"||el.tagName==="INPUT")return;
        var key=text.substring(0,40)+'@'+Math.round(r.y/5);
        if(seen[key])return;
        seen[key]=true;
        result.push({text:text,isMe:isMe(el,r,cls),x:Math.round(r.x),y:Math.round(r.y)});
    }
    function walk(el){
        for(var i=0;i<el.childNodes.length;i++){
            var node=el.childNodes[i];
            if(node.nodeType===3){
                var t=(node.textContent||"").trim();
                if(t)tryCapture(el,t);
            }
        }
        if(el.children.length===0){
            var full=(el.textContent||"").trim();
            if(full)tryCapture(el,full);
            return;
        }
        for(var j=0;j<el.children.length;j++)walk(el.children[j]);
    }
    walk(chatBox);
    result.sort(function(a,b){return a.y-b.y;});
    return JSON.stringify(result);
})()"""

_JS_CLICK_UNREAD = """
(function() {
    var tabs = document.querySelectorAll('.chat-tabs span, .tab-item, [class*="tab"] span, [class*="tab"] div');
    for (var i = 0; i < tabs.length; i++) {
        if ((tabs[i].textContent || '').trim() === '未读') {
            tabs[i].click();
            return 'clicked';
        }
    }
    // fallback: find by text
    var all = document.querySelectorAll('span, div, a, li');
    for (var j = 0; j < all.length; j++) {
        var t = (all[j].textContent || '').trim();
        if (t === '未读' && all[j].offsetHeight > 0 && all[j].offsetWidth > 0) {
            all[j].click();
            return 'clicked_fallback';
        }
    }
    return 'not_found';
})()"""

_JS_GET_CONTACTS = """
(function() {
    try {
        var contacts = [];
        var items = document.querySelectorAll('.geek-item-wrap');
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
                    contacts.push({
                        name: name,
                        subtitle: subtitle,
                        x: Math.round(r.x + r.width / 2),
                        y: Math.round(r.y + r.height / 2),
                        hasUnread: t.indexOf('\\u25cf') >= 0 || t.indexOf('未读') >= 0
                    });
                }
            } catch(e2) {}
        }
        return JSON.stringify(contacts);
    } catch(e) {
        return JSON.stringify({error: 'JS_EXCEPTION', message: e.message || String(e), line: e.lineNumber});
    }
})()"""

_JS_CLICK_AT = """
(function() {
    var x = %s, y = %s;
    var el = document.elementFromPoint(x, y);
    if (el) {
        el.click();
        return 'clicked';
    }
    return 'no_element';
})()"""

_JS_FIND_INPUT = """
(function() {
    var inputs = document.querySelectorAll('textarea, [contenteditable="true"], [class*="input"] textarea, [class*="editor"], [class*="chat-input"], [class*="input-area"], [class*="send-area"], [class*="type-area"]');
    for (var i = 0; i < inputs.length; i++) {
        var r = inputs[i].getBoundingClientRect();
        if (r.width > 100 && r.height > 20) {
            return JSON.stringify({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)});
        }
    }
    return 'null';
})()"""


# ===== API helpers =====

def api_exec(script: str, timeout: int = 15):
    """执行浏览器JS"""
    req = urllib.request.Request(f'{API_BASE}/api/browser/execute',
        data=json.dumps({'script': script}).encode(),
        headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read())
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    return data


def api_type_send(text: str):
    """输入并发送消息"""
    req = urllib.request.Request(f'{API_BASE}/api/browser/type-send',
        data=json.dumps({'script': text}).encode(),
        headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


# ===== 过滤逻辑（与test_llm.py完全一致）=====

UI_SKIP = {
    '没有更多了', '全部职位', '全部', '未读', '已读',
    '沟通中', '不限', '筛选', '发送', '我知道了',
    '求简历', '换电话', '换微信', '不合适',
    '刚刚活跃', '今日活跃', '在线',
    '同意', '拒绝', '接收', '忽略',
    '对方想发送附件简历给您，您是否同意',
    '您可以在这里直接对牛人发起',
    '在线简历', '附件简历',
    '工作经历', '未填写工作经历',
    '沟通职位：', '期望：',
    '送达', '约面试',
}


def is_ui_noise(text: str) -> bool:
    t = text.strip()
    if not t: return True
    if t in UI_SKIP: return True
    if len(t) <= 8 and (t.endswith('月') or t.endswith('日') or ':' in t or t.isdigit()): return True
    if re.match(r'^\d{1,2}岁$', t): return True
    if re.match(r'^\d{1,2}年(应届生)?$', t): return True
    if t in ('本科', '硕士', '博士', '大专'): return True
    if re.match(r'^[一-鿿]{2,8}(大学|学院)$', t): return True
    return False


def filter_messages(msgs):
    filtered = []
    for m in msgs:
        t = m.get('text', '').strip()
        if is_ui_noise(t): continue
        filtered.append(m)
    return filtered


def get_candidate_msg(filtered):
    for m in reversed(filtered):
        if not m.get('isMe'):
            return m.get('text', '').strip()
    return ''


def build_llm_context(filtered, candidate_msg):
    """与test_llm.py完全一致的LLM上下文构建"""
    history = []
    for m in filtered[-12:]:
        role = 'assistant' if m.get('isMe') else 'user'
        history.append({'role': role, 'content': m.get('text', '')})

    # 加载岗位信息
    company_context = ''
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'job_info', 'company_profile.txt')
    try:
        with open(profile_path, encoding='utf-8') as f:
            company_context = f.read().strip()
    except Exception as e:
        print(f'[WARN] 无法读取岗位信息: {e}')

    system_prompt = (
        (company_context + '\n\n' if company_context else '') +
        '你是一名专业的招聘官，正在通过BOSS直聘与候选人交流。'
        '要求：'
        '1. 回复简洁自然，不超过80字'
        '2. 语气友好、专业，像真人对话'
        '3. 严禁向候选人索要微信、电话、转账或任何敏感联系方式'
        '4. 不承诺offer录用'
        '5. 回复时结合公司和岗位背景信息，根据候选人问题进行针对性回复'
    )

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history[-10:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": f"候选人说：{candidate_msg}"})
    return messages


def call_llm(messages):
    """调用DeepSeek API"""
    ds_req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions',
        data=json.dumps({"model": "deepseek-chat", "messages": messages, "temperature": 0.7, "max_tokens": 150}).encode(),
        headers={'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'})
    ds_resp = urllib.request.urlopen(ds_req, timeout=30)
    ds_data = json.loads(ds_resp.read())
    reply = ds_data.get('choices', [{}])[0].get('message', {}).get('content', '')
    return reply.strip(), ds_data.get('error', {}).get('message', '')


def navigate_to_chat_unread():
    """导航到聊天页 + 点击未读筛选"""
    print('[NAV] 导航到聊天页...')
    nav_req = urllib.request.Request(f'{API_BASE}/api/browser/navigate',
        data=json.dumps({'url': 'https://www.zhipin.com/web/chat/index'}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(nav_req, timeout=15)
    except Exception as e:
        print(f'[NAV] 导航请求异常(可忽略): {e}')
    time.sleep(5)

    print('[NAV] 点击未读筛选...')
    result = api_exec(_JS_CLICK_UNREAD)
    print(f'[NAV] 未读筛选: {result}')
    time.sleep(2)

    contacts_raw = api_exec(_JS_GET_CONTACTS)
    contacts = json.loads(contacts_raw) if isinstance(contacts_raw, str) else contacts_raw
    if isinstance(contacts, dict) and contacts.get('error'):
        print(f'[NAV] JS异常: {contacts}')
        return []
    if not isinstance(contacts, list):
        print(f'[NAV] 非预期类型: {type(contacts)}')
        return []
    print(f'[NAV] 获取到 {len(contacts)} 个联系人')
    for c in contacts[:5]:
        print(f'  - {c.get("name")} ({c.get("subtitle")}) unread={c.get("hasUnread")}')
    return contacts


def click_contact(name, x, y):
    """点击联系人"""
    print(f'[CLICK] 点击 {name} ({x}, {y})')
    js = _JS_CLICK_AT % (x, y)
    result = api_exec(js)
    print(f'[CLICK] 结果: {result}')
    time.sleep(2)


def process_one_contact(name, x, y):
    """处理单个候选人：点击→提取→LLM→发送"""
    click_contact(name, x, y)

    # 提取消息
    msgs_raw = api_exec(_JS_GET_MESSAGES)
    msgs = json.loads(msgs_raw) if isinstance(msgs_raw, str) else msgs_raw

    # 过滤
    filtered = filter_messages(msgs)
    candidate_msg = get_candidate_msg(filtered)
    if not candidate_msg:
        print(f'[SKIP] {name}: 无候选人消息')
        return False

    print(f'[{name}] raw={len(msgs)} filtered={len(filtered)} msg="{candidate_msg[:60]}"')

    # 构建LLM上下文
    messages = build_llm_context(filtered, candidate_msg)
    print(f'[{name}] LLM上下文 ({len(messages)} 条):')
    for i, m in enumerate(messages):
        print(f'  [{i}] [{m["role"][:1].upper()}] {m["content"][:100]}')

    # 调用DeepSeek
    reply, error = call_llm(messages)
    if not reply:
        print(f'[{name}] AI生成失败: {error}')
        return False

    print(f'[{name}] AI回复: {reply}')

    # 发送
    send_result = api_type_send(reply)
    print(f'[{name}] 发送结果: {send_result}')
    return send_result.get('status') == 'ok'


def batch_reply(max_count: int = 5):
    """批量回复主流程"""
    print(f'=== 批量AI回复 max={max_count} ===')

    contacts = navigate_to_chat_unread()
    if not contacts:
        print('没有联系人')
        return

    unread = [c for c in contacts if c.get('hasUnread')]
    if unread:
        targets = unread[:max_count]
        print(f'联系人: {len(contacts)} 个, 未读: {len(unread)} 个, 处理: {len(targets)} 个')
    else:
        targets = contacts[:max_count]
        print(f'联系人: {len(contacts)} 个, 无未读, 处理前 {len(targets)} 个')

    success = 0
    failed = 0
    for i, c in enumerate(targets):
        print(f'\n--- [{i+1}/{len(targets)}] {c["name"]} ---')
        try:
            if process_one_contact(c['name'], c['x'], c['y']):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f'[ERROR] {c["name"]}: {e}')
            failed += 1

        if i < len(targets) - 1:
            delay = random.uniform(2, 5)
            print(f'[WAIT] {delay:.1f}s...')
            time.sleep(delay)

    print(f'\n=== 完成: 成功{success}, 失败{failed}, 共{len(targets)} ===')


if __name__ == '__main__':
    if not DEEPSEEK_API_KEY:
        print('请设置 DEEPSEEK_API_KEY 环境变量')
        sys.exit(1)

    batch_reply(max_count=3)
