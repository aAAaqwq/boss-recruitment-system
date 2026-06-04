"""坐标标注工具"""
import sys
from pathlib import Path
import time
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.screen import get_mouse_position


def main():
    """坐标标注工具"""
    print("=" * 60)
    print("BOSS直聘屏幕坐标标注工具")
    print("=" * 60)
    print("\n请按照提示操作：")
    print("1. 打开BOSS直聘聊天页面")
    print("2. 将鼠标移动到目标位置")
    print("3. 按Enter记录坐标")
    print("4. 按Ctrl+C退出")
    print("\n" + "=" * 60 + "\n")
    
    coordinates = {}
    
    regions = [
        ("左侧导航栏左上角", "left_sidebar_top_left"),
        ("左侧导航栏右下角", "left_sidebar_bottom_right"),
        ("候选人卡片区域左上角", "candidate_card_top_left"),
        ("候选人卡片区域右下角", "candidate_card_bottom_right"),
        ("聊天内容区域左上角", "chat_content_top_left"),
        ("聊天内容区域右下角", "chat_content_bottom_right"),
        ("聊天输入框", "chat_input_box"),
        ("发送按钮", "send_button"),
    ]
    
    try:
        for desc, key in regions:
            input(f"\n请将鼠标移动到【{desc}】，然后按Enter...")
            time.sleep(0.5)
            x, y = get_mouse_position()
            coordinates[key] = {"x": x, "y": y}
            print(f"✅ 已记录: ({x}, {y})")
        
        # 计算区域
        profile = {
            "resolution": "custom",
            "regions": {
                "left_sidebar": {
                    "x": coordinates["left_sidebar_top_left"]["x"],
                    "y": coordinates["left_sidebar_top_left"]["y"],
                    "width": coordinates["left_sidebar_bottom_right"]["x"] - coordinates["left_sidebar_top_left"]["x"],
                    "height": coordinates["left_sidebar_bottom_right"]["y"] - coordinates["left_sidebar_top_left"]["y"]
                },
                "candidate_card_area": {
                    "x": coordinates["candidate_card_top_left"]["x"],
                    "y": coordinates["candidate_card_top_left"]["y"],
                    "width": coordinates["candidate_card_bottom_right"]["x"] - coordinates["candidate_card_top_left"]["x"],
                    "height": coordinates["candidate_card_bottom_right"]["y"] - coordinates["candidate_card_top_left"]["y"]
                },
                "chat_content_area": {
                    "x": coordinates["chat_content_top_left"]["x"],
                    "y": coordinates["chat_content_top_left"]["y"],
                    "width": coordinates["chat_content_bottom_right"]["x"] - coordinates["chat_content_top_left"]["x"],
                    "height": coordinates["chat_content_bottom_right"]["y"] - coordinates["chat_content_top_left"]["y"]
                },
                "chat_input_box": coordinates["chat_input_box"],
                "send_button": coordinates["send_button"]
            }
        }
        
        # 保存到配置文件
        config_path = Path(__file__).parent.parent / "config" / "screen_profile.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
        
        print("\n" + "=" * 60)
        print("✅ 坐标配置已保存到: config/screen_profile.json")
        print("=" * 60)
        print("\n配置内容:")
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        
    except KeyboardInterrupt:
        print("\n\n已取消")


if __name__ == "__main__":
    main()
