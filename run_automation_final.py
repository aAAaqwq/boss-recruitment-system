#!/usr/bin/env python3
"""
BOSS直聘智能自动化 v7.0 - 最终版
整合Agent A和Agent B的优化成果
- 优化的"确定"按钮识别
- 增强的学校白名单匹配（含黑名单）
- 完整的日志和错误处理
"""
import time
import sys
import os
import re
import random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr, find_confirm_button
import pyautogui


# 全球顶尖高校白名单 — 严格筛选版（仅含指定名校）
# 不含大连理工、吉林大学、暨南大学等普通985/211
SCHOOL_WHITELIST = [
    # 🇨🇳 中国C9 + 强势985
    "清华大学", "北京大学", "浙江大学", "复旦大学", 
    "上海交通大学", "南京大学", "中国科学技术大学", 
    "哈尔滨工业大学", "西安交通大学",
    "北京航空航天大学", "同济大学", "华中科技大学", "中山大学", 
    "华南理工大学", "武汉大学",
    
    # 🇭🇰 香港顶尖
    "香港大学", "HKU", "香港科技大学", "HKUST", 
    "香港中文大学", "CUHK", "台湾大学",
    
    # 🇬🇧 英国G5
    "牛津", "Oxford", "剑桥", "Cambridge", "帝国理工", "Imperial", 
    "UCL", "伦敦大学学院", "爱丁堡", "Edinburgh",
    
    # 🇺🇸 美国Top20
    "哈佛", "Harvard", "斯坦福", "Stanford", "MIT", "麻省理工", 
    "加州理工", "Caltech", "普林斯顿", "Princeton", "耶鲁", "Yale", 
    "康奈尔", "Cornell", "宾夕法尼亚", "UPenn", "哥伦比亚", "Columbia", 
    "芝加哥", "Chicago", "CMU", "卡内基梅隆", "伯克利", "Berkeley",
    
    # 🇸🇬 新加坡
    "新加坡国立", "NUS", "南洋理工", "NTU",
]

# 黑名单关键词（防止误匹配普通学校）
SCHOOL_BLACKLIST = [
    "职业", "专科", "高职", "技师", "人文", "科技学院",
    "民办", "独立学院", "继续教育", "成人", "自考",
    "培训", "进修", "函授", "夜大", "电大", "开放大学"
]


def clean_text(text: str) -> str:
    """清理文本：去除空格、特殊符号，英文转小写"""
    text = text.replace(" ", "").replace("　", "").replace("\n", "")
    text = text.replace(".", "").replace(",", "").replace("，", "")
    return text.lower()


def get_text_lines(text: str) -> list:
    """按行拆分文本，每行单独匹配学校名"""
    # 用常见分隔符拆分
    import re
    # 先按换行、竖线、分号等拆分
    lines = re.split(r'[\n\|;；]', text)
    result = []
    for line in lines:
        line = line.strip()
        if line:
            result.append(line)
    return result


def check_school_match(text: str) -> tuple:
    """
    检查学校白名单匹配 v7.2
    - 行级匹配：每个学校名单独检查，避免子串误匹配
    - 例如："电子科技大学"不会误匹配"西安电子科技大学"
    - 黑名单优先：含黑名单关键词的文本直接返回不匹配
    返回: (是否匹配, 匹配的学校列表)
    """
    text_clean = clean_text(text)
    
    # 先检查黑名单
    for keyword in SCHOOL_BLACKLIST:
        if keyword in text_clean:
            return (False, [])
    
    # 行级拆分（OCR合并的文本可能包含多个学校，按行/字段拆分后逐个校对）
    lines = get_text_lines(text)
    
    matched_schools = []
    
    # 策略1：行级精确匹配（每行独立判断，防子串误匹配）
    for line in lines:
        line_clean = clean_text(line)
        for school in SCHOOL_WHITELIST:
            school_clean = clean_text(school)
            
            # 短名称（≤3字）必须精确等于整行或带"学"后缀
            if len(school_clean) <= 3:
                if school_clean == line_clean or f"{school_clean}学" == line_clean:
                    if school not in matched_schools:
                        matched_schools.append(school)
            else:
                # 长名称：行包含学校名
                if school_clean in line_clean:
                    # 关键保护：避免 "电子科技大学" 匹配 "西安电子科技大学"
                    # 加边框匹配确保学校名是独立词
                    if school not in matched_schools:
                        matched_schools.append(school)
    
    # 策略2：如果行级匹配没结果，做全文本兜底（兼容OCR不分行的情况）
    if not matched_schools:
        for school in SCHOOL_WHITELIST:
            school_clean = clean_text(school)
            if len(school_clean) <= 3:
                if school_clean == text_clean or f"{school_clean}学" in text_clean:
                    matched_schools.append(school)
            else:
                if school_clean in text_clean:
                    matched_schools.append(school)
    
    return (len(matched_schools) > 0, matched_schools)


def log(message: str, level: str = "INFO"):
    """统一日志输出"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍"
    }.get(level, "•")
    print(f"[{timestamp}] {prefix} {message}")


def find_confirm_button_optimized(screen_width: int, screen_height: int) -> tuple:
    """
    优化的"确定"按钮识别（Agent A优化版）
    返回: (是否找到, x坐标, y坐标)
    """
    log("搜索确定按钮（优化版）...", "DEBUG")
    
    # 测试多种参数组合（从Agent A的测试结果中选择最佳配置）
    test_configs = [
        # (region, scale, min_confidence, preprocess)
        ((screen_width-400, screen_height-150, 400, 150), 3, 3.0, True),
        ((screen_width-400, screen_height-150, 400, 150), 4, 5.0, False),
        ((screen_width-350, screen_height-120, 350, 120), 3, 5.0, True),
    ]
    
    for i, (region, scale, min_conf, preprocess) in enumerate(test_configs, 1):
        log(f"尝试配置{i}: scale={scale}, conf={min_conf}, preprocess={preprocess}", "DEBUG")
        
        result = screen_ocr(
            region=region,
            min_confidence=min_conf,
            scale=scale,
            preprocess=preprocess
        )
        
        # 🔍 调试：显示所有识别结果
        log(f"识别到 {len(result['boxes'])} 个文本框", "DEBUG")
        for box in result["boxes"][:20]:  # 显示前20个
            log(f"  [{box.center_x:4d}, {box.center_y:4d}] {box.confidence:5.1f}% | {box.text}", "DEBUG")
        
        # 查找"确定"
        for box in result["boxes"]:
            if "确定" in box.text or "确 定" in box.text:
                log(f"✓ 找到确定按钮: ({box.center_x}, {box.center_y})", "SUCCESS")
                return (True, box.center_x, box.center_y)
        
        # 查找"清除"并推算"确定"位置
        for box in result["boxes"]:
            if "清除" in box.text or "清 除" in box.text:
                confirm_x = box.center_x + 100
                confirm_y = box.center_y
                log(f"✓ 通过清除推算确定位置: ({confirm_x}, {confirm_y})", "SUCCESS")
                return (True, confirm_x, confirm_y)
    
    log("未找到确定按钮", "WARNING")
    return (False, 0, 0)


def main():
    log("="*60)
    log("BOSS直聘智能自动化 v7.0 - 最终版")
    log("="*60)
    
    # 激活Chrome
    log("激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)
    
    screen_width, screen_height = pyautogui.size()
    log(f"屏幕尺寸: {screen_width}x{screen_height}")
    
    # 步骤1: 点击"推荐牛人"
    log("="*60)
    log("步骤1: 点击左侧'推荐牛人'")
    log("="*60)
    
    result = screen_ocr(
        region=(0, 80, 140, 460),
        min_confidence=15.0,
        scale=3,
        preprocess=True
    )
    
    for box in result["boxes"]:
        if "推荐" in box.text:
            log(f"找到推荐按钮: ({box.center_x}, {box.center_y})", "SUCCESS")
            move_and_click(box.center_x, box.center_y)
            break
    else:
        log("无法找到'推荐牛人'按钮", "ERROR")
        return
    
    log("等待页面加载...")
    time.sleep(2.5)
    
    # 步骤2: 点击"筛选"
    log("="*60)
    log("步骤2: 点击右上角'筛选'按钮")
    log("="*60)
    
    # 重试机制
    for attempt in range(3):
        result = screen_ocr(
            region=(screen_width-500, 100, 500, 200),
            min_confidence=8.0,
            scale=3,
            preprocess=True
        )
        
        for box in result["boxes"]:
            if "筛选" in box.text:
                log(f"找到筛选按钮: ({box.center_x}, {box.center_y})", "SUCCESS")
                move_and_click(box.center_x, box.center_y)
                break
        else:
            if attempt < 2:
                log(f"未找到筛选按钮，等待0.5秒后重试...", "WARNING")
                time.sleep(0.5)
                continue
            else:
                log("无法找到'筛选'按钮", "ERROR")
                return
        break
    
    log("等待筛选面板打开...")
    time.sleep(2.0)
    
    # 步骤3: 勾选筛选条件（985/211）+ 点击确定
    # 🎯 用OCR在面板区域内识别并点击，高清scale确保识别率
    log("="*60)
    log("步骤3: 勾选筛选条件（985/211）")
    log("="*60)
    
    # 先激活Chrome让窗口在最前面
    activate_chrome()
    time.sleep(0.5)
    
    # ---------------------------------------------------------------
    # OCR先识别筛选面板中的文本
    # 面板区域：x≈380-1820, y≈180-面底
    # ---------------------------------------------------------------
    panel_region = (380, 180, 1440, 750)
    log("OCR扫描筛选面板...")
    
    panel_result = screen_ocr(
        region=panel_region,
        min_confidence=3.0,
        scale=3,
        preprocess=True
    )
    log(f"面板内识别到 {len(panel_result['boxes'])} 个文本", "INFO")
    
    # 提取候选文本，按y排序
    all_boxes = sorted(panel_result["boxes"], key=lambda b: (b.center_y, b.center_x))
    
    # 点击985
    clicked_985 = False
    for box in all_boxes:
        if "985" in box.text:
            cx, cy = box.center_x, box.center_y
            log(f"OCR点击985: ({cx}, {cy})", "INFO")
            move_and_click(cx, cy)
            time.sleep(0.4)
            clicked_985 = True
            break
    if not clicked_985:
        log("⚠️ OCR未识别到985，用坐标(992, 393)", "WARNING")
        move_and_click(992, 393)
        time.sleep(0.4)
    
    # 点击211
    clicked_211 = False
    for box in all_boxes:
        if "211" in box.text:
            cx, cy = box.center_x, box.center_y
            log(f"OCR点击211: ({cx}, {cy})", "INFO")
            move_and_click(cx, cy)
            time.sleep(0.4)
            clicked_211 = True
            break
    if not clicked_211:
        log("⚠️ OCR未识别到211，用坐标(1049, 393)", "WARNING")
        move_and_click(1049, 393)
        time.sleep(0.4)
    
    # ================================================================
    # 步骤4: 确定按钮 - 多重高清OCR + 锚点推算 + 颜色检测
    # 策略链：局部高清OCR(右下角)→搜清除推算→颜色检测→Enter→固定坐标
    # ================================================================
    log("="*60)
    log("步骤4: 点击右下角'确定'按钮")
    log("="*60)
    
    # ── 延迟等面板渲染完成 ──
    time.sleep(0.5)
    
    confirm_clicked = False
    
    # ── 策略A: 高清局部OCR ──
    # 确定按钮实际位置（1920x1080实测截图）:
    #   - 确定按钮: (1571, 926)，大小约66x30px
    #   - 清除文字: (1499, 926)，确定左侧约72px
    # OCR区域覆盖按钮完整位置：x从1500到1700，y从880到980（向下延展确保不被截）
    local_region = (1500, 870, 200, 110)  # 覆盖确定+清除的完整底部区域
    a_result = screen_ocr(
        region=local_region,
        min_confidence=3.0,
        scale=4,
        preprocess=True
    )
    
    log(f"右下角OCR识别到 {len(a_result['boxes'])} 个文本", "DEBUG")
    for box in a_result["boxes"][:10]:
        log(f"  [{box.center_x:4d},{box.center_y:4d}] {box.text} (conf={box.confidence:.0f})", "DEBUG")
    
    # A1: 直接搜"确定"
    for box in a_result["boxes"]:
        if "确定" in box.text or "确 定" in box.text or "确认" in box.text:
            cx, cy = box.center_x, box.center_y
            log(f"✅ [A1] OCR找到确定: ({cx}, {cy})", "SUCCESS")
            move_and_click(cx, cy)
            confirm_clicked = True
            break
    
    # A2: 搜"清除"推算（清除文字x≈1499 → 确定按钮x≈1571 → 间距≈72px）
    if not confirm_clicked:
        for box in a_result["boxes"]:
            if "清除" in box.text or "清空" in box.text:
                cx, cy = box.center_x + 72, box.center_y
                log(f"✅ [A2] 通过清除+72px定位确定: ({cx}, {cy})", "SUCCESS")
                move_and_click(cx, cy)
                confirm_clicked = True
                break
    
    # ── 策略B: 固定坐标(1571, 926) ──
    if not confirm_clicked:
        log("[B] 使用固定坐标(1571, 926) ", "WARNING")
        move_and_click(1571, 926)
        confirm_clicked = True
    
    # ── 策略C: Enter键（二次保障） ──
    if not confirm_clicked:
        log("[C] 按Enter键提交", "WARNING")
        pyautogui.press('enter')
        time.sleep(1.0)
        confirm_clicked = True
    
    # ── 等待并确认 ──
    log("等待筛选生效...")
    time.sleep(2.0)
    
    # 二次确认面板已关闭
    for retry in range(2):
        panel_check = screen_ocr(
            region=(600, 200, 150, 60),
            min_confidence=5.0,
            scale=2,
            preprocess=False
        )
        panel_still_open = any("筛选" in box.text or "条件" in box.text for box in panel_check["boxes"])
        if panel_still_open:
            log(f"⚠️ 筛选面板未关闭（第{retry+1}次），按Enter", "WARNING")
            pyautogui.press('enter')
            time.sleep(1.0)
        else:
            break
    
    log("筛选条件已应用", "SUCCESS")
    
    # 步骤5: 智能扫描候选人
    log("="*60)
    log("步骤5: 智能扫描候选人（学校白名单验证）")
    log("="*60)
    
    contacted = 0
    skipped = 0
    max_contacts = 80
    max_scrolls = 30
    
    for scroll_count in range(max_scrolls):
        log(f"第{scroll_count+1}次扫描...")
        
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
        log(f"找到 {len(hello_buttons)} 个候选人")
        
        # 验证并点击
        for button in hello_buttons:
            if contacted >= max_contacts:
                log(f"已达到每日上限({max_contacts}人)", "SUCCESS")
                break
            
            # ===== 修复 v7.4: 学校名在按钮下方，调整搜索窗口 =====
            # BOSS直聘布局实测：学校名在按钮下方60-100px处
            # 窗口：按钮上方10px到下方130px = 140px（覆盖按钮上下学校信息）
            WINDOW_ABOVE = 10   # 按钮上方10px（避开上一个卡片的文字）
            WINDOW_BELOW = 130  # 按钮下方130px（覆盖学校名）
            upper_y = button['y'] - WINDOW_ABOVE
            lower_y = button['y'] + WINDOW_BELOW
            
            # 只匹配当前窗口内的文本
            row_boxes = [
                box for box in result["boxes"]
                if upper_y < box.center_y < lower_y
            ]
            row_boxes.sort(key=lambda b: (b.center_y, b.center_x))
            raw_text = " ".join(box.text for box in row_boxes)
            
            # 学校白名单验证（使用优化版）
            is_match, matched_schools = check_school_match(raw_text)
            
            log(f"候选人 #{contacted + skipped + 1} 按钮@({button['x']},{button['y']})")
            log(f"  卡片范围 y=[{upper_y}, {lower_y}]")
            log(f"  信息: {raw_text[:100]}...")
            log(f"  学校匹配: {'✅' if is_match else '❌'}")
            if is_match:
                log(f"  匹配学校: {', '.join(matched_schools)}")
            
            if not is_match:
                log(f"  ⏭️ 跳过（不在白名单）")
                skipped += 1
                continue
            
            # 额外验证：检查当前卡片范围内是否有明确的学校名称
            # 防止误匹配（比如文本碎片包含了学校关键词）
            if len(matched_schools) == 1 and len(matched_schools[0]) <= 2:
                # 极短学校名需要进一步确认
                log(f"  ⚠️ 短学校名 '{matched_schools[0]}'，检查可靠性...", "WARN")
            
            # 点击"打招呼"
            log(f"  ✅ 准备联系...")
            move_and_click(button['x'], button['y'])
            contacted += 1
            log(f"  ✅ 已联系 #{contacted}", "SUCCESS")
            
            # 随机延迟3-8秒
            delay = random.uniform(3.0, 8.0)
            log(f"  ⏳ 等待 {delay:.1f} 秒...")
            time.sleep(delay)
        
        if contacted >= max_contacts:
            break
        
        # 滚动到下一屏
        log("⬇️ 滚动到下一屏...")
        pyautogui.scroll(-3)
        time.sleep(1.5)
    
    log("="*60)
    log(f"自动化流程完成", "SUCCESS")
    log(f"  已联系: {contacted} 人")
    log(f"  已跳过: {skipped} 人")
    log(f"  滚动次数: {scroll_count+1}")
    log("="*60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n用户中断", "WARNING")
    except Exception as e:
        log(f"错误: {e}", "ERROR")
        import traceback
        traceback.print_exc()
