#!/usr/bin/env python3
"""F6+F7 视觉验收验证脚本 (静态检查，无需浏览器)

验证所有 JS 提取脚本的格式、完整性、合法性。
检查关键词列表、模式列表覆盖率。
输出视觉测试就绪报告。

用法:
    python3 tests/run_visual_checks.py
    python3 tests/run_visual_checks.py --verbose
"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
INFO = "ℹ️"

results: dict[str, list[tuple[str, bool, str]]] = {
    "F6 JS Scripts": [],
    "F7 JS Scripts": [],
    "Keywords & Patterns": [],
    "Import Integrity": [],
}


def check(name: str, condition: bool, detail: str = "", category: str = "F6 JS Scripts"):
    results[category].append((name, condition, detail))


# ══════════════════════════════════════════════════
# F6: resume_collector.py JS 脚本检查
# ══════════════════════════════════════════════════

def check_f6_js_scripts():
    from app.resume_collector import (
        _JS_FIND_RESUME_BTNS,
        _JS_FIND_DOWNLOAD_BTN,
        _JS_DETECT_RESUME_CASE,
        _JS_FIND_CONTACT_BY_NAME,
        _JS_VERIFY_CHAT_PANEL,
    )

    scripts = {
        "_JS_FIND_RESUME_BTNS": _JS_FIND_RESUME_BTNS,
        "_JS_FIND_DOWNLOAD_BTN": _JS_FIND_DOWNLOAD_BTN,
        "_JS_DETECT_RESUME_CASE": _JS_DETECT_RESUME_CASE,
        "_JS_FIND_CONTACT_BY_NAME": _JS_FIND_CONTACT_BY_NAME,
        "_JS_VERIFY_CHAT_PANEL": _JS_VERIFY_CHAT_PANEL,
    }

    for name, script in scripts.items():
        # 1. 非空字符串
        check(f"{name}: 非空", isinstance(script, str) and len(script) > 20,
              f"长度: {len(script)}")

        # 2. IIFE 包装
        check(f"{name}: IIFE包装", "(function()" in script)

        # 3. 有 return 语句
        check(f"{name}: 有return", "return" in script)

        # 4. 没有明显的 JS 语法错误标记
        single_q = script.count("'")
        double_q = script.count('"')
        check(f"{name}: 引号平衡",
              single_q % 2 == 0 and double_q % 2 == 0,
              f"单引号={single_q}, 双引号={double_q}")

        # 5. 花括号平衡
        check(f"{name}: 花括号平衡",
              abs(script.count("{") - script.count("}")) <= 2,
              f"{{ = {script.count('{')}, }} = {script.count('}')}")

        # 6. 圆括号平衡 (容忍 ±2，因字符串内转义)
        paren_diff = abs(script.count("(") - script.count(")"))
        check(f"{name}: 圆括号平衡",
              paren_diff <= 2,
              f"( = {script.count('(')}, ) = {script.count(')')}, diff={paren_diff}")

    # 特定检查
    check("FIND_RESUME_BTNS: 4种文本",
          all(t in _JS_FIND_RESUME_BTNS for t in ["在线简历", "附件简历", "查看简历", "查看附件"]))

    check("FIND_DOWNLOAD_BTN: fallback a[download]",
          'a[download]' in _JS_FIND_DOWNLOAD_BTN)

    check("DETECT_RESUME_CASE: 5种case",
          all(ct in _JS_DETECT_RESUME_CASE
              for ct in ["pdf_preview", "request_popup", "request_pending", "need_reply", "unknown"]))

    check("FIND_CONTACT_BY_NAME: NAME_PLACEHOLDER 模板",
          "{NAME_PLACEHOLDER}" in _JS_FIND_CONTACT_BY_NAME)

    check("VERIFY_CHAT_PANEL: NAME_PLACEHOLDER 模板",
          "{NAME_PLACEHOLDER}" in _JS_VERIFY_CHAT_PANEL)


# ══════════════════════════════════════════════════
# F7: chat_nav.py JS 脚本检查
# ══════════════════════════════════════════════════

def check_f7_js_scripts():
    from app.chat_nav import (
        _JS_CLICK_CHAT_NAV,
        _JS_GET_CONTACTS,
        _JS_GET_MESSAGES,
        _JS_FIND_INPUT_AREA,
        _JS_CHECK_LIMIT_POPUP,
        _JS_DISMISS_POPUP,
        _JS_CLEAR_INPUT,
    )

    scripts = {
        "_JS_CLICK_CHAT_NAV": _JS_CLICK_CHAT_NAV,
        "_JS_GET_CONTACTS": _JS_GET_CONTACTS,
        "_JS_GET_MESSAGES": _JS_GET_MESSAGES,
        "_JS_FIND_INPUT_AREA": _JS_FIND_INPUT_AREA,
        "_JS_CHECK_LIMIT_POPUP": _JS_CHECK_LIMIT_POPUP,
        "_JS_DISMISS_POPUP": _JS_DISMISS_POPUP,
        "_JS_CLEAR_INPUT": _JS_CLEAR_INPUT,
    }

    for name, script in scripts.items():
        check(f"{name}: 非空", isinstance(script, str) and len(script) > 20,
              f"长度: {len(script)}", "F7 JS Scripts")

        check(f"{name}: IIFE包装", "(function()" in script, category="F7 JS Scripts")

        brace_diff = abs(script.count("{") - script.count("}"))
        check(f"{name}: 花括号平衡",
              brace_diff <= 2, category="F7 JS Scripts")

        paren_diff = abs(script.count("(") - script.count(")"))
        check(f"{name}: 圆括号平衡",
              paren_diff <= 2, category="F7 JS Scripts")

    # 特定检查
    check("GET_CONTACTS: hasUnread 字段",
          "hasUnread" in _JS_GET_CONTACTS, category="F7 JS Scripts")

    check("GET_CONTACTS: 左侧面板过滤 (x<450)",
          "r.x < 450" in _JS_GET_CONTACTS, category="F7 JS Scripts")

    check("GET_MESSAGES: isMe 判断",
          "isMe" in _JS_GET_MESSAGES, category="F7 JS Scripts")

    check("FIND_INPUT_AREA: contenteditable",
          'contenteditable="true"' in _JS_FIND_INPUT_AREA, category="F7 JS Scripts")

    check("CHECK_LIMIT_POPUP: 弹窗扫描",
          "keywords" in _JS_CHECK_LIMIT_POPUP
          and "textContent" in _JS_CHECK_LIMIT_POPUP, category="F7 JS Scripts")

    check("DISMISS_POPUP: overlay 移除",
          "el.remove()" in _JS_DISMISS_POPUP, category="F7 JS Scripts")

    check("CLEAR_INPUT: focus + select",
          "el.focus()" in _JS_CLEAR_INPUT
          and "setSelectionRange" in _JS_CLEAR_INPUT, category="F7 JS Scripts")


# ══════════════════════════════════════════════════
# 关键词和模式检查
# ══════════════════════════════════════════════════

def check_keywords_and_patterns():
    # LIMIT_KEYWORDS
    from app.chat_nav import LIMIT_KEYWORDS

    check("LIMIT_KEYWORDS: >= 20个", len(LIMIT_KEYWORDS) >= 20,
          f"当前: {len(LIMIT_KEYWORDS)}", "Keywords & Patterns")

    # 每个关键词都是非空字符串
    non_empty = all(isinstance(kw, str) and len(kw) > 0 for kw in LIMIT_KEYWORDS)
    check("LIMIT_KEYWORDS: 全部非空", non_empty, category="Keywords & Patterns")

    # 关键词无重复
    unique = len(LIMIT_KEYWORDS) == len(set(LIMIT_KEYWORDS))
    check("LIMIT_KEYWORDS: 无重复", unique, category="Keywords & Patterns")

    # RESUME_PATTERNS
    from app.chat_stage import RESUME_PATTERNS, WECHAT_PATTERNS

    check("RESUME_PATTERNS: >= 3个", len(RESUME_PATTERNS) >= 3,
          f"当前: {len(RESUME_PATTERNS)}", "Keywords & Patterns")

    check("WECHAT_PATTERNS: >= 3个", len(WECHAT_PATTERNS) >= 3,
          f"当前: {len(WECHAT_PATTERNS)}", "Keywords & Patterns")

    # STAGE_FALLBACK
    from app.chat_stage import STAGE_FALLBACK
    required_stages = [
        "ready_for_interview", "has_resume_no_wechat",
        "has_wechat_no_resume", "awaiting_response",
    ]
    for stage in required_stages:
        check(f"STAGE_FALLBACK: {stage}", stage in STAGE_FALLBACK
              and len(STAGE_FALLBACK[stage]) >= 10, category="Keywords & Patterns")

    check("STAGE_FALLBACK: early_stage 无兜底",
          "early_stage" not in STAGE_FALLBACK, category="Keywords & Patterns")

    # 默认兜底模板
    from app.chat_workflow import _DEFAULT_FALLBACK_TEMPLATES

    check("DEFAULT_FALLBACK: >= 3个模板",
          len(_DEFAULT_FALLBACK_TEMPLATES) >= 3,
          f"当前: {len(_DEFAULT_FALLBACK_TEMPLATES)}", "Keywords & Patterns")


# ══════════════════════════════════════════════════
# 导入完整性检查
# ══════════════════════════════════════════════════

def check_imports():
    modules = {
        "app.automation": "automation",
        "app.chat_nav": ("navigate_to_chat, get_contacts, get_messages, "
                         "check_limit_popup, dismiss_popup, clear_input, "
                         "type_and_send, click_contact"),
        "app.chat_stage": "compute_stage, reply_redundant, load_candidate_context, STAGE_FALLBACK",
        "app.chat_service": "chat_service",
        "app.chat_workflow": "_batch_reply_impl, _merge_histories, _build_history_from_messages",
        "app.resume_collector": "collect_resumes, _refind_contact, _detect_resume_case",
        "app.database": "Database",
    }

    for module, expected in modules.items():
        try:
            __import__(module)
            check(f"导入: {module}", True, category="Import Integrity")
        except ImportError as e:
            check(f"导入: {module}", False, str(e), "Import Integrity")


# ══════════════════════════════════════════════════
# 报告生成
# ══════════════════════════════════════════════════

def print_report(verbose: bool = False):
    total = 0
    passed = 0

    print("\n" + "=" * 70)
    print("  F6 + F7 视觉验收验证报告")
    print("=" * 70)

    for category, checks in results.items():
        cat_total = len(checks)
        cat_passed = sum(1 for _, ok, _ in checks if ok)
        total += cat_total
        passed += cat_passed

        icon = PASS if cat_passed == cat_total else (WARN if cat_passed > 0 else FAIL)
        print(f"\n{icon} {category} ({cat_passed}/{cat_total})")
        print("-" * 50)

        for name, ok, detail in checks:
            if verbose or not ok:
                status = PASS if ok else FAIL
                detail_str = f" — {detail}" if detail else ""
                print(f"  {status} {name}{detail_str}")

    print("\n" + "=" * 70)
    print(f"  总计: {passed}/{total} 通过 ({100*passed//total if total else 0}%)")
    print("=" * 70)

    if passed == total:
        print(f"\n{PASS} 所有检查通过 — 可以运行视觉测试")
    else:
        failed_count = total - passed
        print(f"\n{FAIL} {failed_count} 项检查未通过 — 请在运行视觉测试前修复")
        print(f"  使用 --verbose 查看详情")

    return passed == total


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print(f"{INFO} 运行 F6+F7 静态视觉验收检查...")

    check_f6_js_scripts()
    check_f7_js_scripts()
    check_keywords_and_patterns()
    check_imports()

    all_ok = print_report(verbose=verbose)
    sys.exit(0 if all_ok else 1)
