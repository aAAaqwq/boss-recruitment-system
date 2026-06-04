#!/usr/bin/env python3
"""
确定按钮OCR识别测试脚本
测试多种参数组合，找到最稳定的识别方案
"""
import time
import sys
import os
from PIL import ImageGrab
import pyautogui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.vision import screen_ocr


def save_screenshot(region, filename):
    """保存指定区域的截图"""
    x0, y0, w, h = region
    img = ImageGrab.grab(bbox=(x0, y0, x0+w, y0+h))
    os.makedirs("test_screenshots", exist_ok=True)
    filepath = f"test_screenshots/{filename}"
    img.save(filepath)
    print(f"   💾 截图已保存: {filepath}")
    return filepath


def test_ocr_params(region, scale, min_confidence, preprocess, test_name):
    """测试单组OCR参数"""
    print(f"\n{'='*70}")
    print(f"测试 #{test_name}")
    print(f"参数: scale={scale}, min_confidence={min_confidence}, preprocess={preprocess}")
    print(f"区域: {region}")
    print('='*70)
    
    try:
        result = screen_ocr(
            region=region,
            min_confidence=min_confidence,
            scale=scale,
            preprocess=preprocess
        )
        
        print(f"识别到 {len(result['boxes'])} 个文本框:")
        
        found_confirm = False
        found_clear = False
        
        # 按Y坐标排序
        sorted_boxes = sorted(result["boxes"], key=lambda b: b.center_y)
        
        for i, box in enumerate(sorted_boxes, 1):
            marker = ""
            if "确定" in box.text:
                marker = " ✅ 【确定】"
                found_confirm = True
            elif "清除" in box.text:
                marker = " 🔵 【清除】"
                found_clear = True
            
            print(f"   {i:2d}. [{box.center_x:4d}, {box.center_y:4d}] {box.confidence:5.1f}% | {box.text}{marker}")
        
        # 评分
        score = 0
        if found_confirm:
            score = 100
            print(f"\n✅ 成功识别到'确定'按钮！")
        elif found_clear:
            score = 50
            print(f"\n🔵 识别到'清除'按钮（可推算确定位置）")
        else:
            score = 0
            print(f"\n❌ 未识别到'确定'或'清除'")
        
        return {
            'test_name': test_name,
            'scale': scale,
            'min_confidence': min_confidence,
            'preprocess': preprocess,
            'region': region,
            'found_confirm': found_confirm,
            'found_clear': found_clear,
            'score': score,
            'box_count': len(result['boxes'])
        }
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return {
            'test_name': test_name,
            'scale': scale,
            'min_confidence': min_confidence,
            'preprocess': preprocess,
            'region': region,
            'found_confirm': False,
            'found_clear': False,
            'score': 0,
            'box_count': 0,
            'error': str(e)
        }


def main():
    print("\n" + "="*70)
    print("确定按钮OCR识别测试 - 多参数组合测试")
    print("="*70)
    
    # 获取屏幕尺寸
    screen_width, screen_height = pyautogui.size()
    print(f"\n📐 屏幕尺寸: {screen_width}x{screen_height}")
    
    # 保存当前屏幕右下角截图
    base_region = (screen_width-400, screen_height-150, 400, 150)
    print(f"\n📸 保存基准截图...")
    save_screenshot(base_region, "base_region.png")
    
    # 定义测试参数组合
    test_configs = []
    test_id = 1
    
    # 测试1: 不同scale值（保持其他参数不变）
    print("\n" + "="*70)
    print("测试组1: 不同scale值")
    print("="*70)
    for scale in [2, 3, 4, 5, 6]:
        test_configs.append({
            'test_name': f"T{test_id:02d}_scale{scale}",
            'region': base_region,
            'scale': scale,
            'min_confidence': 5.0,
            'preprocess': True
        })
        test_id += 1
    
    # 测试2: 不同min_confidence值
    print("\n" + "="*70)
    print("测试组2: 不同min_confidence值")
    print("="*70)
    for conf in [1.0, 3.0, 5.0, 8.0, 10.0, 15.0]:
        test_configs.append({
            'test_name': f"T{test_id:02d}_conf{conf}",
            'region': base_region,
            'scale': 3,
            'min_confidence': conf,
            'preprocess': True
        })
        test_id += 1
    
    # 测试3: preprocess开关
    print("\n" + "="*70)
    print("测试组3: preprocess开关")
    print("="*70)
    for preprocess in [True, False]:
        test_configs.append({
            'test_name': f"T{test_id:02d}_prep{preprocess}",
            'region': base_region,
            'scale': 3,
            'min_confidence': 5.0,
            'preprocess': preprocess
        })
        test_id += 1
    
    # 测试4: 不同region范围
    print("\n" + "="*70)
    print("测试组4: 不同region范围")
    print("="*70)
    regions = [
        (screen_width-500, screen_height-200, 500, 200),  # 更大范围
        (screen_width-350, screen_height-120, 350, 120),  # 更小范围
        (screen_width-450, screen_height-180, 450, 180),  # 中等范围
        (screen_width-400, screen_height-100, 400, 100),  # 更窄高度
    ]
    for i, region in enumerate(regions, 1):
        test_configs.append({
            'test_name': f"T{test_id:02d}_region{i}",
            'region': region,
            'scale': 3,
            'min_confidence': 5.0,
            'preprocess': True
        })
        test_id += 1
    
    # 测试5: 最佳组合猜测
    print("\n" + "="*70)
    print("测试组5: 最佳组合猜测")
    print("="*70)
    best_guesses = [
        # 低scale + 低confidence + 无预处理
        {'scale': 2, 'min_confidence': 1.0, 'preprocess': False},
        # 中scale + 低confidence + 无预处理
        {'scale': 3, 'min_confidence': 3.0, 'preprocess': False},
        # 高scale + 极低confidence + 有预处理
        {'scale': 6, 'min_confidence': 1.0, 'preprocess': True},
        # 中scale + 极低confidence + 有预处理
        {'scale': 3, 'min_confidence': 1.0, 'preprocess': True},
    ]
    for i, params in enumerate(best_guesses, 1):
        test_configs.append({
            'test_name': f"T{test_id:02d}_best{i}",
            'region': base_region,
            **params
        })
        test_id += 1
    
    # 执行所有测试
    results = []
    for config in test_configs:
        result = test_ocr_params(
            region=config['region'],
            scale=config['scale'],
            min_confidence=config['min_confidence'],
            preprocess=config['preprocess'],
            test_name=config['test_name']
        )
        results.append(result)
        time.sleep(0.5)  # 避免过快
    
    # 汇总结果
    print("\n" + "="*70)
    print("测试结果汇总")
    print("="*70)
    
    # 按得分排序
    results.sort(key=lambda r: r['score'], reverse=True)
    
    print(f"\n{'排名':<6} {'测试ID':<12} {'得分':<6} {'scale':<7} {'conf':<7} {'prep':<7} {'识别结果'}")
    print("-" * 70)
    
    for i, r in enumerate(results, 1):
        status = ""
        if r['found_confirm']:
            status = "✅ 确定"
        elif r['found_clear']:
            status = "🔵 清除"
        else:
            status = "❌ 无"
        
        print(f"{i:<6} {r['test_name']:<12} {r['score']:<6} {r['scale']:<7} {r['min_confidence']:<7.1f} {str(r['preprocess']):<7} {status}")
    
    # 输出最佳配置
    print("\n" + "="*70)
    print("🏆 最佳配置推荐")
    print("="*70)
    
    best_results = [r for r in results if r['score'] == 100]
    
    if best_results:
        print(f"\n找到 {len(best_results)} 个成功识别'确定'的配置：\n")
        for i, r in enumerate(best_results[:3], 1):  # 只显示前3个
            print(f"方案 {i}:")
            print(f"  - scale: {r['scale']}")
            print(f"  - min_confidence: {r['min_confidence']}")
            print(f"  - preprocess: {r['preprocess']}")
            print(f"  - region: {r['region']}")
            print()
        
        # 推荐最稳定的配置（优先选择中等参数）
        print("💡 推荐使用方案1（最稳定）")
        
    else:
        # 如果没有100分的，找50分的
        fallback_results = [r for r in results if r['score'] == 50]
        if fallback_results:
            print(f"\n未找到直接识别'确定'的配置，但找到 {len(fallback_results)} 个可识别'清除'的配置：\n")
            for i, r in enumerate(fallback_results[:3], 1):
                print(f"方案 {i} (通过清除推算):")
                print(f"  - scale: {r['scale']}")
                print(f"  - min_confidence: {r['min_confidence']}")
                print(f"  - preprocess: {r['preprocess']}")
                print(f"  - region: {r['region']}")
                print()
            print("💡 推荐使用方案1 + 清除位置推算")
        else:
            print("\n❌ 所有配置均失败，建议：")
            print("  1. 检查筛选面板是否已打开")
            print("  2. 检查'确定'按钮是否在屏幕右下角")
            print("  3. 手动调整region参数")
    
    print("\n" + "="*70)
    print("测试完成！截图已保存到 test_screenshots/ 目录")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
