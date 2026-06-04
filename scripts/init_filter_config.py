#!/usr/bin/env python3
"""
初始化 / 更新筛选配置到 runtime_state 数据库

用法:
    python scripts/init_filter_config.py          # 写入默认配置（国内+海外名校）
    python scripts/init_filter_config.py --show   # 仅查看当前配置
    python scripts/init_filter_config.py --reset  # 重置为默认配置

变更记录:
    2026-06-04  v2.0  新增海外名校白名单（132所），筛选条件可扩展架构
                      - 国内 33 所 + 美国 41 所 + 英国 17 所 + 其他 41 所
                      - FilterCriteria 预留 age_range / tech_stack / industry 扩展字段
"""
import json
import sqlite3
import sys
import os
from datetime import datetime
from pathlib import Path

# 确保能导入项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.filter_criteria import (
    DOMESTIC_ELITE_SCHOOLS, US_ELITE_SCHOOLS, UK_ELITE_SCHOOLS, OTHER_ELITE_SCHOOLS,
    ALL_ELITE_SCHOOLS,
)

DB_PATH = Path(__file__).parent.parent / "data" / "boss_recruitment.db"

DEFAULT_FILTER_CONFIG = {
    "version": "2.0",
    "updated_at": datetime.now().isoformat(),
    "school_whitelist": {
        "domestic": DOMESTIC_ELITE_SCHOOLS,
        "us": US_ELITE_SCHOOLS,
        "uk": UK_ELITE_SCHOOLS,
        "other": OTHER_ELITE_SCHOOLS,
        "all": ALL_ELITE_SCHOOLS,
        "total_count": len(ALL_ELITE_SCHOOLS),
    },
    "degree_options": ["博士", "硕士", "本科", "大专"],
    "min_degree_default": "本科",
    "years_options": [1, 2, 3, 5, 10],
    "min_years_default": 3,
    "daily_cap_default": 80,
    "daily_cap_range": [10, 20, 50, 80, 100, 150],
    "available_filters": [
        {"key": "school_whitelist", "label": "学校白名单", "type": "multi_select", "enabled": True},
        {"key": "min_degree",       "label": "最低学历",   "type": "select",       "enabled": True},
        {"key": "min_years",        "label": "最低工作年限", "type": "number",       "enabled": True},
        {"key": "age_range",        "label": "年龄范围",   "type": "range",        "enabled": False, "note": "后续扩展"},
        {"key": "tech_stack",       "label": "技术栈",     "type": "multi_select",  "enabled": False, "note": "后续扩展"},
        {"key": "industry",         "label": "行业经验",   "type": "multi_select",  "enabled": False, "note": "后续扩展"},
        {"key": "job_title_keywords", "label": "职位关键词", "type": "multi_select","enabled": False, "note": "后续扩展"},
    ],
    "changelog": [
        {
            "date": "2026-06-04",
            "version": "2.0",
            "changes": [
                "新增海外名校白名单: 美国41所 + 英国17所 + 其他41所",
                "筛选条件重构为可扩展的 FilterCriteria 数据类",
                "预留 age_range / tech_stack / industry / job_title_keywords 扩展字段",
                "学校名提取支持中英文（MIT, Stanford University, 哈佛大学等）",
                "学校匹配支持缩写互推（MIT ↔ Massachusetts Institute of Technology）",
                "将名校常量和 FilterCriteria 抽离到 app/filter_criteria.py 轻量模块",
            ],
        },
        {
            "date": "2026-05-20",
            "version": "1.0",
            "changes": [
                "初始版本: 国内12所名校白名单",
                "基础筛选: school_whitelist + min_degree + min_years",
            ],
        },
    ],
}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def show_current_config():
    """显示当前数据库中的筛选配置"""
    if not DB_PATH.exists():
        print("⚠ 数据库文件不存在:", DB_PATH)
        return

    conn = get_db()
    try:
        # 确保表存在
        conn.execute("""CREATE TABLE IF NOT EXISTS runtime_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

        row = conn.execute(
            "SELECT value, updated_at FROM runtime_state WHERE key = 'filter_config'"
        ).fetchone()

        if row:
            config = json.loads(row["value"])
            print(f"当前筛选配置 (更新于 {row['updated_at']}):")
            print(f"  版本: {config.get('version', 'unknown')}")
            schools = config.get("school_whitelist", {})
            if isinstance(schools, dict):
                print(f"  学校总数: {schools.get('total_count', '?')}")
                for k in ["domestic", "us", "uk", "other"]:
                    lst = schools.get(k, [])
                    if lst:
                        print(f"    {k}: {len(lst)} 所")
            else:
                print(f"  学校白名单 (旧格式): {len(schools)} 所")
            print(f"  可用筛选维度: {[f['key'] for f in config.get('available_filters', []) if f['enabled']]}")
        else:
            print("数据库中没有筛选配置（将使用代码中的默认值）")
    finally:
        conn.close()


def write_default_config():
    """写入默认配置到 runtime_state"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_db()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS runtime_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

        config_json = json.dumps(DEFAULT_FILTER_CONFIG, ensure_ascii=False, indent=2)
        conn.execute(
            "INSERT OR REPLACE INTO runtime_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("filter_config", config_json, datetime.now().isoformat()),
        )
        conn.commit()

        print(f"✓ 筛选配置已写入数据库")
        print(f"  版本: {DEFAULT_FILTER_CONFIG['version']}")
        print(f"  学校总数: {len(ALL_ELITE_SCHOOLS)} 所")
        print(f"    - 国内: {len(DOMESTIC_ELITE_SCHOOLS)}")
        print(f"    - 美国: {len(US_ELITE_SCHOOLS)}")
        print(f"    - 英国: {len(UK_ELITE_SCHOOLS)}")
        print(f"    - 其他: {len(OTHER_ELITE_SCHOOLS)}")
        print(f"  可扩展字段: {[f['key'] for f in DEFAULT_FILTER_CONFIG['available_filters'] if not f['enabled']]}")
    finally:
        conn.close()


if __name__ == "__main__":
    if "--show" in sys.argv:
        show_current_config()
    elif "--reset" in sys.argv:
        write_default_config()
    else:
        # 默认: 写入配置
        show_current_config()
        print()
        write_default_config()
