"""OCR和图像识别模块 v3.0
核心升级: macOS Vision框架替代Tesseract，中文识别率从~50%提升到~95%
兼容: 保留Tesseract作为fallback"""
import subprocess
import json
import re
import time
import ctypes
from PIL import Image, ImageGrab, ImageEnhance
import cv2
import numpy as np
from typing import List, Dict, Tuple, Optional

# macOS 25 截图兼容：需要屏幕录制权限
try:
    import Quartz
except ImportError:
    Quartz = None


class OcrTextBox:
    """OCR识别的文本框"""
    def __init__(self, text: str, confidence: float, x: int, y: int, width: int, height: int):
        self.text = text
        self.confidence = confidence
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.center_x = x + width // 2
        self.center_y = y + height // 2


def _vision_ocr(image: Image.Image, region_offset: Tuple[int, int] = (0, 0)) -> List[OcrTextBox]:
    """
    macOS原生Vision OCR - 中文识别率~95%，秒杀Tesseract
    
    通过Python调用osascript执行Swift代码，使用VNRecognizeTextRequest
    """
    import tempfile, os
    
    # 保存临时文件
    tmp_path = tempfile.mktemp(suffix='.png')
    image.save(tmp_path, 'PNG')
    
    # Swift脚本调用Vision框架
    swift_code = '''
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else { print("[]"); exit(0) }
let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("[]")
    exit(0)
}

let request = VNRecognizeTextRequest { request, error in
    guard let observations = request.results as? [VNRecognizedTextObservation] else {
        print("[]")
        return
    }
    var results: [[String]] = []
    for obs in observations {
        guard let candidate = obs.topCandidates(1).first else { continue }
        let bbox = obs.boundingBox
        // bbox是归一化坐标 (0-1)，原点在左下角
        let x = Int(bbox.origin.x * CGFloat(cgImage.width))
        let y = Int((1 - bbox.origin.y - bbox.height) * CGFloat(cgImage.height))
        let w = Int(bbox.width * CGFloat(cgImage.width))
        let h = Int(bbox.height * CGFloat(cgImage.height))
        let conf = Int(candidate.confidence * 100)
        results.append(["\\(candidate.string)", "\\(x)", "\\(y)", "\\(w)", "\\(h)", "\\(conf)"])
    }
    // JSON输出
    if let data = try? JSONSerialization.data(withJSONObject: results, options: []),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    } else {
        print("[]")
    }
}
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try? handler.perform([request])
'''
    
    try:
        result = subprocess.run(
            ['swift', '-e', swift_code, tmp_path],
            capture_output=True, text=True, timeout=15
        )
        try:
            os.unlink(tmp_path)
        except:
            pass
        
        output = result.stdout.strip()
        if not output:
            return []
        
        # 找最后一行JSON
        json_line = None
        for line in reversed(output.split('\n')):
            line = line.strip()
            if line.startswith('['):
                json_line = line
                break
        if not json_line or json_line == '[]':
            return []
        
        boxes = []
        data = json.loads(json_line)
        ox, oy = region_offset
        for item in data:
            if len(item) < 6:
                continue
            text = item[0]
            x = int(item[1]) + ox
            y = int(item[2]) + oy
            w = int(item[3])
            h = int(item[4])
            conf = float(item[5])
            boxes.append(OcrTextBox(text=text, confidence=conf, x=x, y=y, width=w, height=h))
        return boxes
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except:
            pass
        return []


def _tesseract_ocr(image: Image.Image, region_offset: Tuple[int, int] = (0, 0), 
                   lang: str = "chi_sim+eng", min_confidence: float = 20.0) -> List[OcrTextBox]:
    """Tesseract fallback"""
    import pytesseract
    scale = 3
    scaled = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
    gray = scaled.convert('L')
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(2.0)
    
    data = pytesseract.image_to_data(gray, lang=lang, output_type=pytesseract.Output.DICT)
    
    boxes = []
    ox, oy = region_offset
    for i in range(len(data['text'])):
        text = data['text'][i].strip()
        conf = float(data['conf'][i])
        if text and conf >= min_confidence:
            boxes.append(OcrTextBox(
                text=text, confidence=conf,
                x=data['left'][i] // scale + ox,
                y=data['top'][i] // scale + oy,
                width=data['width'][i] // scale,
                height=data['height'][i] // scale
            ))
    return boxes


def _capture_region(x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
    """
    截图指定区域 - macOS 25兼容版
    用 CGDisplayCreateImage + Cocoa NSBitmapImageRep 替代 ImageGrab.grab()
    
    注意：需要屏幕录制权限（系统设置→隐私→屏幕录制→Terminal.app）
    """
    try:
        display_id = Quartz.CGMainDisplayID()
        cg_img = Quartz.CGDisplayCreateImage(display_id)
        if cg_img is None:
            raise RuntimeError("CGDisplayCreateImage returned None")
        
        # 通过 Cocoa 转 PNG
        import Cocoa
        import os, tempfile
        
        img_ns = Cocoa.NSImage.alloc().initWithCGImage_(cg_img)
        rep = Cocoa.NSBitmapImageRep.alloc().initWithData_(img_ns.TIFFRepresentation())
        png_data = rep.representationUsingType_properties_(Cocoa.NSPNGFileType, None)
        
        tmp = '/tmp/boss_capture_temp.png'
        saved = png_data.writeToFile_atomically_(tmp, True)
        
        if not saved or not os.path.exists(tmp):
            raise RuntimeError("PNG save failed")
        
        pil_img = Image.open(tmp)
        
        # 裁剪
        if width > 0 and height > 0:
            pil_img = pil_img.crop((x, y, x + width, y + height))
        
        return pil_img.convert("RGB")
        
    except Exception as e:
        print(f"[截图失败] {e}，回退到 ImageGrab")
        try:
            return ImageGrab.grab(bbox=(x, y, x + width, y + height))
        except Exception:
            return None


def screen_ocr(
    region: Tuple[int, int, int, int],
    lang: str = "chi_sim+eng",
    min_confidence: float = 20.0,
    scale: int = 3,
    preprocess: bool = True
) -> Dict:
    """
    屏幕OCR识别 v4.0
    优先使用macOS Vision（高精度），Tesseract兜底
    macOS 25兼容：用 CGDisplayCreateImage 代替 ImageGrab.grab()
    """
    x, y, width, height = region
    
    # 用兼容的截图方式
    screenshot = _capture_region(x, y, width, height)
    
    if screenshot is None:
        return {"boxes": [], "full_text": "", "screenshot": None, "engine": "failed"}
    
    # 策略1: macOS Vision OCR（推荐）
    boxes = _vision_ocr(screenshot, region_offset=(x, y))
    
    if boxes:
        full_text = " ".join(b.text for b in boxes if b.confidence >= min_confidence)
        return {
            "boxes": boxes,
            "full_text": full_text,
            "screenshot": screenshot,
            "engine": "vision"
        }
    
    # 策略2: Tesseract fallback
    boxes = _tesseract_ocr(screenshot, region_offset=(x, y), min_confidence=min_confidence)
    full_text = " ".join(b.text for b in boxes)
    return {
        "boxes": boxes,
        "full_text": full_text,
        "screenshot": screenshot,
        "engine": "tesseract"
    }


def find_confirm_button(region: Tuple[int, int, int, int]) -> Optional[Tuple[int, int]]:
    """
    确定按钮查找器 v8
    颜色检测定位最右侧的绿色/蓝色按钮
    
    BOSS直聘 1920x1080:
    - 确定: x≈1640-1680, y≈865-895 (最右侧)
    - 清除: x≈1550-1600, y≈865-895 (确定左侧约55px)
    
    策略：颜色检测 → 取最右侧的绿色按钮
    """
    x, y, width, height = region
    
    screenshot = _capture_region(x, y, width, height)
    if screenshot is None:
        return None
    
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w = img.shape[:2]
    
    # 青绿色/蓝色范围（BOSS直聘确定+清除按钮颜色）
    green_mask = cv2.inRange(hsv, np.array([75, 60, 60]), np.array([135, 255, 220]))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # 找所有绿色按钮，取最右侧的那个（确定在最右）
    buttons = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        bx, by, bw, bh = cv2.boundingRect(cnt)
        abs_cx = x + bx + bw // 2
        abs_cy = y + by + bh // 2
        abs_right = x + bx + bw  # 右边缘
        
        if area < 3000:
            continue
        if bh < 25 or bw < 60:
            continue
        if abs_cy < y + height * 0.3:
            continue
        
        buttons.append((abs_cx, abs_cy, abs_right, area))
    
    if buttons:
        # 取最右侧的按钮
        buttons.sort(key=lambda b: -b[2])  # 按右边缘从右到左排序
        cx, cy = buttons[0][0], buttons[0][1]
        return (cx, cy)
    
    # 兜底：固定坐标 (1571, 926)
    return (1571, 926)


def find_colored_button(region, color="green"):
    """保留兼容"""
    return None

find_green_button = find_colored_button


def click_text_ocr(
    text: str,
    region: Tuple[int, int, int, int],
    min_confidence: float = 20.0,
    scale: int = 3,
    preprocess: bool = True
) -> Optional[Tuple[int, int]]:
    result = screen_ocr(region, min_confidence=min_confidence, scale=scale, preprocess=preprocess)
    for box in result["boxes"]:
        if text in box.text:
            return (box.center_x, box.center_y)
    return None


def match_image(
    template_path: str,
    region: Tuple[int, int, int, int] = None,
    confidence: float = 0.8
) -> Optional[Tuple[int, int]]:
    template = cv2.imread(template_path)
    if template is None:
        return None
    if region:
        x, y, width, height = region
        screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
    else:
        screenshot = ImageGrab.grab()
        x, y = 0, 0
    screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    result = cv2.matchTemplate(screenshot_cv, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    if max_val >= confidence:
        center_x = max_loc[0] + template.shape[1] // 2 + x
        center_y = max_loc[1] + template.shape[0] // 2 + y
        return (center_x, center_y)
    return None
