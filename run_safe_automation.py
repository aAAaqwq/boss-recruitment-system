#!/usr/bin/env python3
"""
BOSS直聘智能自动化 v5.0 - 安全版
使用固定坐标 + 学校白名单验证
"""
import time
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr
import pyautogui


# 全球顶尖高校白名单（包含简称和全称）
SCHOOL_WHITELIST = [
    # 🇨🇳 中国内地顶尖高校（C9 + 强势工科）
    "清华", "清华大学", "北大", "北京大学", "浙大", "浙江大学", "复旦", "复旦大学", 
    "上交", "上海交大", "上海交通大学", "南大", "南京大学", "中科大", "中国科学技术大学", 
    "哈工大", "哈尔滨工业大学", "西交", "西安交大", "西安交通大学", "北航", "北京航空航天大学", 
    "同济", "同济大学", "华科", "华中科技", "华中科技大学", "中山", "中山大学", 
    "华南理工", "华南理工大学", "武大", "武汉大学",
    
    # 🇭🇰 中国香港顶尖高校
    "港大", "香港大学", "HKU", "港科大", "香港科技", "香港科技大学", "HKUST", 
    "港中文", "香港中文", "香港中文大学", "CUHK", "台大", "台湾大学", "港理工", "香港理工",
    
    # 🇬🇧 英国 G5 + 顶尖名校
    "牛津", "Oxford", "剑桥", "Cambridge", "帝国理工", "Imperial", "UCL", "伦敦大学", 
    "爱丁堡", "Edinburgh", "KCL", "伦敦国王",
    
    # 🇺🇸 美国常春藤 + 超级理工/私立名校
    "哈佛", "Harvard", "斯坦福", "Stanford", "MIT", "麻省理工", "加州理工", "Caltech", 
    "普林斯顿", "Princeton", "耶鲁", "Yale", "康奈尔", "Cornell", "宾大", "宾夕法尼亚", "UPenn",
    "哥大", "哥伦比亚", "Columbia", "芝加哥大学", "Chicago", "约翰霍普金斯", "Hopkins",
    "CMU", "卡内基梅隆", "伯克利", "UC Berkeley", "Berkeley", "密歇根", "Michigan",
    "NYU", "纽约大学",
    
    # 🇸🇬 新加坡顶尖高校
    "NUS", "新加坡国立", "NTU", "南洋理工",
    
    # 🌏 亚洲及其他地区顶尖高校
    "东京大学", "东大", "京都大学", "京大", "首尔国立", "ETH", "苏黎世联邦", "EPFL", "洛桑联邦",
    "多伦多", "Toronto", "UBC", "不列颠哥伦比亚", "麦吉尔", "McGill", "墨尔本", "悉尼大学"
]

# 普通学校黑名单关键词（防止误匹配）
SCHOOL_BLACKLIST_KEYWORDS = [
    "职业", "职业技术", "专科", "高职", "技师", "技工",
    "人文", "科技学院", "学院", "民办", "独立学院",
    "电大", "函授", "成人", "自考", "网络教育"
]


def log_step(step_num: int, description: str):
    print(f"\n{'='*60}")
    print(f"步骤{step_num}: {description}")
    print('='*60)


def find_and_click_ocr(text: str, region: tuple, min_confidence: float = 15.0, retry: int = 2, save_on_fail: bool = False) -> tuple:
    """查找文字并返回坐标（带重试机制）"""
    for attempt in range(retry):
        result = screen_ocr(
            region=region,
            min_confidence=min_confidence,
            scale=3,
            preprocess=True
        )
        
        for box in result["boxes"]:
            if text in box.text:
                return (box.center_x, box.center_y, box.confidence)
        
        # 第一次失败，等待后重试
        if attempt < retry - 1:
            print(f"   ⏳ 未找到'{text}'，等待0.5秒后重试...")
            time.sleep(0.5)
    
    # 所有尝试失败，保存截图
    if save_on_fail:
        os.makedirs("debug_screenshots", exist_ok=True)
        from PIL import ImageGrab
        x0, y0, w, h = region
        img = ImageGrab.grab(bbox=(x0, y0, x0+w, y0+h))
        filename = f"debug_screenshots/fail_{text}_{int(time.time())}.png"
        img.save(filename)
        print(f"   💾 已保存失败截图: {filename}")
    
    return None


def check_candidate_school(text: str) -> bool:
    """检查候选人是否来自白名单学校（优化版：防误匹配 + 模糊匹配）"""
    # 1. 清理文本：去除所有空格、标点、特殊字符
    text_clean = re.sub(r'[\s\u3000\-_·•]', '', text)  # 去除空格、全角空格、连字符等
    text_clean = text_clean.lower()  # 转小写（用于英文匹配）
    
    # 2. 黑名单检查：如果包含普通学校关键词，直接拒绝
    for keyword in SCHOOL_BLACKLIST_KEYWORDS:
        if keyword in text_clean:
            return False
    
    # 3. 白名单匹配
    for school in SCHOOL_WHITELIST:
        school_clean = re.sub(r'[\s\u3000\-_·•]', '', school).lower()
        
        # 3.1 完全匹配（最高优先级）
        if school_clean == text_clean:
            return True
        
        # 3.2 包含匹配（需要额外验证）
        if school_clean in text_clean:
            # 短名称（≤3个字符）需要更严格的验证
            if len(school_clean) <= 3:
                # 检查是否是独立词（前后不是字母或汉字）
                idx = text_clean.find(school_clean)
                before = text_clean[idx-1] if idx > 0 else ' '
                after = text_clean[idx+len(school_clean)] if idx+len(school_clean) < len(text_clean) else ' '
                
                # 检查前面是否有汉字（可能是另一个学校的一部分）
                # 例如："中南大学"包含"南大"，但"南大"前面有"中"，应该跳过
                if before and '\u4e00' <= before <= '\u9fff':  # 前面是汉字
                    continue  # 跳过，可能是误匹配
                
                # 如果后面是字母或汉字，需要特殊处理
                if after.isalnum():
                    # 特殊处理：中山、华科等，检查是否有"大学"后缀
                    if school in ["中山", "华科", "武大", "南大", "浙大", "复旦", "北大", "清华"]:
                        # 检查是否有"大学"后缀
                        if "大学" in text_clean[idx:idx+len(school_clean)+2]:
                            return True
                        else:
                            continue  # 跳过，可能是误匹配
                    else:
                        continue
                else:
                    return True  # 独立短名称
            else:
                # 长名称（>3个字符）直接匹配
                return True
    
    return False


def extract_candidate_info(boxes: list, button_y: int) -> dict:
    """提取候选人信息（包含按钮上方的学校信息）"""
    # 查找按钮上方200像素内的所有文字（包含学校、学历、工作年限等）
    row_boxes = [
        box for box in boxes
        if button_y - 200 < box.center_y < button_y + 50  # 上方200像素到下方50像素
    ]
    
    # 按Y坐标排序（从上到下），再按X坐标排序（从左到右）
    row_boxes.sort(key=lambda b: (b.center_y, b.center_x))
    
    # 提取信息
    raw_text = " ".join(box.text for box in row_boxes)
    
    info = {
        'raw_text': raw_text,
        'name': row_boxes[0].text if row_boxes else None,
        'school_match': check_candidate_school(raw_text),
        'has_bachelor': '本科' in raw_text or '硕士' in raw_text or '博士' in raw_text,
        'has_3_years': any(f'{i}年' in raw_text for i in range(3, 20))
    }
    
    return info


def main():
    print("\n" + "="*60)
    print("BOSS直聘智能自动化 v5.0 - 安全版")
    print("使用固定坐标 + 学校白名单验证")
    print("="*60)
    
    print(f"\n📋 学校白名单({len(SCHOOL_WHITELIST)}所):")
    print(f"   {', '.join(SCHOOL_WHITELIST)}")
    
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
    
    print("⏳ 等待页面加载...")
    time.sleep(2.5)  # 增加等待时间，确保页面完全渲染
    
    # 步骤2: 点击"筛选"（降低置信度 + 重试 + 保存失败截图）
    log_step(2, "点击右上角'筛选'按钮")
    result = find_and_click_ocr(
        "筛选", 
        region=(screen_width-500, 100, 500, 200),
        min_confidence=8.0,  # 降低置信度阈值
        retry=3,  # 重试3次
        save_on_fail=True  # 失败时保存截图
    )
    if result:
        x, y, conf = result
        print(f"✅ 找到: 筛选 (置信度: {conf:.1f}, 位置: {x}, {y})")
        move_and_click(x, y)
    else:
        print("❌ 无法找到'筛选'按钮（已保存截图到debug_screenshots/）")
        return
    
    print("⏳ 等待筛选生效...")
    time.sleep(2.0)
    
    # 步骤3: 使用超高清OCR识别筛选选项
    log_step(3, "勾选筛选条件（超高清OCR）")
    
    # 扫描筛选面板 - 使用超高清设置
    filter_region = (screen_width//2, 100, screen_width//2, 800)
    
    print("\n🔍 使用超高清OCR扫描筛选面板...")
    result = screen_ocr(
        region=filter_region,
        min_confidence=5.0,  # 超低置信度
        scale=5,  # 超高放大倍数
        preprocess=True
    )
    
    # 查找关键词
    yuanxiao_pos = None
    shuangyiliu_pos = None
    benke_pos = None
    found_985 = None
    found_211 = None
    
    print(f"\n识别到 {len(result['boxes'])} 个文本框")
    
    # 按Y坐标排序显示所有识别结果
    print("\n=== 所有识别结果 ===")
    sorted_boxes = sorted(result["boxes"], key=lambda b: b.center_y)
    for i, box in enumerate(sorted_boxes[:50], 1):  # 只显示前50个
        print(f"{i:3d}. [{box.center_x:4d}, {box.center_y:4d}] {box.confidence:5.1f}% | {box.text}")
    print("=" * 60)
    
    for box in result["boxes"]:
        text = box.text
        
        # 查找"院校"
        if "院校" in text and "双" not in text and "一流" not in text:
            yuanxiao_pos = (box.center_x, box.center_y)
            print(f"✅ 找到'院校': ({box.center_x}, {box.center_y}) - '{text}'")
        
        # 查找"双一流"
        elif "双一流" in text or ("双" in text and "一流" in text):
            shuangyiliu_pos = (box.center_x, box.center_y)
            print(f"✅ 找到'双一流': ({box.center_x}, {box.center_y}) - '{text}'")
        
        # 查找"本科"
        elif "本科" in text:
            benke_pos = (box.center_x, box.center_y)
            print(f"✅ 找到'本科': ({box.center_x}, {box.center_y}) - '{text}'")
        
        # 查找"985"
        elif "985" in text:
            found_985 = (box.center_x, box.center_y)
            print(f"✅ 找到'985': ({box.center_x}, {box.center_y}) - '{text}'")
        
        # 查找"211"
        elif "211" in text:
            found_211 = (box.center_x, box.center_y)
            print(f"✅ 找到'211': ({box.center_x}, {box.center_y}) - '{text}'")
    
    # 策略1: 直接点击识别到的985/211
    if found_985:
        print(f"\n📋 点击985 ({found_985[0]}, {found_985[1]})")
        move_and_click(found_985[0], found_985[1])
        time.sleep(0.5)
    elif yuanxiao_pos and shuangyiliu_pos:
        # 策略2: 计算中间位置
        mid_x = (yuanxiao_pos[0] + shuangyiliu_pos[0]) // 2
        mid_y = yuanxiao_pos[1]
        print(f"\n📋 点击985区域（推算位置: {mid_x}, {mid_y}）")
        move_and_click(mid_x, mid_y)
        time.sleep(0.5)
    else:
        print("\n⚠️ 未找到985选项")
    
    if found_211:
        print(f"\n📋 点击211 ({found_211[0]}, {found_211[1]})")
        move_and_click(found_211[0], found_211[1])
        time.sleep(0.5)
    else:
        print("\n⚠️ 未找到211选项")
    
    # 点击"本科" - 多策略搜索
    if benke_pos:
        print(f"\n📋 点击本科 ({benke_pos[0]}, {benke_pos[1]})")
        move_and_click(benke_pos[0], benke_pos[1])
        time.sleep(0.5)
    else:
        # 策略2: 在985/211下方区域重新搜索"本科"
        print("\n🔍 在下方区域重新搜索'本科'...")
        if found_985 or yuanxiao_pos:
            # 计算搜索区域（985/211下方100-300像素，扩大范围）
            base_y = found_985[1] if found_985 else yuanxiao_pos[1]
            lower_region = (screen_width//2, base_y + 100, screen_width//2, 300)  # 从100像素开始，搜索300像素高度
            
            result2 = screen_ocr(
                region=lower_region,
                min_confidence=3.0,  # 更低置信度
                scale=5,
                preprocess=True
            )
            
            for box in result2["boxes"]:
                if "本科" in box.text or "本" in box.text:
                    benke_pos = (box.center_x, box.center_y)
                    print(f"✅ 找到'本科': ({box.center_x}, {box.center_y}) - '{box.text}'")
                    print(f"📋 点击本科 ({benke_pos[0]}, {benke_pos[1]})")
                    move_and_click(benke_pos[0], benke_pos[1])
                    time.sleep(0.5)
                    break
            else:
                print("⚠️ 仍未找到本科选项，跳过")
        else:
            print("⚠️ 未找到本科选项，跳过")
    
    # 步骤4: 点击绿色"确定"按钮（简化版OCR）
    log_step(4, "点击绿色'确定'按钮")
    
    print("🔍 搜索确定按钮（屏幕右下角）...")
    # 搜索屏幕右下角400x150区域
    confirm_region = (screen_width-400, screen_height-150, 400, 150)
    result_confirm = screen_ocr(
        region=confirm_region,
        min_confidence=5.0,
        scale=5,
        preprocess=True
    )
    
    confirm_found = False
    # 查找"确定"或"清除"（然后推算确定位置）
    for box in result_confirm["boxes"]:
        if "确定" in box.text:
            print(f"✅ 找到确定按钮: ({box.center_x}, {box.center_y})")
            move_and_click(box.center_x, box.center_y)
            confirm_found = True
            break
        elif "清除" in box.text:
            # 确定在清除右侧约100像素
            confirm_x = box.center_x + 100
            confirm_y = box.center_y
            print(f"✅ 通过清除推算确定位置: ({confirm_x}, {confirm_y})")
            move_and_click(confirm_x, confirm_y)
            confirm_found = True
            break
    
    if not confirm_found:
        print("⚠️ 未找到确定按钮，跳过筛选...")
    
    time.sleep(2.0)
    
    # 步骤5: 智能扫描和联系候选人（带学校验证）
    log_step(5, "智能扫描候选人（学校白名单验证）")
    
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
            min_confidence=10.0,  # 降低置信度，避免漏掉
            scale=3,
            preprocess=True
        )
        
        # 查找"打招呼"按钮 - 只匹配打招呼，不匹配继续沟通
        hello_buttons = []
        for box in result["boxes"]:
            # 只匹配"打招呼"和"立即沟通"，不匹配"继续沟通"
            if ("打招呼" in box.text or "立即沟通" in box.text or "招呼" in box.text) and "继续" not in box.text:
                hello_buttons.append({
                    'text': box.text,
                    'x': box.center_x,
                    'y': box.center_y
                })
        
        hello_buttons.sort(key=lambda b: b['y'])
        print(f"   找到 {len(hello_buttons)} 个候选人")
        
        # 🔍 调试：显示所有找到的按钮
        if len(hello_buttons) > 0:
            print("   📋 按钮列表：")
            for i, btn in enumerate(hello_buttons[:5], 1):  # 只显示前5个
                print(f"      {i}. {btn['text']} at ({btn['x']}, {btn['y']})")
        
        # 验证并点击
        for button in hello_buttons:
            if contacted >= max_contacts:
                print(f"\n✅ 已达到每日上限({max_contacts}人)")
                break
            
            # 提取候选人信息
            info = extract_candidate_info(result["boxes"], button['y'])
            
            print(f"\n👤 候选人 {contacted + skipped + 1}")
            print(f"   姓名: {info['name']}")
            print(f"   完整信息: {info['raw_text'][:150]}...")  # 显示更多信息用于调试
            print(f"   学校匹配: {'✅' if info['school_match'] else '❌'}")
            
            # 🔍 调试：显示匹配到的学校（如果有）
            if info['school_match']:
                matched_schools = [s for s in SCHOOL_WHITELIST if s in info['raw_text']]
                print(f"   匹配学校: {', '.join(matched_schools[:3])}")
            
            # 学校白名单验证
            if not info['school_match']:
                print(f"   ⏭️ 跳过（不在白名单）")
                skipped += 1
                continue
            
            # 点击"打招呼"
            print(f"   位置: ({button['x']}, {button['y']})")
            print(f"   ✅ 准备联系...")
            move_and_click(button['x'], button['y'])
            contacted += 1
            print(f"   ✅ 已联系 #{contacted}")
            
            # 随机延迟3-8秒，避免被识别为机器
            import random
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
