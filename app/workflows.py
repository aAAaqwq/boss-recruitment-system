"""三大核心工作流"""
import json
import time
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.database import Database
from app.automation import automation
import httpx


# 名校白名单 + 可扩展筛选条件（从轻量模块导入，避免循环依赖）
from app.filter_criteria import (
    DOMESTIC_ELITE_SCHOOLS, US_ELITE_SCHOOLS, UK_ELITE_SCHOOLS, OTHER_ELITE_SCHOOLS,
    ALL_ELITE_SCHOOLS, FilterCriteria,
)


# ========== 3.1 主动筛选沟通流程 ==========

async def workflow_3_1_auto_contact(
    daily_cap: int = 80,
    school_whitelist: List[str] = None,
    min_degree: str = "本科",
    min_years: int = 3,
    dry_run: bool = True,
    criteria: Optional[FilterCriteria] = None,
) -> Dict:
    """3.1 主动筛选沟通流程 (Phase 1 stub — 完整实现在 Phase 2)"""
    return {
        "status": "not_implemented",
        "message": "筛选打招呼功能将在 Phase 2 实现",
        "phase": 1,
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
    """提取学校（支持中英文名校名）

    匹配模式:
        中文: XX大学, XX学院 (含海外学校中文译名如"哈佛大学")
        英文: Harvard University, MIT, UC Berkeley, etc.
    """
    # 1. 先尝试匹配中文学校名
    cn_match = re.search(r'([\u4e00-\u9fa5]{2,8}(?:大学|学院|学校))', text)
    if cn_match:
        return cn_match.group(1)

    # 2. 匹配常见海外名校英文名（含缩写）
    # 大小写不敏感的完整校名模式
    ci_patterns = [
        # Harvard University, Massachusetts Institute of Technology, etc.
        r'((?:[A-Z][a-z]+\s){0,4}(?:University|College|Institute|School)(?:\s(?:of|at|in)\s[A-Z][a-z]+)?)',
        # Well-known short names
        r'(Caltech|ETH\s?Zurich|EPFL|KAIST)',
        r'\b(Oxford|Cambridge)\b',
        # Mixed-case abbreviations
        r'\b(UPenn|UChicago|UMich)\b',
    ]
    for pattern in ci_patterns:
        en_match = re.search(pattern, text, re.IGNORECASE)
        if en_match:
            return en_match.group(1).strip()

    # 大小写敏感的大写缩写模式（避免匹配到普通英文名如 John, Alice）
    cs_patterns = [
        r'\b([A-Z]{2,7})\b',   # MIT, CMU, UCLA, NYU, UIUC, UBC, NUS, NTU, etc.
    ]
    for pattern in cs_patterns:
        en_match = re.search(pattern, text)  # no IGNORECASE
        if en_match:
            return en_match.group(1).strip()

    # 其他常见缩写（大小写不敏感但更精确）
    more_abbr = r'\b(LSE|UCL|HKU|CUHK|HKUST|ANU|UNSW|JHU)\b'
    en_match = re.search(more_abbr, text, re.IGNORECASE)
    if en_match:
        return en_match.group(1).strip()

    return None


# _match_school: 从轻量模块导入，避免重复定义
from app.filter_criteria import match_school as _match_school


def _should_contact(
    candidate: Dict,
    criteria: "FilterCriteria",
) -> bool:
    """判断是否应该联系（基于可扩展筛选条件）

    Args:
        candidate: 候选人信息字典
        criteria: 可扩展筛选条件

    Returns:
        是否应该联系
    """
    # 年限检查
    if criteria.min_years is not None:
        if candidate.get('years') is None or candidate['years'] < criteria.min_years:
            return False

    # 学历检查
    if criteria.min_degree:
        degree_rank = {"博士": 4, "硕士": 3, "本科": 2, "大专": 1}
        if candidate.get('degree') not in degree_rank:
            return False
        if degree_rank[candidate['degree']] < degree_rank.get(criteria.min_degree, 0):
            return False

    # 学校白名单检查
    if criteria.school_whitelist:
        school = candidate.get('school', '')
        if not _match_school(school, criteria.school_whitelist):
            return False

    # ---- 预留扩展筛选维度 ----
    # 年龄范围
    # if criteria.age_range:
    #     age = candidate.get('age')
    #     if age is None or not (criteria.age_range[0] <= age <= criteria.age_range[1]):
    #         return False
    #
    # 技术栈
    # if criteria.tech_stack:
    #     skills = candidate.get('skills', '')
    #     if not any(tech.lower() in skills.lower() for tech in criteria.tech_stack):
    #         return False

    return True


# ========== 3.3 智能聊天Bot流程 ==========

async def workflow_3_3_chat_bot(
    boss_id: str,
    candidate_name: str,
    chat_region: Tuple[int, int, int, int] = (420, 140, 560, 350),
    auto_send: bool = False,
    dry_run: bool = True
) -> Dict:
    """3.3 AI自动对话流程 (Phase 1 stub — 完整实现在 Phase 2)"""
    return {
        "status": "not_implemented",
        "message": "AI对话功能将在 Phase 2 实现",
        "phase": 1,
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
