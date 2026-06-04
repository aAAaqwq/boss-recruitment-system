#!/usr/bin/env python3
"""
BOSS直聘完整自动化流程
包含所有6个步骤:
1. 点击"推荐牛人"
2. 点击"筛选"
3. 勾选"985/211/本科/3年"
4. 点击"确定"
5. 扫描候选人
6. 点击"打招呼"
"""
import time
import json
from app.screen import activate_chrome, move_and_click, screenshot
from app.vision import find_text_ocr


def log_step(step_num: int, description: str):
    """打印步骤日志"""
    print(f"\n{'='*60}")
    print(f"步骤{step_num}: {description}")
    print('='*60)


def find_and_click(text: str, region: tuple = None, confidence: float = 40.0, description: str = None, fuzzy: bool = False) -> bool:
    """查找文字并点击"""
    desc = description or text
    print(f"🔍 查找: {desc}")

    # 使用screen_ocr直接识别
    from app.vision import screen_ocr

    if region:
        result = screen_ocr(region, min_confidence=confidence)
    else:
        # 全屏
        import pyautogui
        screen_width, screen_height = pyautogui.size()
        result = screen_ocr((0, 0, screen_width, screen_height), min_confidence=confidence)

    # 查找匹配的文字
    for box in result["boxes"]:
        # 精确匹配
        if text in box.text:
            x, y = box.center_x, box.center_y
            print(f"✅ 找到: {desc} (置信度: {box.confidence:.1f}, 位置: {x}, {y})")

            # 点击
            move_and_click(x, y)
            return True

        # 模糊匹配(如果启用)
        if fuzzy:
            # 检查是否包含任何一个字
            if any(char in box.text for char in text):
                x, y = box.center_x, box.center_y
                print(f"✅ 找到(模糊): {desc} -> '{box.text}' (置信度: {box.confidence:.1f}, 位置: {x}, {y})")

                # 点击
                move_and_click(x, y)
                return True

    print(f"❌ 未找到: {desc}")
    print(f"   识别到的文字: {result['full_text'][:100]}...")
    return False


def scan_candidates(region: tuple = (200, 200, 1400, 800)) -> list:
    """扫描候选人列表"""
    print("🔍 扫描候选人列表...")

    # 使用screen_ocr直接识别
    from app.vision import screen_ocr
    result = screen_ocr(region, min_confidence=40.0)

    # 查找"打招呼"按钮
    hello_buttons = []
    for box in result["boxes"]:
        if "打招呼" in box.text or "立即沟通" in box.text or "继续沟通" in box.text:
            hello_buttons.append({
                'text': box.text,
                'x': box.center_x,
                'y': box.center_y,
                'confidence': box.confidence
            })

    # 按Y坐标排序(从上到下)
    hello_buttons.sort(key=lambda b: b['y'])

    print(f"✅ 找到 {len(hello_buttons)} 个候选人")
    return hello_buttons


def extract_candidate_info(boxes: list, button_y: int, region_offset: tuple) -> dict:
    """提取候选人信息"""
    # 查找与按钮同一行的文字(Y坐标相近)
    row_boxes = [
        box for box in boxes
        if abs(box['y'] - button_y) < 30  # 同一行的阈值
    ]

    # 按X坐标排序
    row_boxes.sort(key=lambda b: b['x'])

    # 提取信息
    raw_text = " ".join(box['text'] for box in row_boxes)

    info = {
        'raw_text': raw_text,
        'name': row_boxes[0]['text'] if row_boxes else None,
        'has_985_211': '985' in raw_text or '211' in raw_text,
        'has_bachelor': '本科' in raw_text or '硕士' in raw_text or '博士' in raw_text,
        'has_3_years': any(f'{i}年' in raw_text for i in range(3, 20))
    }

    return info


def main():
    """主流程"""
    print("\n" + "="*60)
    print("BOSS直聘完整自动化流程")
    print("="*60)

    # 激活Chrome
    print("\n🚀 激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)

    # 步骤1: 点击"推荐牛人"
    log_step(1, "点击左侧'推荐牛人'")
    if not find_and_click("推荐", region=(0, 80, 140, 460), confidence=40.0, description="推荐牛人"):
        # 尝试分别查找"推荐"和"牛人"
        if not find_and_click("牛人", region=(0, 80, 140, 460), confidence=40.0):
            print("❌ 无法找到'推荐牛人'按钮")
            return
    time.sleep(1.5)

    # 步骤2: 点击"筛选"
    log_step(2, "点击右上角'筛选'按钮")
    # 扩大搜索区域到整个屏幕上半部分,降低置信度,启用模糊匹配
    if not find_and_click("筛选", region=(1000, 100, 900, 300), confidence=30.0, fuzzy=True):
        print("❌ 无法找到'筛选'按钮")
        print("💡 提示: 请确保已进入推荐页面,筛选按钮通常在右上角")
        return
    time.sleep(1.0)

    # 步骤3: 勾选筛选条件
    log_step(3, "勾选'985/211/本科/3年'")

    # 筛选面板通常在屏幕中央偏右,扩大区域并降低置信度
    filter_region = (600, 150, 800, 700)

    # 勾选985/211
    print("\n📋 勾选学校类型...")
    find_and_click("985", region=filter_region, confidence=30.0)
    time.sleep(0.3)
    find_and_click("211", region=filter_region, confidence=30.0)
    time.sleep(0.3)

    # 勾选本科
    print("\n📋 勾选学历...")
    find_and_click("本科", region=filter_region, confidence=30.0)
    time.sleep(0.3)

    # 勾选3年以上
    print("\n📋 勾选工作年限...")
    find_and_click("3年", region=filter_region, confidence=30.0)
    time.sleep(0.3)

    # 步骤4: 点击"确定"
    log_step(4, "点击'确定'按钮")
    if not find_and_click("确定", region=filter_region, confidence=30.0):
        # 尝试"确认"
        if not find_and_click("确认", region=filter_region, confidence=30.0):
            print("❌ 无法找到'确定'按钮")
            print("💡 提示: 尝试手动点击确定按钮,然后按回车继续...")
            input("按回车继续...")
    time.sleep(2.0)  # 等待列表刷新

    # 步骤5: 扫描候选人
    log_step(5, "扫描候选人列表")
    candidates = scan_candidates(region=(200, 200, 1400, 800))

    if not candidates:
        print("❌ 未找到候选人")
        return

    # 步骤6: 点击"打招呼"
    log_step(6, f"点击'打招呼' (共{len(candidates)}个候选人)")

    contacted = 0
    max_contacts = 5  # 测试阶段限制5个

    for i, button in enumerate(candidates[:max_contacts]):
        print(f"\n👤 候选人 {i+1}/{min(len(candidates), max_contacts)}")
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
    print(f"   剩余: {len(candidates) - contacted} 人")
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
