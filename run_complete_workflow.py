#!/usr/bin/env python3
"""完整的BOSS招聘自动化流程"""
import sys
from pathlib import Path
import time
import random

sys.path.insert(0, str(Path(__file__).parent))

from app.vision import screen_ocr, click_text_ocr
from app.screen import move_and_click
from app.database import Database
import pyautogui

# 配置
SCHOOL_WHITELIST = [
    "清华大学", "北京大学", "浙江大学", "复旦大学",
    "上海交通大学", "华中科技大学", "武汉大学", "中山大学",
    "西安交通大学", "南京大学", "哈尔滨工业大学", "北京航空航天大学"
]

DAILY_CAP = 80
DRY_RUN = True  # 先Dry Run

print("=" * 60)
print("BOSS招聘自动化 - 完整流程")
print("=" * 60)
print(f"\n配置:")
print(f"  学校白名单: {len(SCHOOL_WHITELIST)}所")
print(f"  每日上限: {DAILY_CAP}人")
print(f"  模式: {'Dry Run' if DRY_RUN else '真实执行'}")

# 初始化数据库
db = Database()
with db:
    db.init_tables()

# 步骤1: 点击"推荐牛人"
print("\n" + "=" * 60)
print("步骤1: 点击'推荐牛人'")
print("=" * 60)

recommend_coord = None
for keyword in ["推荐牛人", "推荐", "牛人"]:
    coord = click_text_ocr(keyword, (0, 80, 230, 460), min_confidence=40.0)
    if coord:
        print(f"✅ 找到: {keyword} 位置: {coord}")
        move_and_click(coord[0], coord[1])
        recommend_coord = coord
        break

if not recommend_coord:
    print("❌ 未找到'推荐牛人'按钮")
    sys.exit(1)

time.sleep(2)  # 等待页面加载

# 步骤2: 点击右上角"筛选"按钮
print("\n" + "=" * 60)
print("步骤2: 点击右上角'筛选'按钮")
print("=" * 60)

screen_width, screen_height = pyautogui.size()
right_top_region = (screen_width - 400, 0, screen_width, 200)

filter_coord = None
for keyword in ["筛选", "筛", "filter"]:
    coord = click_text_ocr(keyword, (0, 0, screen_width, screen_height // 2), min_confidence=40.0)
    if coord:
        print(f"✅ 找到: {keyword} 位置: {coord}")
        move_and_click(coord[0], coord[1])
        filter_coord = coord
        break

if not filter_coord:
    print("❌ 未找到'筛选'按钮")
    print("尝试扫描右上角区域...")
    result = screen_ocr(region=(0, 0, screen_width, screen_height // 2), min_confidence=40.0)
    print(f"识别到的文字:")
    for box in result["boxes"][:10]:
        print(f"  {box.text} (位置: {box.center_x}, {box.center_y})")
    sys.exit(1)

time.sleep(1)  # 等待筛选面板弹出

# 步骤3: 勾选筛选条件
print("\n" + "=" * 60)
print("步骤3: 勾选筛选条件")
print("=" * 60)

# 扫描筛选面板区域（通常在屏幕中央偏右）
filter_panel_region = (screen_width // 2, 100, screen_width - 100, screen_height - 100)

filter_options = ["985", "211", "本科", "3年"]
selected_count = 0

for option in filter_options:
    coord = click_text_ocr(option, filter_panel_region, min_confidence=40.0)
    if coord:
        print(f"✅ 找到: {option} 位置: {coord}")
        move_and_click(coord[0], coord[1])
        selected_count += 1
        time.sleep(0.3)
    else:
        print(f"⚠️ 未找到: {option}")

if selected_count == 0:
    print("❌ 未找到任何筛选条件")
    sys.exit(1)

# 步骤4: 点击"确定"按钮
print("\n" + "=" * 60)
print("步骤4: 点击'确定'按钮")
print("=" * 60)

confirm_coord = None
for keyword in ["确定", "确认", "应用", "OK"]:
    coord = click_text_ocr(keyword, filter_panel_region, min_confidence=40.0)
    if coord:
        print(f"✅ 找到: {keyword} 位置: {coord}")
        move_and_click(coord[0], coord[1])
        confirm_coord = coord
        break

if not confirm_coord:
    print("❌ 未找到'确定'按钮")
    sys.exit(1)

time.sleep(2)  # 等待候选人列表刷新

# 步骤5: 扫描候选人列表
print("\n" + "=" * 60)
print("步骤5: 扫描候选人列表")
print("=" * 60)

# 候选人列表区域（屏幕中央）
candidate_list_region = (300, 150, screen_width - 300, screen_height - 100)

result = screen_ocr(region=candidate_list_region, min_confidence=60.0)

print(f"识别到 {len(result['boxes'])} 个文本框")

# 解析候选人信息
candidates = []
current_candidate = {}

for box in result["boxes"]:
    text = box.text.strip()
    
    # 检测学校
    for school in SCHOOL_WHITELIST:
        if school in text:
            if current_candidate:
                candidates.append(current_candidate)
            current_candidate = {
                "school": school,
                "position": (box.center_x, box.center_y),
                "text": text
            }
            break

if current_candidate:
    candidates.append(current_candidate)

print(f"\n找到 {len(candidates)} 位白名单学校候选人:")
for i, candidate in enumerate(candidates, 1):
    print(f"  {i}. {candidate['school']} (位置: {candidate['position']})")

# 步骤6: 点击"打招呼"
print("\n" + "=" * 60)
print("步骤6: 点击'打招呼'")
print("=" * 60)

if DRY_RUN:
    print(f"\n🔵 Dry Run模式: 将联系 {len(candidates)} 位候选人")
    print("\n是否继续真实执行？")
    confirm = input("输入 'y' 继续，其他键取消: ")
    
    if confirm.lower() != 'y':
        print("\n❌ 用户取消操作")
        sys.exit(0)
    
    print("\n切换到真实执行模式...")
    DRY_RUN = False

contacted_count = 0

for i, candidate in enumerate(candidates, 1):
    if contacted_count >= DAILY_CAP:
        print(f"\n⚠️ 已达到每日上限 {DAILY_CAP} 人")
        break
    
    print(f"\n处理候选人 {i}/{len(candidates)}: {candidate['school']}")
    
    # 在候选人卡片附近查找"打招呼"按钮
    x, y = candidate['position']
    button_region = (x - 200, y - 100, x + 200, y + 100)
    
    hello_coord = None
    for keyword in ["打招呼", "立即沟通", "继续沟通"]:
        coord = click_text_ocr(keyword, button_region, min_confidence=40.0)
        if coord:
            print(f"  ✅ 找到: {keyword} 位置: {coord}")
            move_and_click(coord[0], coord[1])
            hello_coord = coord
            contacted_count += 1
            
            # 记录到数据库
            with Database() as db:
                db.insert_contact_record(
                    boss_id=f"unknown_{int(time.time())}",
                    action="contacted",
                    success=True
                )
            
            time.sleep(random.uniform(0.4, 0.6))
            break
    
    if not hello_coord:
        print(f"  ⚠️ 未找到'打招呼'按钮")

print("\n" + "=" * 60)
print("流程完成")
print("=" * 60)
print(f"\n✅ 成功联系 {contacted_count} 位候选人")
