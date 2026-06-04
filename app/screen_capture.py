#!/usr/bin/env python3
"""
screen_capture.py — macOS 26 原生截图模块 v1.0
================================================
解决macOS 25+ CGDisplayCreateImage废弃、TCC拦截、HDR色彩空间三大问题。

方案:
  - CGDisplayCreateImage (Python进程内调用，继承Terminal TCC权限)
  - NSBitmapImageRep → numpy 直接读像素 (不经过PIL)
  - sRGB转换 → Vision OCR (HDR → sRGB兼容)

兼容: macOS 26.2 + Python 3.9 + PyObjC 11.1 (Quartz + Cocoa + Vision)
"""
import Quartz
import Cocoa
import Vision
import numpy as np
import threading
import time
import os, json
from typing import List, Optional, Tuple


# ============================================================
# 一键截图 + 像素数组
# ============================================================

class ScreenShot:
    """屏幕截图，支持像素读取和裁剪"""
    
    def __init__(self, cg_image=None, x_offset: int = 0, y_offset: int = 0):
        """
        创建截图对象。
        可传入裁剪后的CGImage，或直接从主显示器捕获。
        """
        if cg_image is None:
            self._capture_full()
        else:
            self.cg_image = cg_image
        
        self.x_offset = x_offset
        self.y_offset = y_offset
        self._load_pixels()
    
    def _capture_full(self):
        """捕获主显示器全屏"""
        display_id = Quartz.CGMainDisplayID()
        self.cg_image = Quartz.CGDisplayCreateImage(display_id)
        if not self.cg_image:
            raise RuntimeError("❌ CGDisplayCreateImage 失败 — 检查TCC屏幕录制权限")
    
    def _load_pixels(self):
        """将CGImage解码为numpy数组"""
        ns_img = Cocoa.NSImage.alloc().initWithCGImage_(self.cg_image)
        tiff = ns_img.TIFFRepresentation()
        bitmap = Cocoa.NSBitmapImageRep.alloc().initWithData_(tiff)
        
        self.width = bitmap.pixelsWide()
        self.height = bitmap.pixelsHigh()
        
        buf = bytes(bitmap.bitmapData()[:self.width * self.height * 4])
        # BGRA格式
        self.bgra = np.frombuffer(buf, dtype=np.uint8).reshape(self.height, self.width, 4)
    
    def pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        """获取(x,y)的RGB颜色值（窗口坐标）"""
        sx = x - self.x_offset
        sy = y - self.y_offset
        if 0 <= sy < self.height and 0 <= sx < self.width:
            b, g, r, a = self.bgra[sy, sx]
            return (r, g, b)
        return (0, 0, 0)
    
    def is_white(self, x: int, y: int, threshold: int = 200) -> bool:
        r, g, b = self.pixel(x, y)
        return r > threshold and g > threshold and b > threshold
    
    def is_green(self, x: int, y: int, g_threshold: int = 180) -> bool:
        """检测确认按钮绿色"""
        r, g, b = self.pixel(x, y)
        return g > g_threshold and g > r and g > b
    
    def region_brightness(self, x: int, y: int, w: int, h: int) -> float:
        """计算区域的亮度均值 (0-255)"""
        sx = x - self.x_offset
        sy = y - self.y_offset
        if sx < 0 or sy < 0 or sx + w > self.width or sy + h > self.height:
            return 0
        region = self.bgra[sy:sy+h, sx:sx+w]
        # BGRA -> luminance
        lum = 0.299 * region[:,:,2] + 0.587 * region[:,:,1] + 0.114 * region[:,:,0]
        return float(lum.mean())
    
    def crop(self, x: int, y: int, w: int, h: int) -> 'ScreenShot':
        """裁剪到子区域"""
        from PIL import Image
        import io
        
        ns_img = Cocoa.NSImage.alloc().initWithCGImage_(self.cg_image)
        tiff = ns_img.TIFFRepresentation()
        bitmap = Cocoa.NSBitmapImageRep.alloc().initWithData_(tiff)
        
        png_data = bitmap.representationUsingType_properties_(Cocoa.NSPNGFileType, None)
        png_bytes = bytes(png_data)
        pil_img = Image.open(io.BytesIO(png_bytes))
        
        # 注意y坐标翻转
        cropped = pil_img.crop((x, self.height - y - h, x + w, self.height - y))
        
        tmp = f"/tmp/ss_crop_{int(time.time()*1000)}.png"
        cropped.save(tmp, "PNG")
        
        ns_crop = Cocoa.NSImage.alloc().initWithContentsOfFile_(tmp)
        tiff_crop = ns_crop.TIFFRepresentation()
        cg_crop = Cocoa.NSBitmapImageRep.alloc().initWithData_(tiff_crop).CGImage()
        
        os.unlink(tmp)
        return ScreenShot(cg_crop, x_offset=self.x_offset + x, y_offset=self.y_offset + y)


# ============================================================
# Vision OCR (色彩空间兼容)
# ============================================================

class VisionOCR:
    """macOS Vision框架OCR — 修复HDR色彩空间问题"""
    
    @staticmethod
    def _to_srgb_cgimage(cg_image):
        """
        将HDR CGImage转换为sRGB CGImage（Vision OCR兼容）
        通过: CGImage → NSBitmapImageRep → PIL → sRGB PNG → NSImage → CGImage
        """
        ns_img = Cocoa.NSImage.alloc().initWithCGImage_(cg_image)
        tiff = ns_img.TIFFRepresentation()
        bitmap = Cocoa.NSBitmapImageRep.alloc().initWithData_(tiff)
        
        # 保存PNG
        png_data = bitmap.representationUsingType_properties_(Cocoa.NSPNGFileType, None)
        tmp = f"/tmp/vocr_{int(time.time()*1000)}.png"
        png_data.writeToFile_atomically_(tmp, True)
        
        # PIL读并转sRGB
        from PIL import Image
        pil = Image.open(tmp)
        if pil.mode == 'RGBA':
            rgb = Image.new('RGB', pil.size)
            rgb.paste(pil)
            pil = rgb
        elif pil.mode != 'RGB':
            pil = pil.convert('RGB')
        pil.save(tmp, "PNG", icc_profile=None)
        
        # 加载回NSImage
        ns_srgb = Cocoa.NSImage.alloc().initWithContentsOfFile_(tmp)
        tiff_srgb = ns_srgb.TIFFRepresentation()
        bitmap_srgb = Cocoa.NSBitmapImageRep.alloc().initWithData_(tiff_srgb)
        cg_srgb = bitmap_srgb.CGImage()
        
        os.unlink(tmp)
        return cg_srgb
    
    @staticmethod
    def recognize(cg_image, min_confidence: float = 0.3) -> List[dict]:
        """
        对CGImage执行Vision OCR
        
        Returns:
            [{text, confidence, x, y, width, height}, ...]
        """
        # HDR → sRGB
        cg_srgb = VisionOCR._to_srgb_cgimage(cg_image)
        
        # 获取尺寸
        ns_img = Cocoa.NSImage.alloc().initWithCGImage_(cg_srgb)
        tiff = ns_img.TIFFRepresentation()
        bitmap = Cocoa.NSBitmapImageRep.alloc().initWithData_(tiff)
        w, h = bitmap.pixelsWide(), bitmap.pixelsHigh()
        
        ocr_results = []
        sem = threading.Semaphore(0)
        
        def callback(request, error):
            observations = request.results()
            if observations:
                for obs in observations:
                    candidate = obs.topCandidates_(1)[0]
                    if not candidate:
                        continue
                    conf = candidate.confidence()
                    if conf < min_confidence:
                        continue
                    
                    text = candidate.string()
                    bbox = obs.boundingBox()
                    
                    x = int(bbox.origin.x * w)
                    y = int((1 - bbox.origin.y - bbox.size.height) * h)
                    bw = int(bbox.size.width * w)
                    bh = int(bbox.size.height * h)
                    
                    ocr_results.append({
                        "text": text,
                        "confidence": round(conf * 100, 1),
                        "x": x, "y": y,
                        "width": bw, "height": bh,
                        "cx": x + bw // 2,
                        "cy": y + bh // 2,
                    })
            sem.release()
        
        request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(callback)
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en"])
        
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_srgb, None)
        success, error = handler.performRequests_error_([request], None)
        
        sem.acquire(timeout=15)
        return ocr_results
    
    @staticmethod
    def recognize_region(x: int, y: int, w: int, h: int, min_confidence: float = 0.3) -> List[dict]:
        """截取屏幕区域并OCR"""
        ss = ScreenShot()
        cropped = ss.crop(x, y, w, h)
        return VisionOCR.recognize(cropped.cg_image, min_confidence)


# ============================================================
# 快捷工具
# ============================================================

def screenshot() -> ScreenShot:
    """快速截屏"""
    return ScreenShot()

def ocr(x: int = 0, y: int = 0, w: int = 1920, h: int = 1080, 
        min_confidence: float = 0.3) -> List[dict]:
    """快速OCR某区域"""
    return VisionOCR.recognize_region(x, y, w, h, min_confidence)

def pixel(x: int, y: int) -> Tuple[int, int, int]:
    """读取某像素颜色（替代pyautogui.pixel）"""
    ss = ScreenShot()
    return ss.pixel(x, y)


# ============================================================
# 模块自测
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🧪 screen_capture.py 模块自测")
    print("=" * 60)
    
    # 1. 截全屏
    print("\n1️⃣  全屏截图...")
    ss = screenshot()
    print(f"   尺寸: {ss.width}x{ss.height}")
    
    # 2. 像素读取
    print("\n2️⃣  像素读取:")
    for label in ["(50,50)", "中央(960,540)", "Dock(500,1050)"]:
        px, py = 50, 50
        if label == "中央(960,540)": px, py = 960, 540
        elif label == "Dock(500,1050)": px, py = 500, 1050
        r, g, b = ss.pixel(px, py)
        print(f"   {label}: RGB=({r},{g},{b})")
    
    # 3. Vision OCR
    print("\n3️⃣  Vision OCR (全屏, sRGB转换):")
    results = VisionOCR.recognize(ss.cg_image)
    print(f"   识别到 {len(results)} 个文字:")
    for r in sorted(results, key=lambda x: (x['y'], x['x']))[:30]:
        print(f"   [{r['confidence']:5.1f}%] ({r['x']:4d},{r['y']:4d}) {r['width']}x{r['height']} → {r['text']}")
    
    print("\n✅ 模块正常")
