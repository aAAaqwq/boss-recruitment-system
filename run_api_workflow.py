#!/usr/bin/env python3
"""基于参考项目API的完整自动化流程"""
import requests
import json

API_BASE = "http://127.0.0.1:8765"

print("=" * 60)
print("BOSS招聘自动化 - 完整流程（基于参考项目API）")
print("=" * 60)

# 配置
config = {
    "activate_chrome": True,
    "open_recommend": True,
    "apply_filter_panel": True,
    "filter_panel": {
        "select_texts": ["985", "211", "本科及以上", "3年以上"]
    },
    "scan": {
        "filter": {
            "min_degree": "本科",
            "min_years": 3,
            "school_whitelist": [
                "清华大学", "北京大学", "浙江大学", "复旦大学",
                "上海交通大学", "华中科技大学", "武汉大学", "中山大学",
                "西安交通大学", "南京大学", "哈尔滨工业大学", "北京航空航天大学"
            ]
        }
    },
    "daily_cap": 80,
    "require_school_or_985_211": True,
    "auto_say_hello": True,
    "dry_run": True  # 先Dry Run
}

print("\n配置:")
print(f"  学校白名单: {len(config['scan']['filter']['school_whitelist'])}所")
print(f"  筛选条件: 985/211/本科及以上/3年以上")
print(f"  每日上限: {config['daily_cap']}人")

# 第一步：Dry Run
print("\n" + "=" * 60)
print("第一步: Dry Run预览")
print("=" * 60)

try:
    response = requests.post(
        f"{API_BASE}/boss/recommend/auto-run",
        json=config,
        timeout=60
    )
    
    result = response.json()
    
    print(f"\n状态: {response.status_code}")
    print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    if result.get("contacted"):
        print(f"\n将联系 {len(result['contacted'])} 位候选人:")
        for i, candidate in enumerate(result['contacted'][:10], 1):
            print(f"  {i}. {candidate.get('name', '未知')} - {candidate.get('school', '未知')}")
        
        # 第二步：人工确认
        print("\n" + "=" * 60)
        print("第二步: 人工确认")
        print("=" * 60)
        
        confirm = input("\n确认执行真实打招呼？(y/n): ")
        
        if confirm.lower() == 'y':
            print("\n" + "=" * 60)
            print("第三步: 执行真实打招呼")
            print("=" * 60)
            
            # 切换到真实执行
            config["dry_run"] = False
            
            response = requests.post(
                f"{API_BASE}/boss/recommend/auto-run",
                json=config,
                timeout=120
            )
            
            result = response.json()
            
            print(f"\n状态: {response.status_code}")
            print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
            
            if result.get("contacted"):
                print(f"\n✅ 成功联系 {len(result['contacted'])} 位候选人")
        else:
            print("\n❌ 用户取消操作")
    
except Exception as e:
    print(f"\n❌ 错误: {e}")

print("\n" + "=" * 60)
print("流程结束")
print("=" * 60)
