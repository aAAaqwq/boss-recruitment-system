"""测试3.3智能聊天Bot流程"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workflows import workflow_3_3_chat_bot


def test_chat_bot():
    """测试聊天Bot"""
    print("=" * 60)
    print("测试 3.3 智能聊天Bot流程")
    print("=" * 60)
    
    # 输入候选人信息
    boss_id = input("\n请输入候选人ID (例如: candidate_001): ").strip()
    if not boss_id:
        boss_id = "test_candidate_001"
    
    candidate_name = input("请输入候选人姓名 (例如: 张三): ").strip()
    if not candidate_name:
        candidate_name = "测试候选人"
    
    print(f"\n候选人: {candidate_name} ({boss_id})")
    print("请确保已打开BOSS直聘聊天页面，并切换到该候选人的聊天窗口")
    input("准备好后按Enter继续...")
    
    # Dry Run预览
    print("\n正在生成回复...")
    result = workflow_3_3_chat_bot(
        boss_id=boss_id,
        candidate_name=candidate_name,
        chat_region=(420, 140, 560, 350),
        auto_send=False,
        dry_run=True
    )
    
    print(f"\n状态: {result['status']}")
    
    if result['status'] == 'preview':
        print(f"当前轮次: {result['round_id']} (第{result['round_index']+1}轮)")
        print(f"候选人消息: {result['screen_text'][:100]}...")
        print(f"\n草稿回复:\n{result['draft_reply']}")
        
        # 询问是否发送
        confirm = input("\n确认发送？(y/n): ")
        if confirm.lower() == 'y':
            print("\n正在发送...")
            result = workflow_3_3_chat_bot(
                boss_id=boss_id,
                candidate_name=candidate_name,
                chat_region=(420, 140, 560, 350),
                auto_send=True,
                dry_run=False
            )
            
            if result['status'] == 'success' and result['sent']:
                print("✅ 发送成功！")
                print(f"已完成 {result['round_index']} 轮对话")
                print(f"今日已发 {result['rounds_sent_today']} 轮")
            else:
                print(f"❌ 发送失败: {result.get('reason', 'unknown')}")
    
    elif result['status'] == 'skipped':
        print(f"跳过原因: {result['reason']}")
    
    elif result['status'] == 'blocked':
        print(f"阻塞原因: {result['reason']}")
        if 'rounds_sent_today' in result:
            print(f"今日已发 {result['rounds_sent_today']} 轮")
    
    elif result['status'] == 'completed':
        print("所有对话轮次已完成！")


if __name__ == "__main__":
    test_chat_bot()
