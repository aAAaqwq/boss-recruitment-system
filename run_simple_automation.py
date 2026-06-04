#!/usr/bin/env python3
"""
BOSS直聘智能自动化 v6.0 - 极简版
跳过筛选，直接扫描全量候选人，代码层严格过滤
"""
import time
import sys
import os
import re
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr
import pyautogui


# 全球顶尖高校白名单（只保留最核心的学校，避免误匹配）
SCHOOL_WHITELIST = [
    # 🇨🇳 中国C9
    "清华大学", "北京大学", "浙江大学", "复旦大学", 
    "上海交通大学", "南京大学", "中国科学技术大学", 
    "哈尔滨工业大学", "西安交通大学",
    
    # 🇨🇳 强势工科
    "北京航空航天大学", "同济大学", "华中科技大学", "中山大学", 
    "华南理工大学", "武汉大学",
    
    # 🇭🇰 香港顶尖
    "香港大学", "香港科技大学", "香港中文大学", "台湾大学",
    
    # 🇬🇧 英国G5
    "牛津", "Oxford", "剑桥", "Cambridge", "帝国理工", "Imperial", 
    "UCL", "伦敦大学学院", "爱丁堡",
    
    # 🇺🇸 美国Top20
    "哈佛", "Harvard", "斯坦福", "Stanford", "MIT", "麻省理工", 
    "加州理工", "Caltech", "普林斯顿", "Princeton", "耶鲁", "Yale", 
    "康奈尔", "Cornell", "宾夕法尼亚", "UPenn", "哥伦比亚", "Columbia", 
    "芝加哥", "Chicago", "CMU", "卡内基梅隆", "伯克利", "Berkeley",
    
    # 🇸🇬 新加坡
    "新加坡国立", "NUS", "南洋理工", "NTU",
]


def check_school_strict(text: str) -> tuple:
    """
    严格检查学校白名单
    返回: (是否匹配, 匹配的学校列表)
    """
    # 去除所有空格和特殊字符
    text_clean = text.replace(" ", "").replace("　", "").replace("\n", "")
    
    matched_schools = []
    for school in SCHOOL_WHITELIST:
        school_clean = school.replace(" ", "")
        if school_clean in text_clean:
            matched_schools.append(school)
    
    return (len(matched_schools) > 0, matched_schools)


def main():
    print("\n" + "="*60)
    print("BOSS直聘智能自动化 v6.0 - 极简版")
    print("跳过筛选，直接扫描全量候选人")
    print("="*60)
    
    print(f"\n📋 学校白名单({len(SCHOOL_WHITELIST)}所)")
    
    # 激活Chrome
    print("\n🚀 激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)
    
    screen_width, screen_height = pyautogui.size()
    print(f"📐 屏幕尺寸: {screen_width}x{screen_height}")
    
    # 步骤1: 点击"推荐牛人"
    print("\n" + "="*60)
    print("步骤1: 点击左侧'推荐牛人'")
    print("="*60)
    
    result = screen_ocr(
        region=(0, 80, 140, 460),
        min_confidence=15.0,
        scale=3,
        preprocess=True
    )
    
    for box in result["boxes"]:
        if "推荐" in box.text:
            print(f"✅ 找到: 推荐 (位置: {box.center_x}, {box.center_y})")
            move_and_click(box.center_x, box.center_y)
            break
    else:
        print("❌ 无法找到'推荐牛人'按钮")
        return
    
    print("⏳ 等待页面加载...")
    time.sleep(3)
    
    # 步骤2: 智能扫描候选人（跳过筛选，直接扫描）
    print("\n" + "="*60)
    print("步骤2: 智能扫描候选人（学校白名单验证）")
    print("="*60)
    
    contacted = 0
    skipped = 0
    max_contacts = 80
    max_scrolls = 30
    
    for scroll_count in range(max_scrolls):
        print(f"\n🔍 第{scroll_count+1}次扫描...")
        
        # 扫描当前屏幕
        candidates_region = (200, 200, screen_width-200, screen_height-200)
        result = screen_ocr(
            region=candidates_region,
            min_confidence=10.0,
            scale=3,
            preprocess=True
        )
        
        # 查找"打招呼"按钮
        hello_buttons = []
        for box in result["boxes"]:
            if ("打招呼" in box.text or "立即沟通" in box.text) and "继续" not in box.text:
                hello_buttons.append({
                    'text': box.text,
                    'x': box.center_x,
                    'y': box.center_y
                })
        
        hello_buttons.sort(key=lambda b: b['y'])
        print(f"   找到 {len(hello_buttons)} 个候选人")
        
        # 验证并点击
        for button in hello_buttons:
            if contacted >= max_contacts:
                print(f"\n✅ 已达到每日上限({max_contacts}人)")
                break
            
            # 提取候选人信息（按钮上方200像素）
            row_boxes = [
                box for box in result["boxes"]
                if button['y'] - 200 < box.center_y < button['y'] + 50
            ]
            row_boxes.sort(key=lambda b: (b.center_y, b.center_x))
            raw_text = " ".join(box.text for box in row_boxes)
            
            # 学校白名单验证
            is_match, matched_schools = check_school_strict(raw_text)
            
            print(f"\n👤 候选人 {contacted + skipped + 1}")
            print(f"   信息: {raw_text[:100]}...")
            print(f"   学校匹配: {'✅' if is_match else '❌'}")
            if is_match:
                print(f"   匹配学校: {', '.join(matched_schools)}")
            
            if not is_match:
                print(f"   ⏭️ 跳过（不在白名单）")
                skipped += 1
                continue
            
            # 点击"打招呼"
            print(f"   ✅ 准备联系...")
            move_and_click(button['x'], button['y'])
            contacted += 1
            print(f"   ✅ 已联系 #{contacted}")
            
            # 随机延迟3-8秒
            delay = random.uniform(3.0, 8.0)
            print(f"   ⏳ 等待 {delay:.1f} 秒...")
            time.sleep(delay)
        
        if contacted >= max_contacts:
            break
        
        # 滚动到下一屏
        print("\n⬇️ 滚动到下一屏...")
        pyautogui.scroll(-3)
        time.sleep(1.5)
    
    print("\n" + "="*60)
    print(f"✅ 自动化流程完成")
    print(f"   已联系: {contacted} 人")
    print(f"   已跳过: {skipped} 人")
    print(f"   滚动次数: {scroll_count+1}")
    print("="*60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
