"""OCR和图像识别模块 - Linux Docker版
使用 Tesseract OCR + PIL 截图，兼容 Docker Linux 环境"""
import subprocess
import json
import re
import time
from PIL import Image, ImageGrab, ImageEnhance
import cv2
import numpy as np
from typing import List, Dict, Tuple, Optional


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


def _tesseract_ocr(image: Image.Image, region_offset: Tuple[int, int] = (0, 0),
                   lang: str = "chi_sim+eng", min_confidence: float = 20.0) -> List[OcrTextBox]:
    """Tesseract OCR - Linux兼容版本"""
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
    截图指定区域 - Linux版本
    使用 Pillow ImageGrab 配合 X11
    """
    try:
        # Linux 下 ImageGrab 需要 X11 服务器 (DISPLAY=:1)
        screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        return screenshot.convert("RGB")
    except Exception as e:
        print(f"[截图失败] {e}")
        return None


def screen_ocr(
    region: Tuple[int, int, int, int],
    lang: str = "chi_sim+eng",
    min_confidence: float = 20.0,
    scale: int = 3,
    preprocess: bool = True
) -> Dict:
    """
    屏幕OCR识别 - Linux版本
    使用 Tesseract OCR
    """
    x, y, width, height = region

    screenshot = _capture_region(x, y, width, height)

    if screenshot is None:
        return {"boxes": [], "full_text": "", "screenshot": None, "engine": "failed"}

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
    确定按钮查找器 - 颜色检测定位最右侧的绿色/蓝色按钮
    """
    x, y, width, height = region

    screenshot = _capture_region(x, y, width, height)
    if screenshot is None:
        return None

    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w = img.shape[:2]

    # 青绿色/蓝色范围
    green_mask = cv2.inRange(hsv, np.array([75, 60, 60]), np.array([135, 255, 220]))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    buttons = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        bx, by, bw, bh = cv2.boundingRect(cnt)
        abs_cx = x + bx + bw // 2
        abs_cy = y + by + bh // 2
        abs_right = x + bx + bw

        if area < 3000:
            continue
        if bh < 25 or bw < 60:
            continue
        if abs_cy < y + height * 0.3:
            continue

        buttons.append((abs_cx, abs_cy, abs_right, area))

    if buttons:
        buttons.sort(key=lambda b: -b[2])
        cx, cy = buttons[0][0], buttons[0][1]
        return (cx, cy)

    # 兜底  (1571, 926)
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
