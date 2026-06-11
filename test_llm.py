import json, re, os, sys
import urllib.request

# ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# 1. get messages from current chat
js = """(function(){
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

req = urllib.request.Request('http://localhost:8002/api/browser/execute',
    data=json.dumps({'script': js}).encode(),
    headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req, timeout=15)
data = json.loads(resp.read())
msgs = json.loads(data) if isinstance(data, str) else data

# 2. filter ui noise
UI_SKIP = {
    '没有更多了',  # 没有更多了
    '全部职位',        # 全部职位
    '全部', '未读', '已读',  # 全部,未读,已读
    '沟通中',              # 沟通中
    '不限', '筛选',    # 不限,筛选
    '发送', '我知道了',  # 发送,我知道了
    '求简历', '换电话', '换微信', '不合适',
    '刚刚活跃',        # 刚刚活跃
    '今日活跃',        # 今日活跃
    '在线',                    # 在线
    '同意', '拒绝', '接收', '忽略',
    '对方想发送附件简历给您，您是否同意',
    '您可以在这里直接对牛人发起',
    '在线简历', '附件简历',
    '工作经历', '未填写工作经历',
    '沟通职位：', '期望：',
    '送达', '约面试',
}

filtered = []
for m in msgs:
    t = m.get('text', '').strip()
    if not t: continue
    if t in UI_SKIP: continue
    if len(t) <= 8 and (t.endswith('月') or t.endswith('日') or ':' in t or t.isdigit()): continue
    if re.match(r'^\d{1,2}岁$', t): continue       # XX岁
    if re.match(r'^\d{1,2}年(应届生)?$', t): continue  # X年(应届生)
    if t in ('本科', '硕士', '博士', '大专'): continue
    if re.match(r'^[一-鿿]{2,8}(大学|学院)$', t): continue
    filtered.append(m)

# find candidate latest msg
candidate_msg = ''
for m in reversed(filtered):
    if not m.get('isMe'):
        candidate_msg = m.get('text', '').strip()
        break

print(f'raw={len(msgs)} filtered={len(filtered)} candidate_msg="{candidate_msg}"')

# 3. build history for LLM
history = []
for m in filtered[-12:]:
    role = 'assistant' if m.get('isMe') else 'user'
    history.append({'role': role, 'content': m.get('text', '')})

script_dir = os.path.dirname(os.path.abspath(__file__))
profile_path = os.path.join(script_dir, 'job_info', 'company_profile.txt')
company_context = ''
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

print('=== LLM CONTEXT ===')
for i, m in enumerate(messages):
    print(f'[{i}] [{m["role"][:1].upper()}] {m["content"][:150]}')

# 4. call DeepSeek
api_key = os.environ.get('DEEPSEEK_API_KEY', '')
if not api_key:
    print('\n=== NO API KEY ===')
    sys.exit(0)

ds_req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions',
    data=json.dumps({"model": "deepseek-chat", "messages": messages, "temperature": 0.7, "max_tokens": 150}).encode(),
    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'})
ds_resp = urllib.request.urlopen(ds_req, timeout=30)
ds_data = json.loads(ds_resp.read())
reply = ds_data.get('choices', [{}])[0].get('message', {}).get('content', '')
error = ds_data.get('error', {}).get('message', '')
print(f'\n=== AI REPLY ===')
print(reply if reply else f'ERROR: {error}')

if not reply:
    sys.exit(1)

# 5. type and send the reply
print('\n=== SENDING ===')
send_req = urllib.request.Request('http://localhost:8002/api/browser/type-send',
    data=json.dumps({'script': reply}).encode(),
    headers={'Content-Type': 'application/json'})
try:
    send_resp = urllib.request.urlopen(send_req, timeout=15)
    send_data = json.loads(send_resp.read())
    print(f'发送结果: {send_data}')
except Exception as e:
    print(f'发送失败: {e}')
