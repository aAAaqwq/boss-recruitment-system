"""测试3.1主动筛选沟通流程"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workflows import workflow_3_1_auto_contact


def test_dry_run():
    """测试Dry Run模式"""
    print("=" * 60)
    print("测试 3.1 主动筛选沟通流程 (Dry Run)")
    print("=" * 60)
    
    result = workflow_3_1_auto_contact(
        daily_cap=80,
        school_whitelist=[
            "清华大学", "北京大学", "浙江大学", "复旦大学",
            "上海交通大学", "华中科技大学", "武汉大学", "中山大学"
        ],
        min_degree="本科",
        min_years=3,
        dry_run=True  # Dry Run模式
    )
    
    print(f"\n状态: {result['status']}")
    
    if result['status'] == 'preview':
        print(f"将联系 {result['total']} 位候选人:")
        for i, candidate in enumerate(result['candidates'][:10]):
            print(f"  {i+1}. {candidate.get('name', '未知')} - {candidate.get('school', '未知')} - {candidate.get('degree', '未知')} - {candidate.get('years', 0)}年")
        
        if result['total'] > 10:
            print(f"  ... 还有 {result['total'] - 10} 位")
        
        print(f"\n剩余额度: {result['remaining']} 人")
        
        # 询问是否真执行
        confirm = input("\n确认真正执行？(y/n): ")
        if confirm.lower() == 'y':
            test_real_run()
    else:
        print(f"原因: {result.get('reason', 'unknown')}")


def test_real_run():
    """测试真实执行"""
    print("\n" + "=" * 60)
    print("开始真实执行...")
    print("=" * 60)
    
    result = workflow_3_1_auto_contact(
        daily_cap=80,
        school_whitelist=[
            "清华大学", "北京大学", "浙江大学", "复旦大学",
            "上海交通大学", "华中科技大学", "武汉大学", "中山大学"
        ],
        min_degree="本科",
        min_years=3,
        dry_run=False  # 真实执行
    )
    
    print(f"\n状态: {result['status']}")
    
    if result['status'] == 'completed':
        print(f"成功联系 {result['total']} 位候选人")
        print(f"剩余额度: {result['remaining']} 人")
    else:
        print(f"原因: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    test_dry_run()
