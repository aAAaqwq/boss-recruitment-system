#!/usr/bin/env python3
"""完整自动化流程 - 筛选并打招呼"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workflows import workflow_3_1_auto_contact

print("=" * 60)
print("BOSS招聘自动化 - 完整流程")
print("=" * 60)

# 配置
school_whitelist = [
    "清华大学", "北京大学", "浙江大学", "复旦大学",
    "上海交通大学", "华中科技大学", "武汉大学", "中山大学",
    "南京大学", "哈尔滨工业大学", "西安交通大学", "北京航空航天大学"
]

print("\n配置:")
print(f"  学校白名单: {len(school_whitelist)}所")
print(f"  最低学历: 本科")
print(f"  最低年限: 3年")
print(f"  每日上限: 80人")

# 第一步：Dry Run预览
print("\n" + "=" * 60)
print("第一步: Dry Run预览")
print("=" * 60)

result = workflow_3_1_auto_contact(
    daily_cap=80,
    school_whitelist=school_whitelist,
    min_degree="本科",
    min_years=3,
    dry_run=True
)

print(f"\n状态: {result['status']}")

if result['status'] == 'preview':
    print(f"发现 {result['total']} 位符合条件的候选人:")
    for i, candidate in enumerate(result['candidates'][:10], 1):
        print(f"  {i}. {candidate.get('name', '未知')} - {candidate.get('school', '未知')} - {candidate.get('degree', '未知')} - {candidate.get('years', 0)}年")
    
    if result['total'] > 10:
        print(f"  ... 还有 {result['total'] - 10} 位")
    
    print(f"\n剩余额度: {result['remaining']} 人")
    
    # 第二步：人工确认
    print("\n" + "=" * 60)
    print("第二步: 人工确认")
    print("=" * 60)
    
    confirm = input("\n确认执行自动打招呼？(y/n): ")
    
    if confirm.lower() == 'y':
        print("\n" + "=" * 60)
        print("第三步: 执行自动打招呼")
        print("=" * 60)
        
        # 真实执行
        result = workflow_3_1_auto_contact(
            daily_cap=80,
            school_whitelist=school_whitelist,
            min_degree="本科",
            min_years=3,
            dry_run=False
        )
        
        print(f"\n状态: {result['status']}")
        
        if result['status'] == 'completed':
            print(f"✅ 成功联系 {result['total']} 位候选人")
            print(f"剩余额度: {result['remaining']} 人")
            
            print("\n已联系的候选人:")
            for i, candidate in enumerate(result['contacted'], 1):
                print(f"  {i}. {candidate.get('name', '未知')} - {candidate.get('school', '未知')}")
        
        elif result['status'] == 'cancelled':
            print("❌ 用户取消操作")
        
        else:
            print(f"❌ 执行失败: {result.get('reason', 'unknown')}")
    
    else:
        print("\n❌ 用户取消操作")

elif result['status'] == 'blocked':
    print(f"❌ 阻塞: {result['reason']}")
    if 'contacted_today' in result:
        print(f"今日已联系: {result['contacted_today']} 人")

elif result['status'] == 'failed':
    print(f"❌ 失败: {result['reason']}")

print("\n" + "=" * 60)
print("流程结束")
print("=" * 60)
