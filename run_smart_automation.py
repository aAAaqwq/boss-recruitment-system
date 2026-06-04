#!/usr/bin/env python3
"""
BOSS直聘智能自动化 - 基于参考项目的完整实现
使用参考项目中验证过的OCR策略和坐标
"""
import time
import sys
import os

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr, click_text_ocr


def log_step(step_num: int, description: str):
    """打印步骤日志"""
    print(f"\n{'='*60}")
    print(f"步骤{step_num}: {description}")
    print('='*60)


def smart_click(text: str, region: tuple, min_confidence: float = 20.0, scale: int = 3, fuzzy: bool = False) -> bool:
    """
    智能点击 - 使用多种策略
    """
    print(f"🔍 查找: {text}")
    
    # 策略1: 标准OCR
    result = screen_ocr(
        region=region,
        lang="chi_sim+eng",
        min_confidence=min_confidence,
        scale=scale,
        preprocess=True
    )
    
    # 精确匹配
    for box in result["boxes"]:
        if text in box.text:
            print(f"✅ 找到: {text} (置信度: {box.confidence:.1f}, 位置: {box.center_x}, {box.center_y})")
            move_and_click(box.center_x, box.center_y)
            return True
    
    # 策略2: 超低置信度重试
    if min_confidence > 5.0:
        result2 = screen_ocr(
            region=region,
            lang="chi_sim+eng",
            min_confidence=5.0,  # 超低置信度
            scale=scale,
            preprocess=True
        )
        
        for box in result2["boxes"]:
            if text in box.text:
                print(f"✅ 找到(低置信度): {text} (置信度: {box.confidence:.1f}, 位置: {box.center_x}, {box.center_y})")
                move_and_click(box.center_x, box.center_y)
                return True
    
    # 策略3: 模糊匹配
    if fuzzy:
        for box in result["boxes"]:
            if len(box.text) >= 2 and any(char in box.text for char in text):
                print(f"✅ 找到(模糊): {text} -> '{box.text}' (置信度: {box.confidence:.1f}, 位置: {box.center_x}, {box.center_y})")
                move_and_click(box.center_x, box.center_y)
                return True
    
    print(f"❌ 未找到: {text}")
    print(f"   识别到的文字: {result['full_text'][:200]}")
    return False


def main():
    """主流程 - 使用参考项目验证过的坐标和策略"""
    print("\n" + "="*60)
    print("BOSS直聘智能自动化 v2.0")
    print("基于参考项目的完整实现")
    print("="*60)
    
    # 激活Chrome
    print("\n🚀 激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)
    
    # 步骤1: 点击"推荐牛人"
    log_step(1, "点击左侧'推荐牛人'")
    # 参考项目使用的区域: (0, 80, 140, 460)
    if not smart_click("推荐", region=(0, 80, 140, 460), min_confidence=20.0):
        # 尝试"牛人"
        if not smart_click("牛人", region=(0, 80, 140, 460), min_confidence=20.0):
            print("❌ 无法找到'推荐牛人'按钮")
            return
    time.sleep(1.5)
    
    # 步骤2: 点击"筛选"
    log_step(2, "点击右上角'筛选'按钮")
    # 扩大搜索区域，使用更低的置信度
    import pyautogui
    screen_width, screen_height = pyautogui.size()
    
    # 尝试多个策略
    success = False
    
    # 策略1: 右上角区域 - 精确匹配
    if smart_click("筛选", region=(screen_width-500, 100, 500, 200), min_confidence=20.0, fuzzy=False):
        success = True
    
    # 策略2: 更大的右侧区域 - 模糊匹配
    if not success and smart_click("筛选", region=(screen_width-600, 80, 600, 300), min_confidence=15.0, fuzzy=True):
        success = True
    
    if not success:
        print("❌ 无法找到'筛选'按钮")
        print("💡 提示: 请手动点击'筛选'按钮，然后按回车继续...")
        input("按回车继续...")
    
    # 等待筛选面板完全打开
    print("⏳ 等待筛选面板打开...")
    time.sleep(2.0)  # 增加等待时间
    
    # 步骤3: 勾选筛选条件
    log_step(3, "勾选'985/211/本科/3年'")
    
    # 筛选面板在屏幕右侧（浅橙色背景）
    # 使用更大的区域，从屏幕中央到右边缘
    filter_region = (screen_width//2, 100, screen_width//2, 800)
    
    # 先验证筛选面板是否打开，查找“学历”或“工作年限”等标题
    print("\n🔍 验证筛选面板是否打开...")
    result = screen_ocr(
        region=filter_region,
        min_confidence=15.0,
        scale=3,
        preprocess=True
    )
    
    panel_opened = False
    for box in result["boxes"]:
        if "学历" in box.text or "工作年限" in box.text or "学校" in box.text or "院校" in box.text:
            panel_opened = True
            print(f"✅ 筛选面板已打开，找到: {box.text}")
            break
    
    if not panel_opened:
        print("⚠️ 筛选面板可能未完全打开，再等待1秒...")
        time.sleep(1.0)
    
    print("\n📋 勾选学校类型...")
    # 尝试多种表达方式
    found_985 = False
    found_211 = False
    
    # 策略1: 精确匹配 "985"
    if smart_click("985", region=filter_region, min_confidence=15.0, fuzzy=False):
        found_985 = True
    # 策略2: 查找包含"985"的文字
    elif smart_click("985/211", region=filter_region, min_confidence=15.0, fuzzy=False):
        found_985 = True
        found_211 = True  # 985/211一起点击了
    # 策略3: 查找"名校"
    elif smart_click("名校", region=filter_region, min_confidence=15.0, fuzzy=False):
        found_985 = True
        found_211 = True  # 名校通常包含985/211
    
    if not found_985:
        print("⚠️ 未找到985选项，跳过")
    time.sleep(0.5)
    
    # 如果还没找到211，继续查找
    if not found_211:
        if not smart_click("211", region=filter_region, min_confidence=15.0, fuzzy=False):
            print("⚠️ 未找到211选项，跳过")
    time.sleep(0.5)
    
    print("\n📋 勾选学历...")
    if not smart_click("本科", region=filter_region, min_confidence=15.0, fuzzy=False):
        print("⚠️ 未找到本科选项，跳过")
    time.sleep(0.5)
    
    print("\n📋 勾选工作年限...")
    # 尝试多种表达
    if not smart_click("3年", region=filter_region, min_confidence=15.0, fuzzy=False):
        if not smart_click("3-5年", region=filter_region, min_confidence=15.0, fuzzy=False):
            if not smart_click("3-5", region=filter_region, min_confidence=15.0, fuzzy=False):
                print("⚠️ 未找到工作年限选项，跳过")
    time.sleep(0.5)
    
    # 步骤4: 点击"确定"
    log_step(4, "点击'确定'按钮")
    # 扩大搜索区域到整个屏幕下半部分
    confirm_region = (screen_width//4, screen_height//2, screen_width*3//4, screen_height//2)
    
    if not smart_click("确定", region=confirm_region, min_confidence=15.0, fuzzy=False):
        if not smart_click("确认", region=confirm_region, min_confidence=15.0, fuzzy=False):
            # 尝试模糊匹配
            if not smart_click("确定", region=confirm_region, min_confidence=15.0, fuzzy=True):
                print("❌ 无法找到'确定'按钮")
                print("💡 提示: 请手动点击'确定'按钮，然后按回车继续...")
                input("按回车继续...")
    
    time.sleep(2.0)  # 等待列表刷新
    
    # 步骤5: 扫描候选人
    log_step(5, "扫描候选人列表")
    
    # 候选人列表区域 - 使用参考项目的策略
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
        if "打招呼" in box.text or "立即沟通" in box.text or "继续沟通" in box.text or "招呼" in box.text:
            hello_buttons.append({
                'text': box.text,
                'x': box.center_x,
                'y': box.center_y,
                'confidence': box.confidence
            })
    
    # 按Y坐标排序
    hello_buttons.sort(key=lambda b: b['y'])
    
    print(f"✅ 找到 {len(hello_buttons)} 个候选人")
    
    if not hello_buttons:
        print("❌ 未找到候选人")
        return
    
    # 步骤6: 点击"打招呼"
    log_step(6, f"点击'打招呼' (共{len(hello_buttons)}个候选人)")
    
    contacted = 0
    max_contacts = 5  # 测试阶段限制5个
    
    for i, button in enumerate(hello_buttons[:max_contacts]):
        print(f"\n👤 候选人 {i+1}/{min(len(hello_buttons), max_contacts)}")
        print(f"   位置: ({button['x']}, {button['y']})")
        print(f"   按钮: {button['text']}")
        
        # 点击"打招呼"
        move_and_click(button['x'], button['y'])
        contacted += 1
        
        print(f"✅ 已联系")
        time.sleep(0.8)  # 避免操作过快
    
    # 完成
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
