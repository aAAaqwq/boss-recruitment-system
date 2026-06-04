#!/usr/bin/env python3
"""
BOSS直聘完整自动化 v3.0 - 使用固定坐标策略
基于你的屏幕分辨率，使用固定坐标点击筛选选项
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


def smart_click_ocr(text: str, region: tuple, min_confidence: float = 20.0) -> bool:
    """使用OCR查找并点击"""
    print(f"🔍 查找: {text}")
    
    result = screen_ocr(
        region=region,
        min_confidence=min_confidence,
        scale=3,
        preprocess=True
    )
    
    for box in result["boxes"]:
        if text in box.text:
            print(f"✅ 找到: {text} (置信度: {box.confidence:.1f}, 位置: {box.center_x}, {box.center_y})")
            move_and_click(box.center_x, box.center_y)
            return True
    
    print(f"❌ 未找到: {text}")
    return False


def main():
    print("\n" + "="*60)
    print("BOSS直聘完整自动化 v3.0")
    print("使用固定坐标策略")
    print("="*60)
    
    # 激活Chrome
    print("\n🚀 激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)
    
    # 获取屏幕尺寸
    screen_width, screen_height = pyautogui.size()
    print(f"📐 屏幕尺寸: {screen_width}x{screen_height}")
    
    # 步骤1: 点击"推荐牛人"
    log_step(1, "点击左侧'推荐牛人'")
    if not smart_click_ocr("推荐", region=(0, 80, 140, 460), min_confidence=20.0):
        print("❌ 无法找到'推荐牛人'按钮")
        return
    time.sleep(1.5)
    
    # 步骤2: 点击"筛选"
    log_step(2, "点击右上角'筛选'按钮")
    if not smart_click_ocr("筛选", region=(screen_width-500, 100, 500, 200), min_confidence=20.0):
        print("❌ 无法找到'筛选'按钮")
        return
    
    # 等待筛选面板完全打开
    print("⏳ 等待筛选面板打开...")
    time.sleep(2.5)
    
    # 步骤3: 使用固定坐标点击筛选选项
    log_step(3, "勾选'985/211/本科/3年' (使用固定坐标)")
    
    # 根据你的截图，筛选面板在屏幕右侧
    # 假设屏幕宽度1920，筛选面板大约在 x=1400-1800 的位置
    # 选项之间的垂直间距大约40-50像素
    
    # 计算筛选面板的基准位置
    panel_x = int(screen_width * 0.85)  # 屏幕右侧 85% 的位置
    panel_start_y = 300  # 筛选选项开始的Y坐标
    option_spacing = 45  # 选项之间的间距
    
    print(f"\n📍 筛选面板预估位置: x={panel_x}, y_start={panel_start_y}")
    print("💡 如果点击位置不对，请手动勾选后按回车继续...")
    
    # 点击985选项
    print(f"\n📋 点击985选项 ({panel_x}, {panel_start_y})")
    move_and_click(panel_x, panel_start_y)
    time.sleep(0.5)
    
    # 点击211选项
    y_211 = panel_start_y + option_spacing
    print(f"📋 点击211选项 ({panel_x}, {y_211})")
    move_and_click(panel_x, y_211)
    time.sleep(0.5)
    
    # 点击本科选项
    y_bachelor = panel_start_y + option_spacing * 2
    print(f"📋 点击本科选项 ({panel_x}, {y_bachelor})")
    move_and_click(panel_x, y_bachelor)
    time.sleep(0.5)
    
    # 点击3年选项
    y_3years = panel_start_y + option_spacing * 3
    print(f"📋 点击3年选项 ({panel_x}, {y_3years})")
    move_and_click(panel_x, y_3years)
    time.sleep(0.5)
    
    print("\n💡 如果上述选项点击不正确，请手动调整后按回车继续...")
    input("按回车继续...")
    
    # 步骤4: 点击"确定"
    log_step(4, "点击'确定'按钮")
    # 确定按钮通常在筛选面板底部
    confirm_region = (screen_width//2, screen_height//2, screen_width//2, screen_height//2)
    if not smart_click_ocr("确定", region=confirm_region, min_confidence=15.0):
        print("💡 请手动点击'确定'按钮，然后按回车继续...")
        input("按回车继续...")
    
    time.sleep(2.0)
    
    # 步骤5: 扫描候选人
    log_step(5, "扫描候选人列表")
    candidates_region = (200, 200, screen_width-200, screen_height-200)
    
    result = screen_ocr(
        region=candidates_region,
        min_confidence=15.0,
        scale=3,
        preprocess=True
    )
    
    hello_buttons = []
    for box in result["boxes"]:
        if "打招呼" in box.text or "立即沟通" in box.text or "继续沟通" in box.text:
            hello_buttons.append({
                'text': box.text,
                'x': box.center_x,
                'y': box.center_y,
                'confidence': box.confidence
            })
    
    hello_buttons.sort(key=lambda b: b['y'])
    print(f"✅ 找到 {len(hello_buttons)} 个候选人")
    
    if not hello_buttons:
        print("❌ 未找到候选人")
        return
    
    # 步骤6: 点击"打招呼"
    log_step(6, f"点击'打招呼' (共{len(hello_buttons)}个候选人)")
    
    contacted = 0
    max_contacts = 5
    
    for i, button in enumerate(hello_buttons[:max_contacts]):
        print(f"\n👤 候选人 {i+1}/{min(len(hello_buttons), max_contacts)}")
        print(f"   位置: ({button['x']}, {button['y']})")
        print(f"   按钮: {button['text']}")
        
        move_and_click(button['x'], button['y'])
        contacted += 1
        
        print(f"✅ 已联系")
        time.sleep(0.8)
    
    print("\n" + "="*60)
    print(f"✅ 自动化流程完成")
    print(f"   已联系: {contacted} 人")
    print(f"   剩余: {len(hello_buttons) - contacted} 人")
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
