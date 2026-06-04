#!/usr/bin/env python3
"""
BOSS直聘智能自动化 v4.0 - 最终版
使用智能位置推算 + 候选人筛选
"""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr
import pyautogui


def log_step(step_num: int, description: str):
    print(f"\n{'='*60}")
    print(f"步骤{step_num}: {description}")
    print('='*60)


def find_and_click_ocr(text: str, region: tuple, min_confidence: float = 15.0) -> tuple:
    """查找文字并返回坐标"""
    result = screen_ocr(
        region=region,
        min_confidence=min_confidence,
        scale=3,
        preprocess=True
    )
    
    for box in result["boxes"]:
        if text in box.text:
            return (box.center_x, box.center_y, box.confidence)
    
    return None


def main():
    print("\n" + "="*60)
    print("BOSS直聘智能自动化 v4.0 - 最终版")
    print("="*60)
    
    # 激活Chrome
    print("\n🚀 激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)
    
    screen_width, screen_height = pyautogui.size()
    print(f"📐 屏幕尺寸: {screen_width}x{screen_height}")
    
    # 步骤1: 点击"推荐牛人"
    log_step(1, "点击左侧'推荐牛人'")
    result = find_and_click_ocr("推荐", region=(0, 80, 140, 460))
    if result:
        x, y, conf = result
        print(f"✅ 找到: 推荐 (置信度: {conf:.1f}, 位置: {x}, {y})")
        move_and_click(x, y)
    else:
        print("❌ 无法找到'推荐牛人'按钮")
        return
    time.sleep(1.5)
    
    # 步骤2: 点击"筛选"
    log_step(2, "点击右上角'筛选'按钮")
    result = find_and_click_ocr("筛选", region=(screen_width-500, 100, 500, 200))
    if result:
        x, y, conf = result
        print(f"✅ 找到: 筛选 (置信度: {conf:.1f}, 位置: {x}, {y})")
        move_and_click(x, y)
    else:
        print("❌ 无法找到'筛选'按钮")
        return
    
    print("⏳ 等待筛选面板打开...")
    time.sleep(2.5)
    
    # 步骤3: 智能点击筛选选项
    log_step(3, "勾选筛选条件（智能位置推算）")
    
    # 扫描筛选面板
    filter_region = (screen_width//2, 100, screen_width//2, 800)
    result = screen_ocr(
        region=filter_region,
        min_confidence=10.0,
        scale=3,
        preprocess=True
    )
    
    # 查找"院校"和"双一流院校"
    yuanxiao_pos = None
    shuangyiliu_pos = None
    benke_pos = None
    
    for box in result["boxes"]:
        if "院校" in box.text and "双" not in box.text and "一流" not in box.text:
            yuanxiao_pos = (box.center_x, box.center_y)
            print(f"✅ 找到'院校': ({box.center_x}, {box.center_y})")
        elif "双一流" in box.text or ("双" in box.text and "一流" in box.text):
            shuangyiliu_pos = (box.center_x, box.center_y)
            print(f"✅ 找到'双一流院校': ({box.center_x}, {box.center_y})")
        elif "本科" in box.text:
            benke_pos = (box.center_x, box.center_y)
            print(f"✅ 找到'本科': ({box.center_x}, {box.center_y})")
    
    # 点击"院校"和"双一流院校"之间的位置（985/211的位置）
    if yuanxiao_pos and shuangyiliu_pos:
        # 计算中间位置
        mid_x = (yuanxiao_pos[0] + shuangyiliu_pos[0]) // 2
        mid_y = yuanxiao_pos[1]  # Y坐标相同
        
        print(f"\n📋 点击985/211区域（推算位置: {mid_x}, {mid_y}）")
        move_and_click(mid_x, mid_y)
        time.sleep(0.5)
    else:
        print("⚠️ 未找到'院校'和'双一流院校'，跳过985/211")
    
    # 点击"本科"
    if benke_pos:
        print(f"\n📋 点击本科 ({benke_pos[0]}, {benke_pos[1]})")
        move_and_click(benke_pos[0], benke_pos[1])
        time.sleep(0.5)
    else:
        print("⚠️ 未找到'本科'，跳过")
    
    # 步骤4: 点击绿色"确认"按钮
    log_step(4, "点击绿色'确认'按钮")
    
    # 查找"确认"或"应用"按钮
    confirm_result = find_and_click_ocr("确认", region=filter_region)
    if not confirm_result:
        confirm_result = find_and_click_ocr("应用", region=filter_region)
    if not confirm_result:
        confirm_result = find_and_click_ocr("确定", region=filter_region)
    
    if confirm_result:
        x, y, conf = confirm_result
        print(f"✅ 找到确认按钮 (置信度: {conf:.1f}, 位置: {x}, {y})")
        move_and_click(x, y)
    else:
        print("💡 请手动点击绿色'确认'按钮，然后按回车继续...")
        input("按回车继续...")
    
    time.sleep(2.0)
    
    # 步骤5-6: 智能扫描和联系候选人
    log_step(5, "智能扫描候选人并自动联系")
    
    contacted = 0
    max_contacts = 80  # 每日上限
    max_scrolls = 20   # 最多滚动20次
    
    for scroll_count in range(max_scrolls):
        print(f"\n🔍 第{scroll_count+1}次扫描...")
        
        # 扫描当前屏幕的候选人
        candidates_region = (200, 200, screen_width-200, screen_height-200)
        result = screen_ocr(
            region=candidates_region,
            min_confidence=15.0,
            scale=3,
            preprocess=True
        )
        
        # 查找"打招呼"按钮
        hello_buttons = []
        for box in result["boxes"]:
            if "打招呼" in box.text or "立即沟通" in box.text:
                hello_buttons.append({
                    'text': box.text,
                    'x': box.center_x,
                    'y': box.center_y
                })
        
        hello_buttons.sort(key=lambda b: b['y'])
        print(f"   找到 {len(hello_buttons)} 个候选人")
        
        # 点击"打招呼"
        for button in hello_buttons:
            if contacted >= max_contacts:
                print(f"\n✅ 已达到每日上限({max_contacts}人)")
                break
            
            print(f"\n👤 候选人 {contacted+1}")
            print(f"   位置: ({button['x']}, {button['y']})")
            
            move_and_click(button['x'], button['y'])
            contacted += 1
            print(f"✅ 已联系")
            time.sleep(0.8)
        
        if contacted >= max_contacts:
            break
        
        # 滚动到下一屏
        print("\n⬇️ 滚动到下一屏...")
        pyautogui.scroll(-3)  # 向下滚动
        time.sleep(1.5)
    
    print("\n" + "="*60)
    print(f"✅ 自动化流程完成")
    print(f"   已联系: {contacted} 人")
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
