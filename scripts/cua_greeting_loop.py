#!/usr/bin/env python3
"""
cua-driver 驱动的 BOSS直聘打招呼
==================================

用法:
  python scripts/cua_greeting_loop.py              # 刷新→扫描→打招呼(最多5人)
  python scripts/cua_greeting_loop.py --dry-run    # 仅预览
  python scripts/cua_greeting_loop.py --limit 3    # 最多打3人
  python scripts/cua_greeting_loop.py --no-refresh # 不刷新,用当前页
"""
import argparse, json, random, subprocess, sys, time, re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.filter_criteria import ALL_ELITE_SCHOOLS, match_school

SESSION_ID = "boss-greeting"
CHROME_BUNDLE_ID = "com.google.Chrome"

# ── 限制检测关键词 ──
LIMIT_KEYWORDS = [
    # 打招呼次数限制 (完整短语, 避免误匹配)
    "已达上限", "次数已用完", "今日已达", "已达每日",
    "沟通人数已达", "打招呼次数", "超出限制",
    "明天再来", "今日上限", "已达当天",
    "每天最多", "上限了", "用完了", "今日沟通",
    # 开料权益限制
    "权益不足", "开料次数", "剩余次数", "次数不足",
    "会员权益", "升级会员", "额度不足", "免费次数",
    "今日剩余",
]


def cua(*args: str) -> dict:
    cmd = ["cua-driver"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {}
    stdout = result.stdout.strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"text": stdout[:200]}


# ══════════════════════════════════════════════════
# 页面加载等待
# ══════════════════════════════════════════════════

def wait_for_page(pid: int, window_id: int, timeout: float = 15.0, label: str = "") -> bool:
    """等待 SPA 渲染完成。双重检测: JS readyState + AX 树卡片数"""
    prefix = f"[{label}] " if label else ""
    delays = [0.5, 0.5, 1.0, 1.0, 1.5, 1.5, 2.0, 2.0, 3.0, 3.0]
    elapsed = 0.0

    for delay in delays:
        time.sleep(delay)
        elapsed += delay

        # 1: JS readyState
        r = cua("page", json.dumps({
            "pid": pid, "window_id": window_id,
            "action": "execute_javascript",
            "javascript": "document.readyState",
        }))
        ready_val = " ".join(str(x) for x in r) if isinstance(r, list) else str(r.get("result", r.get("text", "")))
        if ready_val.strip().strip('"') != "complete":
            continue

        # 2: AX 树
        snap = cua("get_window_state", json.dumps({"pid": pid, "window_id": window_id}))
        tree = snap.get("tree_markdown", "")
        greet_count = tree.count("打招呼") if tree else 0
        elem_count = snap.get("element_count", 0)

        if greet_count >= 5 and elem_count > 500:
            print(f"  {prefix}✓ 就绪 ({greet_count}卡片, {elapsed:.1f}s)")
            return True
        if greet_count > 0:
            print(f"  {prefix}加载中... ({greet_count}卡片, {elapsed:.1f}s)")

    print(f"  {prefix}⚠ 超时 ({elapsed:.1f}s)")
    return False


# ══════════════════════════════════════════════════
# 限制检测
# ══════════════════════════════════════════════════

def dismiss_limit_popup(pid: int, window_id: int):
    """关闭限制弹窗 — JS移除DOM (BOSS弹窗无AX关闭按钮,像素点击也常无效)"""
    print(f"  关闭弹窗...", end=" ", flush=True)

    # 直接移除弹窗DOM (最可靠)
    r = cua("page", json.dumps({
        "pid": pid, "window_id": window_id,
        "action": "execute_javascript",
        "javascript": """
        (function(){
            var removed = 0;
            document.querySelectorAll(
                '.dialog-wrap, [class*=overlay], [class*=mask], [class*=backdrop], ' +
                '.boss-popup__wrapper, [class*=modal]'
            ).forEach(function(el){
                var s = getComputedStyle(el);
                if ((s.position === 'fixed' || s.zIndex > 100) && s.display !== 'none') {
                    el.remove(); removed++;
                }
            });
            return 'removed ' + removed;
        })()
        """
    }))
    time.sleep(0.3)

    # Escape 兜底
    cua("press_key", json.dumps({"pid": pid, "window_id": window_id, "key": "escape"}))
    time.sleep(0.3)

    # 验证
    snap = cua("get_window_state", json.dumps({"pid": pid, "window_id": window_id}))
    tree = snap.get("tree_markdown", "")
    closed = not any(kw in tree for kw in LIMIT_KEYWORDS)
    print("✓ 已关闭" if closed else "⚠ 仍在")


def check_limit_popup(pid: int, window_id: int) -> Optional[str]:
    """点击打招呼后检测是否弹出每日上限提示

    BOSS直聘限制弹窗出现在点击"打招呼"按钮之后:
      - toast: 页面顶部/中间浮层提示
      - modal: 居中弹窗 "今日沟通人数已达上限"
      - 按钮变灰/消失
    """
    # 快速轮询 3 次 (弹窗通常在 0.3-0.8s 内出现)
    for attempt in range(3):
        if attempt > 0:
            time.sleep(0.4)

        # 1. JS 只扫描可见弹窗/toast (跳过隐藏和固定侧边栏)
        r = cua("page", json.dumps({
            "pid": pid, "window_id": window_id,
            "action": "execute_javascript",
            "javascript": """
            (function(){
                var texts = [];
                document.querySelectorAll(
                    '[class*=toast], [class*=popup], [class*=modal], [class*=dialog], ' +
                    '[class*=notice], [class*=tip], [class*=message], [class*=snackbar], ' +
                    '[class*=alert], [class*=confirm]'
                ).forEach(function(el){
                    var style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return;
                    var rect = el.getBoundingClientRect();
                    if (rect.width < 50 || rect.height < 10) return;
                    var t = (el.textContent || '').trim();
                    if (t.length > 2 && t.length < 200) texts.push(t);
                });
                return JSON.stringify(texts);
            })()
            """
        }))
        popup_text = " ".join(str(x) for x in r) if isinstance(r, list) else str(r.get("result", r.get("text", "")))
        for kw in LIMIT_KEYWORDS:
            if kw in popup_text:
                return f"弹窗: {kw}"

        # 2. AX 树扫描 (兜底 JS 不可达的情况)
        snap = cua("get_window_state", json.dumps({"pid": pid, "window_id": window_id}))
        tree = snap.get("tree_markdown", "")
        for line in tree.split("\n"):
            for kw in LIMIT_KEYWORDS:
                if kw in line and ("StaticText" in line or "AXButton" in line or "AXGroup" in line):
                    return f"页面: {kw}"

        # 3. 检查打招呼按钮是否仍然存在 (按钮消失=可能已达上限)
        greet_count = tree.count("打招呼") if tree else 0
        if greet_count == 0:
            return "按钮消失: 页面可能已切换或触发限制"

    return None


# ══════════════════════════════════════════════════
# 核心流程
# ══════════════════════════════════════════════════

def start_session():
    print("1. 启动会话...")
    if "running" not in str(cua("status")).lower():
        subprocess.run(["cua-driver", "serve"], capture_output=True)
        time.sleep(1)
    cua("start_session", json.dumps({"session": SESSION_ID}))


def find_boss_window() -> dict:
    print("2. 查找 BOSS直聘窗口...")
    apps = cua("list_apps")
    chrome_pid = None
    for app in apps.get("apps", []):
        if app.get("bundle_id") == CHROME_BUNDLE_ID and app.get("running"):
            chrome_pid = app.get("pid")
            break
    if not chrome_pid:
        print("  ❌ Chrome 未运行"); sys.exit(1)

    lw = cua("list_windows", json.dumps({"pid": chrome_pid}))
    for w in lw.get("windows", []):
        title = w.get("title", "")
        if ("BOSS" in title or "zhipin" in title) and w.get("is_on_screen"):
            print(f"  ✓ id={w['window_id']} '{title[:60]}'")
            return {"pid": chrome_pid, "window_id": w["window_id"]}

    for w in lw.get("windows", []):
        if "BOSS" in w.get("title", "") or "zhipin" in w.get("title", ""):
            print(f"  ⚠ 窗口隐藏, 请点 Dock 中 Chrome 使其可见"); sys.exit(1)

    print("  ❌ 找不到 BOSS直聘窗口"); sys.exit(1)


def refresh_page(pid: int, window_id: int):
    print("3. 刷新页面...")
    cua("hotkey", json.dumps({"pid": pid, "window_id": window_id, "keys": ["cmd", "r"]}))
    wait_for_page(pid, window_id, label="刷新")


def scan_candidates(pid: int, window_id: int) -> list[dict]:
    print("4. 扫描候选人...")
    snap = cua("get_window_state", json.dumps({"pid": pid, "window_id": window_id}))
    tree = snap.get("tree_markdown", "")
    if not tree:
        print("  ⚠ AX 树为空"); return []

    candidates = []
    current = {}
    for line in tree.split("\n"):
        s = line.strip()

        m = re.search(r'AXStaticText\s*=\s*"([一-龥]{2,8}(?:大学|学院|学校))"', s)
        if m: current["school"] = m.group(1)

        m = re.search(r'AXStaticText\s*=\s*"(博士|硕士|本科|大专)"', s)
        if m and "school" in current: current["degree"] = m.group(1)

        m = re.search(r'AXImage\s*\(\s*(\S+?)\s*\)', s)
        if m:
            name = m.group(1)
            if not name.startswith("/") and "." not in name and len(name) < 20:
                current["name"] = name

        if "打招呼" in s and "AXButton" in s:
            m = re.search(r'\[(\d+)\]', s)
            if m: current["greet_index"] = int(m.group(1))
            if current.get("school"):
                candidates.append(dict(current))
            current = {}

    seen = set()
    unique = []
    for c in candidates:
        key = (c.get("name", ""), c.get("school", ""))
        if key not in seen and key[0] != "":
            seen.add(key); unique.append(c)

    print(f"  找到 {len(unique)} 人")
    return unique


def greet_candidates(pid: int, wid: int, passed: list[dict]):
    """打招呼 + 上限检测"""
    print(f"\n6. 打招呼 ({len(passed)} 人)...")

    for i, c in enumerate(passed):
        name = c.get("name", f"#{i+1}")
        idx = c.get("greet_index")
        if not idx:
            print(f"  [{i+1}/{len(passed)}] {name} ⚠ 无按钮"); continue

        # 等页面稳定
        if i > 0:
            wait_for_page(pid, wid, timeout=6.0, label=f"间隔{i}")

        # 点击
        print(f"  [{i+1}/{len(passed)}] {name} (idx={idx})...", end=" ", flush=True)
        result = cua("click", json.dumps({"pid": pid, "window_id": wid, "element_index": idx}))
        err = result.get("error", "")
        print("✅" if not err else f"❌ {err}")

        # 立即检测上限弹窗 (BOSS直聘在点击后即刻弹出)
        limit = check_limit_popup(pid, wid)
        if limit:
            print(f"  🛑 {limit}")
            dismiss_limit_popup(pid, wid)
            print(f"\n⏹ 已达上限 ({i+1}/{len(passed)} 人已打招呼)")
            return i + 1

        time.sleep(random.uniform(1.5, 3))

    print(f"\n✅ 完成: {len(passed)} 人")
    return len(passed)


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="cua-driver 驱动 BOSS直聘打招呼")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--schools", type=str)
    args = parser.parse_args()

    school_whitelist = (
        [s.strip() for s in args.schools.split(",")]
        if args.schools else ALL_ELITE_SCHOOLS
    )

    print("=" * 50)
    print(f"BOSS打招呼 | {len(school_whitelist)}所学校 | 上限{args.limit}人 | "
          f"{'预览' if args.dry_run else '执行'}{' | 不刷新' if args.no_refresh else ''}")
    print("=" * 50)

    start_session()
    chrome = find_boss_window()
    pid, wid = chrome["pid"], chrome["window_id"]

    if not args.no_refresh:
        refresh_page(pid, wid)

    candidates = scan_candidates(pid, wid)
    if not candidates:
        print("\n⚠ 未找到候选人"); sys.exit(1)

    print(f"5. 学校筛选...")
    passed = [c for c in candidates if match_school(c.get("school", ""), school_whitelist)]
    passed = passed[:args.limit]
    print(f"  命中 {len(passed)}/{len(candidates)}")

    for c in candidates:
        hit = "✅" if c in passed else "  "
        print(f"  [{c.get('greet_index','?'):>4}] {hit} {c.get('name','?'):8s} | {c.get('school','?'):14s} | {c.get('degree','?'):4s}")

    if args.dry_run:
        print(f"\n⚠ 预览模式"); return
    if not passed:
        print("\n无命中"); return

    greet_candidates(pid, wid, passed)


if __name__ == "__main__":
    main()
