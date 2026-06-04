#!/usr/bin/env python3
"""
学校白名单匹配测试脚本
测试各种OCR识别结果的匹配准确性
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def check_candidate_school_old(text: str) -> bool:
    """原始版本（用于对比）"""
    text_no_space = text.replace(" ", "").replace("　", "")
    
    for school in SCHOOL_WHITELIST:
        school_no_space = school.replace(" ", "")
        if school_no_space in text_no_space:
            if school == "华科" and "西安电子科技" in text_no_space:
                continue
            if school == "中山" and "中山大学" not in text_no_space:
                continue
            return True
    
    return False


def check_candidate_school_optimized(text: str) -> tuple:
    """
    优化版本：更严格的匹配逻辑
    返回: (是否匹配, 匹配的学校名称, 匹配原因)
    """
    # 1. 清理文本：去除所有空格、标点、特殊字符
    import re
    text_clean = re.sub(r'[\s\u3000\-_·•]', '', text)  # 去除空格、全角空格、连字符等
    text_clean = text_clean.lower()  # 转小写（用于英文匹配）
    
    # 2. 黑名单检查：如果包含普通学校关键词，直接拒绝
    for keyword in SCHOOL_BLACKLIST_KEYWORDS:
        if keyword in text_clean:
            return (False, None, f"黑名单关键词: {keyword}")
    
    # 3. 白名单匹配
    matched_schools = []
    
    for school in SCHOOL_WHITELIST:
        school_clean = re.sub(r'[\s\u3000\-_·•]', '', school).lower()
        
        # 3.1 完全匹配（最高优先级）
        if school_clean == text_clean:
            return (True, school, "完全匹配")
        
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
                            matched_schools.append((school, "短名称+大学"))
                        else:
                            continue  # 跳过，可能是误匹配
                    else:
                        continue
                else:
                    matched_schools.append((school, "独立短名称"))
            else:
                # 长名称（>3个字符）直接匹配
                matched_schools.append((school, "长名称匹配"))
    
    # 4. 返回结果
    if matched_schools:
        # 优先返回最长的匹配（更精确）
        best_match = max(matched_schools, key=lambda x: len(x[0]))
        return (True, best_match[0], best_match[1])
    
    return (False, None, "未匹配")


def run_tests():
    """运行测试用例"""
    test_cases = [
        # (输入文本, 期望结果, 描述)
        ("中 山大 学", True, "OCR空格：中山大学"),
        ("华南 理工", True, "OCR空格：华南理工"),
        ("广州职业技术学院", False, "普通学校：广州职业"),
        ("重庆人文科技学院", False, "普通学校：重庆人文"),
        ("新 加坡国立", True, "OCR空格：新加坡国立"),
        ("清华大学", True, "完整名称：清华大学"),
        ("清 华", True, "OCR空格：清华"),
        ("北 京 大 学", True, "多空格：北京大学"),
        ("MIT", True, "英文简称：MIT"),
        ("Stanford University", True, "英文全称：Stanford"),
        ("中山职业技术学院", False, "误匹配：中山职业（包含中山但是职业学校）"),
        ("华南农业大学", False, "非白名单：华南农业"),
        ("西安电子科技大学", False, "非白名单：西安电子科技"),
        ("华中科技大学", True, "完整名称：华中科技大学"),
        ("华科", True, "短名称：华科"),
        ("浙江大学 本科 3年", True, "包含其他信息：浙江大学"),
        ("张三 | 中山大学 | 本科 | 5年", True, "简历格式：中山大学"),
        ("深圳职业技术学院", False, "普通学校：深圳职业"),
        ("上海交通大学", True, "完整名称：上海交通大学"),
        ("上交", True, "短名称：上交"),
        ("UC Berkeley", True, "英文：UC Berkeley"),
        ("伯克利", True, "中文：伯克利"),
        ("南京大学", True, "完整名称：南京大学"),
        ("南大", True, "短名称：南大"),
        ("中南大学", False, "非白名单：中南大学（虽然包含'南大'但不应匹配）"),
        ("港大", True, "短名称：港大"),
        ("香港大学", True, "完整名称：香港大学"),
    ]
    
    print("="*80)
    print("学校白名单匹配测试")
    print("="*80)
    
    print(f"\n📋 白名单学校数量: {len(SCHOOL_WHITELIST)}")
    print(f"📋 黑名单关键词数量: {len(SCHOOL_BLACKLIST_KEYWORDS)}")
    
    print("\n" + "="*80)
    print("测试结果对比（旧版 vs 优化版）")
    print("="*80)
    
    old_correct = 0
    new_correct = 0
    total = len(test_cases)
    
    for i, (text, expected, desc) in enumerate(test_cases, 1):
        old_result = check_candidate_school_old(text)
        new_result, matched_school, reason = check_candidate_school_optimized(text)
        
        old_status = "✅" if old_result == expected else "❌"
        new_status = "✅" if new_result == expected else "❌"
        
        if old_result == expected:
            old_correct += 1
        if new_result == expected:
            new_correct += 1
        
        print(f"\n{i:2d}. {desc}")
        print(f"    输入: '{text}'")
        print(f"    期望: {'匹配' if expected else '不匹配'}")
        print(f"    旧版: {old_status} {'匹配' if old_result else '不匹配'}")
        print(f"    优化: {new_status} {'匹配' if new_result else '不匹配'} | 学校: {matched_school} | 原因: {reason}")
    
    print("\n" + "="*80)
    print("测试总结")
    print("="*80)
    print(f"总测试用例: {total}")
    print(f"旧版正确率: {old_correct}/{total} ({old_correct/total*100:.1f}%)")
    print(f"优化版正确率: {new_correct}/{total} ({new_correct/total*100:.1f}%)")
    print(f"提升: {new_correct - old_correct} 个用例 ({(new_correct - old_correct)/total*100:.1f}%)")
    
    if new_correct == total:
        print("\n🎉 优化版通过所有测试用例！")
    else:
        print(f"\n⚠️ 优化版仍有 {total - new_correct} 个用例失败")
        print("\n失败用例：")
        for i, (text, expected, desc) in enumerate(test_cases, 1):
            new_result, _, _ = check_candidate_school_optimized(text)
            if new_result != expected:
                print(f"  - {desc}: '{text}' (期望: {'匹配' if expected else '不匹配'}, 实际: {'匹配' if new_result else '不匹配'})")


if __name__ == "__main__":
    run_tests()
