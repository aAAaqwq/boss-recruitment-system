#!/usr/bin/env python3
"""测试OCR扫描不同区域，找到学历信息的确切位置"""
import sys, time
sys.path.insert(0, '/Users/peterqiu/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system')
from run_chat_and_resume import ocr

print("=" * 60)
print("测试OCR扫描不同区域，找到学历信息位置")
print("=" * 60)

# 定义多个扫描区域（1920x1080分辨率）
regions = {
    "左侧列表顶部": (90, 180, 400, 600),
    "右侧聊天顶部": (800, 100, 500, 150),
    "右侧聊天顶部偏左": (700, 100, 400, 150),
    "页面中间偏上": (400, 150, 600, 200),
    "全屏顶部": (0, 0, 1920, 200),
}

for name, region in regions.items():
    print(f"\n{'='*60}")
    print(f"扫描区域: {name} {region}")
    print(f"{'='*60}")
    try:
        r = ocr(region, min_conf=5.0, scale=2)
        text = " ".join(b.text for b in r.get("boxes", []))
        print(f"结果: {text[:200]}")
        
        for kw in ["博士", "硕士", "本科", "大专", "专科"]:
            if kw in text:
                print(f"  >>> 找到学历: {kw}")
                break
        else:
            print(f"  未找到学历")
    except Exception as e:
        print(f"错误: {e}")
    
    time.sleep(0.5)

print("\n测试完成")
