"""三大核心工作流"""
import json
import time
import random
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.database import Database
from app.vision import screen_ocr, click_text_ocr
from app.screen import activate_chrome, move_and_click, type_text, press_hotkey
import httpx


# ========== 3.1 主动筛选沟通流程 ==========

def workflow_3_1_auto_contact(
    daily_cap: int = 80,
    school_whitelist: List[str] = None,
    min_degree: str = "本科",
    min_years: int = 3,
    dry_run: bool = True
) -> Dict:
    """
    3.1 主动筛选沟通流程
    
    Args:
        daily_cap: 每日上限
        school_whitelist: 学校白名单
        min_degree: 最低学历
        min_years: 最低年限
        dry_run: 是否dry run模式
    
    Returns:
        执行结果
    """
    if school_whitelist is None:
        school_whitelist = [
            "清华大学", "北京大学", "浙江大学", "复旦大学",
            "上海交通大学", "华中科技大学", "武汉大学", "中山大学"
        ]
    
    with Database() as db:
        # 1. 检查每日上限
        contacted_today = db.count_contacted_today()
        remaining = max(0, daily_cap - contacted_today)
        
        if remaining <= 0:
            return {
                "status": "blocked",
                "reason": "daily_cap_reached",
                "contacted_today": contacted_today
            }
        
        # 2. 激活Chrome
        if not activate_chrome():
            return {"status": "failed", "reason": "chrome_activation_failed"}
        
        # 3. 点击"推荐牛人"（尝试多个关键词）
        recommend_coord = None
        for keyword in ["推荐牛人", "推荐", "牛人"]:
            recommend_coord = click_text_ocr(keyword, (0, 80, 230, 460))
            if recommend_coord:
                break
        
        if not recommend_coord:
            return {"status": "failed", "reason": "recommend_button_not_found"}
        
        move_and_click(*recommend_coord)
        time.sleep(0.8)
        
        # 4. OCR扫描候选人卡片
        scan_result = screen_ocr(
            region=(235, 130, 650, 410),
            min_confidence=20.0,
            scale=3,
            preprocess=True
        )
        
        # 5. 解析候选人信息
        candidates = _parse_candidates(scan_result["boxes"])
        
        # 6. 筛选候选人
        passed = []
        for candidate in candidates:
            if _should_contact(candidate, school_whitelist, min_degree, min_years):
                passed.append(candidate)
        
        # 限制数量
        passed = passed[:remaining]
        
        # 7. Dry Run预览
        if dry_run:
            return {
                "status": "preview",
                "dry_run": True,
                "candidates": passed,
                "total": len(passed),
                "remaining": remaining
            }
        
        # 8. 人工确认
        print(f"\n准备联系 {len(passed)} 位候选人:")
        for i, c in enumerate(passed[:5]):
            print(f"  {i+1}. {c.get('name', '未知')} - {c.get('school', '未知')} - {c.get('degree', '未知')} - {c.get('years', 0)}年")
        if len(passed) > 5:
            print(f"  ... 还有 {len(passed)-5} 位")
        
        confirm = input("\n确认联系？(y/n): ")
        if confirm.lower() != 'y':
            return {"status": "cancelled", "reason": "human_rejected"}
        
        # 9. 逐个点击"打招呼"
        contacted = []
        for candidate in passed:
            if candidate.get("button_x") and candidate.get("button_y"):
                try:
                    move_and_click(candidate["button_x"], candidate["button_y"])
                    
                    # 记录到数据库
                    boss_id = f"{candidate.get('name', 'unknown')}_{int(time.time())}"
                    db.insert_candidate(
                        boss_id=boss_id,
                        candidate_name=candidate.get('name'),
                        school=candidate.get('school'),
                        degree=candidate.get('degree'),
                        years=candidate.get('years'),
                        status='contacted'
                    )
                    db.insert_contact_record(boss_id, 'contacted', success=True)
                    
                    contacted.append(candidate)
                    time.sleep(random.uniform(0.4, 0.6))
                    
                except Exception as e:
                    print(f"联系失败: {candidate.get('name')} - {e}")
        
        return {
            "status": "completed",
            "contacted": contacted,
            "total": len(contacted),
            "remaining": remaining - len(contacted)
        }


def _parse_candidates(boxes: List) -> List[Dict]:
    """解析候选人信息"""
    # 按Y坐标分组（同一行）
    rows = {}
    for box in boxes:
        row_key = box.center_y // 50  # 每50像素一行
        if row_key not in rows:
            rows[row_key] = []
        rows[row_key].append(box)
    
    candidates = []
    for row_boxes in rows.values():
        # 按X坐标排序
        row_boxes.sort(key=lambda b: b.center_x)
        
        # 提取信息
        raw_text = " ".join(b.text for b in row_boxes)
        
        candidate = {
            "name": row_boxes[0].text if row_boxes else None,
            "years": _extract_years(raw_text),
            "degree": _extract_degree(raw_text),
            "school": _extract_school(raw_text),
            "raw_text": raw_text
        }
        
        # 查找"打招呼"按钮
        for box in row_boxes:
            if "打招呼" in box.text or "立即沟通" in box.text:
                candidate["button_x"] = box.center_x
                candidate["button_y"] = box.center_y
                break
        
        if candidate.get("button_x"):
            candidates.append(candidate)
    
    return candidates


def _extract_years(text: str) -> Optional[int]:
    """提取年限"""
    match = re.search(r'(\d+)\s*年', text)
    return int(match.group(1)) if match else None


def _extract_degree(text: str) -> Optional[str]:
    """提取学历"""
    degrees = ["博士", "硕士", "本科", "大专"]
    for degree in degrees:
        if degree in text:
            return degree
    return None


def _extract_school(text: str) -> Optional[str]:
    """提取学校"""
    match = re.search(r'([\u4e00-\u9fa5]{2,8}(?:大学|学院|学校))', text)
    return match.group(1) if match else None


def _should_contact(
    candidate: Dict,
    school_whitelist: List[str],
    min_degree: str,
    min_years: int
) -> bool:
    """判断是否应该联系"""
    # 年限检查
    if candidate.get('years') is None or candidate['years'] < min_years:
        return False
    
    # 学历检查
    degree_rank = {"博士": 4, "硕士": 3, "本科": 2, "大专": 1}
    if candidate.get('degree') not in degree_rank:
        return False
    if degree_rank[candidate['degree']] < degree_rank.get(min_degree, 0):
        return False
    
    # 学校白名单检查
    school = candidate.get('school', '')
    if not any(s in school for s in school_whitelist):
        return False
    
    return True


# ========== 3.3 智能聊天Bot流程 ==========

def workflow_3_3_chat_bot(
    boss_id: str,
    candidate_name: str,
    chat_region: Tuple[int, int, int, int] = (420, 140, 560, 350),
    auto_send: bool = False,
    dry_run: bool = True
) -> Dict:
    """
    3.3 智能聊天Bot流程
    
    Args:
        boss_id: 候选人ID
        candidate_name: 候选人姓名
        chat_region: 聊天区域坐标
        auto_send: 是否自动发送
        dry_run: 是否dry run模式
    
    Returns:
        执行结果
    """
    # 1. 加载对话流配置
    with open(settings.CHAT_BOT_FLOW_PATH) as f:
        flow = json.load(f)
    
    with Database() as db:
        # 2. 获取会话状态
        session = db.get_chat_session(boss_id)
        if not session:
            session = {
                "boss_id": boss_id,
                "candidate_name": candidate_name,
                "round_index": 0,
                "history": [],
                "rounds_sent_today": 0,
                "last_screen_text": ""
            }
        
        # 3. 检查今日发送上限
        max_rounds_per_day = flow["guardrails"]["max_rounds_per_day"]
        if session["rounds_sent_today"] >= max_rounds_per_day:
            return {
                "status": "blocked",
                "reason": "daily_round_cap_reached",
                "rounds_sent_today": session["rounds_sent_today"]
            }
        
        # 4. 获取当前轮次
        rounds = flow["rounds"]
        if session["round_index"] >= len(rounds):
            return {"status": "completed", "reason": "all_rounds_finished"}
        
        current_round = rounds[session["round_index"]]
        
        # 5. OCR识别聊天区域
        ocr_result = screen_ocr(chat_region, min_confidence=20.0, scale=3)
        screen_text = ocr_result["full_text"]
        
        # 6. 检测是否有新消息
        if screen_text.strip() == session["last_screen_text"].strip():
            return {"status": "skipped", "reason": "no_new_message"}
        
        # 7. 记录候选人消息
        session["history"].append({
            "role": "user",
            "content": screen_text,
            "round_id": current_round["id"],
            "timestamp": datetime.now().isoformat()
        })
        
        # 8. 生成回复
        draft_reply = _generate_reply(flow, current_round, session["history"])
        if not draft_reply:
            return {"status": "failed", "reason": "llm_generation_failed"}
        
        # 9. 安全检查
        safe_reply, reject_reason = _safety_check(draft_reply, flow)
        if not safe_reply:
            return {
                "status": "blocked",
                "reason": reject_reason,
                "draft_reply": draft_reply
            }
        
        # 10. 记录AI回复
        session["history"].append({
            "role": "assistant",
            "content": safe_reply,
            "round_id": current_round["id"],
            "timestamp": datetime.now().isoformat()
        })
        
        # 11. Dry Run预览
        if dry_run:
            return {
                "status": "preview",
                "dry_run": True,
                "boss_id": boss_id,
                "candidate_name": candidate_name,
                "round_id": current_round["id"],
                "round_index": session["round_index"],
                "screen_text": screen_text,
                "draft_reply": safe_reply
            }
        
        # 12. 发送消息
        sent = False
        if auto_send:
            # 点击输入框
            move_and_click(650, 505)
            time.sleep(0.2)
            
            # 输入文字
            type_text(safe_reply)
            time.sleep(0.2)
            
            # 发送
            press_hotkey('command', 'enter')
            sent = True
            
            # 进入下一轮
            session["round_index"] += 1
            session["rounds_sent_today"] += 1
            
            # 记录到数据库
            db.insert_contact_record(boss_id, 'chat_sent', success=True)
        
        # 13. 更新会话状态
        session["last_screen_text"] = screen_text
        session["current_round_id"] = current_round["id"]
        db.save_chat_session(session)
        
        return {
            "status": "success",
            "boss_id": boss_id,
            "candidate_name": candidate_name,
            "round_id": current_round["id"],
            "round_index": session["round_index"],
            "draft_reply": safe_reply,
            "sent": sent,
            "dry_run": dry_run,
            "rounds_sent_today": session["rounds_sent_today"]
        }


def _generate_reply(flow: Dict, target_round: Dict, history: List[Dict]) -> Optional[str]:
    """使用LLM生成回复"""
    if not settings.DEEPSEEK_API_KEY:
        # Fallback到固定回复
        return target_round.get("ask")
    
    system_prompt = flow.get("system_prompt", "你是一名招聘官，回复简洁、自然、像真人。")
    instruction = (
        f"当前对话目标: {target_round.get('id')} - {target_round.get('ask','')}\n"
        f"请基于候选人最新消息生成一句简洁自然的回复，不要超过 80 字。\n"
        f"严禁向候选人索要微信、电话、转账或任何敏感联系方式。"
    )
    
    messages = [
        {"role": "system", "content": system_prompt + "\n" + instruction}
    ]
    
    for turn in history[-10:]:
        messages.append({
            "role": turn["role"],
            "content": turn["content"]
        })
    
    try:
        response = httpx.post(
            f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 200
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    
    return None


def _safety_check(text: str, flow: Dict) -> Tuple[Optional[str], str]:
    """安全检查"""
    guardrails = flow.get("guardrails", {})
    
    # 1. 不承诺offer
    if guardrails.get("do_not_promise_offer", True):
        promise_keywords = ["offer", "录用", "保证", "一定能"]
        for keyword in promise_keywords:
            if keyword in text.lower() if keyword.isascii() else keyword in text:
                return None, f"promise:{keyword}"
    
    # 2. 禁词检查
    banned_phrases = guardrails.get("banned_phrases", [])
    for phrase in banned_phrases:
        if phrase in text:
            return None, f"banned_phrase:{phrase}"
    
    # 3. 清理
    cleaned = text.strip().strip("\"' \n")
    if not cleaned:
        return None, "empty_draft"
    
    return cleaned, ""
