"""
工具函数
"""
import re
import random
import time
from datetime import datetime
from typing import Optional
from .config import WHITELIST_SCHOOLS, BLACKLIST_KEYWORDS, DELAY_MIN, DELAY_MAX


def log(message: str, level: str = "INFO"):
    """带时间戳的日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    emoji_map = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
    }
    emoji = emoji_map.get(level, "ℹ️")
    print(f"[{timestamp}] {emoji} {message}")


def random_delay(min_sec: float = DELAY_MIN, max_sec: float = DELAY_MAX):
    """随机延迟（防检测）"""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def clean_text(text: str) -> str:
    """清理文本（去空格、特殊符号）"""
    if not text:
        return ""
    # 去除所有空格和特殊符号
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)
    return text.strip()


def check_school_whitelist(school_text: str) -> Optional[str]:
    """
    检查学校是否在白名单中
    
    返回：
        - 匹配的学校名称（如果在白名单中）
        - None（如果不在白名单或在黑名单中）
    """
    if not school_text:
        return None
    
    # 清理文本
    cleaned = clean_text(school_text)
    
    # 检查黑名单
    for keyword in BLACKLIST_KEYWORDS:
        if keyword in school_text or keyword in cleaned:
            log(f"黑名单关键词匹配: {keyword} in {school_text}", "DEBUG")
            return None
    
    # 检查白名单
    for school in WHITELIST_SCHOOLS:
        school_cleaned = clean_text(school)
        
        # 完全匹配
        if school_cleaned == cleaned:
            return school
        
        # 包含匹配（处理"XX大学"的情况）
        if school_cleaned in cleaned or cleaned in school_cleaned:
            # 短名称严格匹配（防止"南大"误匹配"中南大学"）
            if len(school_cleaned) <= 3:
                if school_cleaned == cleaned:
                    return school
            else:
                return school
    
    return None


def extract_candidate_info(text: str) -> dict:
    """
    从候选人卡片文本中提取信息
    
    返回格式：
    {
        "name": "张三",
        "position": "Python开发工程师",
        "company": "字节跳动",
        "experience": "3-5年",
        "education": "本科",
        "school": "清华大学",
        "salary": "20-30K",
    }
    """
    info = {
        "name": "",
        "position": "",
        "company": "",
        "experience": "",
        "education": "",
        "school": "",
        "salary": "",
    }
    
    # 提取学历
    education_pattern = r'(博士|硕士|本科|大专)'
    education_match = re.search(education_pattern, text)
    if education_match:
        info["education"] = education_match.group(1)
    
    # 提取工作年限
    experience_pattern = r'(\d+-\d+年|\d+年以上|应届生)'
    experience_match = re.search(experience_pattern, text)
    if experience_match:
        info["experience"] = experience_match.group(1)
    
    # 提取薪资
    salary_pattern = r'(\d+-\d+K|\d+K以上)'
    salary_match = re.search(salary_pattern, text)
    if salary_match:
        info["salary"] = salary_match.group(1)
    
    return info


def calculate_score(candidate_info: dict) -> int:
    """
    计算候选人评分（0-100分）
    
    评分维度：
    - 学校（25分）
    - 学历（15分）
    - 工作年限（25分）
    - 大厂经验（20分）
    - 技能匹配度（15分）
    """
    from .config import SCORING_RULES
    
    score = 0
    
    # 学校评分
    school = candidate_info.get("school", "")
    if school:
        if school in ["清华大学", "北京大学", "浙江大学", "复旦大学", "上海交通大学",
                      "南京大学", "中国科学技术大学", "哈尔滨工业大学", "西安交通大学"]:
            score += SCORING_RULES["学校"]["C9"]
        elif "985" in school or any(s in school for s in WHITELIST_SCHOOLS):
            score += SCORING_RULES["学校"]["985"]
        else:
            score += SCORING_RULES["学校"]["其他"]
    
    # 学历评分
    education = candidate_info.get("education", "")
    if education in SCORING_RULES["学历"]:
        score += SCORING_RULES["学历"][education]
    
    # 工作年限评分
    experience = candidate_info.get("experience", "")
    if "3-5年" in experience:
        score += SCORING_RULES["工作年限"]["3-5年"]
    elif "5-8年" in experience:
        score += SCORING_RULES["工作年限"]["5-8年"]
    elif "8年以上" in experience or "10年以上" in experience:
        score += SCORING_RULES["工作年限"]["8年以上"]
    else:
        score += SCORING_RULES["工作年限"]["3年以下"]
    
    # 大厂经验评分（简化版，实际需要解析公司名称）
    company = candidate_info.get("company", "")
    big_companies = ["字节", "阿里", "腾讯", "百度", "京东", "美团", "滴滴", "快手"]
    if any(c in company for c in big_companies):
        score += SCORING_RULES["大厂经验"]["BATJ"]
    
    # 技能匹配度（默认部分匹配）
    score += SCORING_RULES["技能匹配度"]["部分匹配"]
    
    return min(score, 100)


def get_score_level(score: int) -> tuple:
    """
    根据分数返回等级和emoji
    
    返回：(等级, emoji)
    """
    if score >= 85:
        return ("S级", "🔥")
    elif score >= 75:
        return ("A级", "⭐️⭐️⭐️⭐️")
    elif score >= 60:
        return ("B级", "⭐️⭐️⭐️")
    elif score >= 40:
        return ("C级", "⭐️⭐️")
    else:
        return ("D级", "⭐️")
