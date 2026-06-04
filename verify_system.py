"""系统验证脚本"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("BOSS招聘自动化系统 - 系统验证")
print("=" * 60)

# 1. 检查依赖
print("\n1. 检查Python依赖...")
try:
    import pyautogui
    print("  ✅ pyautogui")
except ImportError:
    print("  ❌ pyautogui 未安装")

try:
    from PIL import Image
    print("  ✅ pillow")
except ImportError:
    print("  ❌ pillow 未安装")

try:
    import pytesseract
    print("  ✅ pytesseract")
except ImportError:
    print("  ❌ pytesseract 未安装")

try:
    import cv2
    print("  ✅ opencv-python")
except ImportError:
    print("  ❌ opencv-python 未安装")

try:
    import httpx
    print("  ✅ httpx")
except ImportError:
    print("  ❌ httpx 未安装")

try:
    from dotenv import load_dotenv
    print("  ✅ python-dotenv")
except ImportError:
    print("  ❌ python-dotenv 未安装")

# 2. 检查配置文件
print("\n2. 检查配置文件...")
config_files = [
    "config/chat_bot_flow.json",
    "config/screen_profile.json",
    ".env.example"
]

for file in config_files:
    if Path(file).exists():
        print(f"  ✅ {file}")
    else:
        print(f"  ❌ {file} 不存在")

# 3. 检查数据库
print("\n3. 检查数据库...")
if Path("data/boss_recruitment.db").exists():
    print("  ✅ data/boss_recruitment.db")
    
    from app.database import Database
    with Database() as db:
        # 检查表
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in db.cursor.fetchall()]
        print(f"  ✅ 数据库表: {', '.join(tables)}")
else:
    print("  ❌ data/boss_recruitment.db 不存在")

# 4. 检查核心模块
print("\n4. 检查核心模块...")
try:
    from app.config import settings
    print("  ✅ app.config")
except Exception as e:
    print(f"  ❌ app.config: {e}")

try:
    from app.database import Database
    print("  ✅ app.database")
except Exception as e:
    print(f"  ❌ app.database: {e}")

try:
    from app.vision import screen_ocr
    print("  ✅ app.vision")
except Exception as e:
    print(f"  ❌ app.vision: {e}")

try:
    from app.screen import activate_chrome
    print("  ✅ app.screen")
except Exception as e:
    print(f"  ❌ app.screen: {e}")

try:
    from app.workflows import workflow_3_1_auto_contact, workflow_3_3_chat_bot
    print("  ✅ app.workflows")
except Exception as e:
    print(f"  ❌ app.workflows: {e}")

# 5. 检查环境变量
print("\n5. 检查环境变量...")
if Path(".env").exists():
    print("  ✅ .env 文件存在")
    from app.config import settings
    if settings.DEEPSEEK_API_KEY:
        print("  ✅ DEEPSEEK_API_KEY 已配置")
    else:
        print("  ⚠️  DEEPSEEK_API_KEY 未配置（聊天Bot将使用固定回复）")
else:
    print("  ⚠️  .env 文件不存在（请从.env.example复制）")

# 6. 测试OCR
print("\n6. 测试OCR功能...")
try:
    import pytesseract
    from PIL import Image, ImageDraw, ImageFont
    
    # 创建测试图片
    img = Image.new('RGB', (200, 50), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "测试文字 Test", fill='black')
    
    # OCR识别
    text = pytesseract.image_to_string(img, lang='chi_sim+eng')
    if text.strip():
        print(f"  ✅ OCR识别成功: {text.strip()}")
    else:
        print("  ⚠️  OCR识别为空（可能需要安装中文语言包）")
except Exception as e:
    print(f"  ❌ OCR测试失败: {e}")

# 7. 测试数据库操作
print("\n7. 测试数据库操作...")
try:
    from app.database import Database
    with Database() as db:
        # 测试插入候选人
        db.insert_candidate(
            boss_id="test_001",
            candidate_name="测试候选人",
            school="清华大学",
            degree="本科",
            years=3,
            status="discovered"
        )
        
        # 测试查询
        candidate = db.get_candidate("test_001")
        if candidate:
            print(f"  ✅ 数据库操作成功: {candidate['candidate_name']}")
        
        # 清理测试数据
        db.cursor.execute("DELETE FROM candidates WHERE boss_id = 'test_001'")
        db.conn.commit()
except Exception as e:
    print(f"  ❌ 数据库操作失败: {e}")

print("\n" + "=" * 60)
print("系统验证完成！")
print("=" * 60)
print("\n下一步:")
print("1. 如果.env未配置，请运行: cp .env.example .env")
print("2. 编辑.env，填入DEEPSEEK_API_KEY")
print("3. 运行坐标标注工具: python tools/mark_coordinates.py")
print("4. 运行测试脚本: python tests/test_workflow_3_1.py")
