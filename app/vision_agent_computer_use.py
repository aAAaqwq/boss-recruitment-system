#!/usr/bin/env python3
"""
vision_agent_computer_use.py — 纯视觉电脑操作 Agent v1.0
=========================================================
基于 specs/vision-agent-computer-use.md 五层管道架构：
1. 截图采样器 → 2. 视觉理解引擎 → 3. 决策引擎 → 4. 精度对齐 → 5. 验证闭环

不依赖DOM/API，纯像素驱动，适合Playwright/AppleScript无法操作的场景。

依赖:
  Python 3.9+, PyObjC 11.1 (Quartz, Cocoa, Vision), opencv-python, numpy, pyautogui
"""
import os, sys, time, json, subprocess, random
from typing import List, Dict, Tuple, Optional, Callable, Union
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np

import pyautogui
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True

# 截图模块
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from app.screen_capture import ScreenShot, VisionOCR

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ============================================================
# 数据结构
# ============================================================

@dataclass
class UIElement:
    """检测到的UI元素"""
    text: str
    confidence: float  # 0-100
    x: int
    y: int
    width: int
    height: int
    
    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)
    
    @property
    def area(self) -> int:
        return self.width * self.height
    
    def contains(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height


@dataclass
class LocateResult:
    """定位结果"""
    element: Optional[UIElement]
    screen_region: Optional[Tuple[int, int, int, int]]  # x, y, w, h
    confidence: float
    method: str  # "ocr", "template", "color", "edge"
    refine_center: Optional[Tuple[int, int]] = None  # OpenCV精修后的点击点


# ============================================================
# 日志
# ============================================================
def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌",
            "ACT":"🖱️","VISION":"👁️","DET":"🔍","VERIFY":"🔎"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}")


# ============================================================
# 1. 截图采样器 (Layer 1)
# ============================================================

class ScreenSampler:
    """截图采样器 — CGDisplayCreateImage原生API"""
    
    @staticmethod
    def capture(region: Optional[Tuple[int, int, int, int]] = None) -> ScreenShot:
        """
        截屏。
        Args:
            region: (x, y, w, h) 可选区域
        Returns:
            ScreenShot 对象
        """
        t0 = time.time()
        ss = ScreenShot()
        
        if region:
            x, y, w, h = region
            return ss.crop(x, y, w, h)
        
        return ss
    
    @staticmethod
    def capture_png_bytes(region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
        """截屏并返回PNG字节"""
        return bytes(ScreenShot().cg_image)  # 简化


# ============================================================
# 2. 视觉理解引擎 (Layer 2)
# ============================================================

class VisionEngine:
    """
    视觉理解引擎 — Vision OCR + OpenCV边缘检测
    """
    
    @staticmethod
    def ocr(ss: ScreenShot, min_confidence: float = 0.3) -> List[UIElement]:
        """对截图执行OCR"""
        results = VisionOCR.recognize(ss.cg_image, min_confidence)
        return [
            UIElement(
                text=r["text"],
                confidence=r["confidence"],
                x=r["x"] + ss.x_offset,
                y=r["y"] + ss.y_offset,
                width=r["width"],
                height=r["height"],
            )
            for r in results
        ]
    
    @staticmethod
    def find_text(ss: ScreenShot, text: str, fuzzy: bool = True,
                  min_confidence: float = 0.3) -> List[UIElement]:
        """
        在截图找文字
        Args:
            ss: 截图
            text: 搜索的文字
            fuzzy: 是否模糊匹配（包含关系）
        """
        elements = VisionEngine.ocr(ss, min_confidence)
        results = []
        
        for elem in elements:
            if fuzzy:
                if text.lower() in elem.text.lower():
                    results.append(elem)
            else:
                if text == elem.text:
                    results.append(elem)
        
        # 按置信度排序
        results.sort(key=lambda e: (-e.confidence, -e.area))
        return results
    
    @staticmethod
    def find_text_center(ss: ScreenShot, text: str, fuzzy: bool = True,
                         min_confidence: float = 0.3) -> Optional[Tuple[int, int]]:
        """找文字并返回中心坐标"""
        results = VisionEngine.find_text(ss, text, fuzzy, min_confidence)
        if results:
            return results[0].center
        return None
    
    @staticmethod
    def describe(ss: ScreenShot, min_confidence: float = 0.3) -> List[str]:
        """生成文字描述（用于ReAct决策）"""
        elements = VisionEngine.ocr(ss, min_confidence)
        lines = []
        for e in sorted(elements, key=lambda x: (x.y, x.x)):
            lines.append(f"[{e.confidence:.0f}%] ({e.x},{e.y}) {e.width}x{e.height} <{e.text}>")
        return lines
    
    @staticmethod
    def refine_center_opencv(ss: ScreenShot, approx_x: int, approx_y: int,
                             search_size: int = 40) -> Tuple[int, int]:
        """
        Layer 4: OpenCV边缘检测精确定位
        从粗坐标开始，找最近的按钮边缘，返回更精确的点击点
        
        Args:
            ss: 截图
            approx_x, approx_y: 粗坐标（Vision OCR的输出，±20px误差）
            search_size: 搜索区域半径
        
        Returns:
            精修后的点击点 (±3px精度)
        """
        if not HAS_CV2:
            return (approx_x, approx_y)
        
        # 局部裁剪
        sx = max(0, approx_x - search_size)
        sy = max(0, approx_y - search_size)
        sw = min(search_size * 2, ss.width - sx)
        sh = min(search_size * 2, ss.height - sy)
        
        if sw < 10 or sh < 10:
            return (approx_x, approx_y)
        
        # 取BGRA的BGR通道
        region = ss.bgra[sy:sy+sh, sx:sx+sw, :3].copy()
        
        # 边缘检测
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        
        # 找轮廓
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return (approx_x, approx_y)
        
        # 找最近的按钮轮廓（中心点离粗坐标最近的）
        search_cx, search_cy = search_size, search_size
        best_dist = search_size * 2
        best_center = (approx_x, approx_y)
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 200 or area > sw * sh * 0.8:
                continue
            
            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            dist = ((cx - search_cx) ** 2 + (cy - search_cy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_center = (sx + cx, sy + cy)
        
        return best_center


# ============================================================
# 3. 精度对齐引擎 (Layer 4)
# ============================================================

class PrecisionAligner:
    """由 VisionEngine.refine_center_opencv 提供"""
    pass


# ============================================================
# 4. 操作执行
# ============================================================

class MouseController:
    """鼠标/键盘控制"""
    
    @staticmethod
    def click(x: int, y: int, wait: float = 0.3) -> None:
        pyautogui.moveTo(x, y, duration=0.08)
        pyautogui.click()
        time.sleep(wait)
    
    @staticmethod
    def click_refined(ss: ScreenShot, approx_x: int, approx_y: int,
                      wait: float = 0.3) -> Tuple[int, int]:
        """使用OCR定位+OpenCV精修后点击"""
        final_x, final_y = VisionEngine.refine_center_opencv(ss, approx_x, approx_y)
        MouseController.click(final_x, final_y, wait)
        return (final_x, final_y)
    
    @staticmethod
    def click_text(ss: ScreenShot, text: str, fuzzy: bool = True,
                   wait: float = 0.3, refine: bool = True) -> Optional[Tuple[int, int]]:
        """找文字并点击"""
        center = VisionEngine.find_text_center(ss, text, fuzzy)
        if not center:
            return None
        
        cx, cy = center
        if refine:
            cx, cy = VisionEngine.refine_center_opencv(ss, cx, cy)
        
        MouseController.click(cx, cy, wait)
        return (cx, cy)
    
    @staticmethod
    def type(text: str, interval: float = 0.05) -> None:
        pyautogui.write(text, interval=interval)
    
    @staticmethod
    def press(key: str, times: int = 1) -> None:
        for _ in range(times):
            pyautogui.press(key)
            time.sleep(0.2)
    
    @staticmethod
    def scroll(clicks: int) -> None:
        pyautogui.scroll(clicks)
    
    @staticmethod
    def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        pyautogui.moveTo(x1, y1, duration=0.1)
        pyautogui.drag(x2 - x1, y2 - y1, duration=duration)


# ============================================================
# 5. 验证闭环 (Layer 5)
# ============================================================

class VerifyLoop:
    """
    验证闭环 — OCR验证 + 自愈重试
    
    操作后截屏确认：预期文字是否出现/消失？
    """
    
    @staticmethod
    def verify_text_appears(text: str, timeout: float = 3.0,
                            interval: float = 0.5) -> Tuple[bool, float]:
        """
        验证文字是否在timeout内出现
        Returns: (是否出现, 耗时)
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            ss = ScreenShot()
            results = VisionEngine.find_text(ss, text)
            if results:
                return True, time.time() - t0
            time.sleep(interval)
        return False, timeout
    
    @staticmethod
    def verify_text_disappears(text: str, timeout: float = 3.0,
                               interval: float = 0.5) -> Tuple[bool, float]:
        """验证文字是否消失"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            ss = ScreenShot()
            results = VisionEngine.find_text(ss, text)
            if not results:
                return True, time.time() - t0
            time.sleep(interval)
        return False, timeout
    
    @staticmethod
    def verify_brightness_change(region: Tuple[int, int, int, int],
                                 threshold: float = 50,
                                 timeout: float = 3.0,
                                 interval: float = 0.3) -> Tuple[bool, float, float]:
        """
        验证区域亮度变化
        Returns: (是否变化, 变化量, 耗时)
        """
        x, y, w, h = region
        ss_before = ScreenShot()
        brightness_before = ss_before.region_brightness(x, y, w, h)
        
        t0 = time.time()
        while time.time() - t0 < timeout:
            ss = ScreenShot()
            brightness = ss.region_brightness(x, y, w, h)
            diff = abs(brightness - brightness_before)
            if diff > threshold:
                return True, diff, time.time() - t0
            time.sleep(interval)
        
        return False, 0, timeout
    
    @staticmethod
    def retry_on_fail(action: Callable, verify_func: Callable,
                      max_retries: int = 3, action_name: str = "操作") -> bool:
        """
        自愈重试：执行操作→验证→失败→重试
        Args:
            action: 执行操作的函数
            verify_func: 验证函数，返回(bool, any)
            max_retries: 最大重试次数
        Returns:
            是否最终成功
        """
        for attempt in range(max_retries):
            log(f"  执行[{action_name}] 尝试 #{attempt+1}", "ACT")
            action()
            success, detail = verify_func()
            if success:
                log(f"  [{action_name}] ✅ 验证通过", "VERIFY")
                return True
            else:
                log(f"  [{action_name}] ❌ 验证失败，第{attempt+1}次", "VERIFY")
                time.sleep(0.5)
        
        log(f"  [{action_name}] ⛔ 重试{max_retries}次仍失败", "ERR")
        return False


# ============================================================
# 6. 决策引擎 (Layer 3 — ReAct循环)
# ============================================================

class ReActDecision:
    """
    简单的ReAct决策循环
    观察(OCR)→思考→行动(点击/输入)→观察→...
    """
    
    def __init__(self, max_steps: int = 15):
        self.max_steps = max_steps
        self.history: List[Dict] = []
    
    def observe(self, region: Optional[Tuple[int, int, int, int]] = None) -> List[str]:
        """观察当前屏幕"""
        ss = ScreenShot()
        elements = VisionEngine.describe(ss)
        self.history.append({
            "step": len(self.history),
            "type": "observe",
            "elements_count": len(elements),
        })
        return elements
    
    def think(self, goal: str, context: List[str]) -> str:
        """
        思考下一步操作。
        实际场景中会将context发给LLM进行决策。
        这里提供一个简化的规则决策。
        
        Returns: 操作指令描述
        """
        # 基础规则：如果看到目标文字就点击
        for line in context:
            if goal.lower() in line.lower():
                return f"found_text:{goal}"
        
        return "continue_search"
    
    def act(self, instruction: str) -> bool:
        """执行操作"""
        if instruction.startswith("found_text:"):
            text = instruction.split(":", 1)[1]
            ss = ScreenShot()
            result = MouseController.click_text(ss, text)
            self.history.append({
                "step": len(self.history),
                "type": "click_text",
                "text": text,
                "success": result is not None,
            })
            return result is not None
        
        elif instruction == "continue_search":
            MouseController.scroll(-3)
            return True
        
        return False
    
    def run(self, goal: str) -> bool:
        """
        执行ReAct循环直到找到目标
        Returns: 是否在max_steps内找到目标
        """
        log(f"🎯 ReAct: 目标=[{goal}]", "VISION")
        
        for step in range(self.max_steps):
            # 观察
            context = self.observe()
            log(f"  步骤{step+1}: 观察={len(context)}元素", "VISION")
            
            # 思考
            instruction = self.think(goal, context)
            
            # 如果找到了
            if instruction.startswith("found_text:"):
                success = self.act(instruction)
                if success:
                    log(f"  ✅ 找到并点击 [{goal}]", "OK")
                    return True
            
            # 滚动继续搜索
            self.act("continue_search")
        
        log(f"  ❌ [{goal}] 在{self.max_steps}步内未找到", "ERR")
        return False


# ============================================================
# 7. 统一Agent
# ============================================================

class ComputerUseAgent:
    """
    纯视觉电脑操作Agent — 单例模式
    
    核心方法:
      screenshot() → 截屏
      locate(text) → 定位文字
      click(text) → 找文字点点击
      type(text) → 输入文字
      verify(text) → 验证文字出现
      describe() → 描述当前屏幕
    """
    
    _instance: Optional['ComputerUseAgent'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.sampler = ScreenSampler()
            self.vision = VisionEngine()
            self.mouse = MouseController()
            self.verify = VerifyLoop()
    
    def screenshot(self, region: Optional[Tuple[int, int, int, int]] = None) -> ScreenShot:
        """截屏"""
        return self.sampler.capture(region)
    
    def locate(self, text: str, fuzzy: bool = True,
               min_confidence: float = 0.3) -> Optional[LocateResult]:
        """
        定位屏幕上的文字
        Returns: LocateResult 或 None
        """
        ss = self.screenshot()
        elements = self.vision.find_text(ss, text, fuzzy, min_confidence)
        
        if not elements:
            return None
        
        elem = elements[0]
        # 精修坐标
        refined = self.vision.refine_center_opencv(ss, elem.center[0], elem.center[1])
        
        return LocateResult(
            element=elem,
            screen_region=(elem.x, elem.y, elem.width, elem.height),
            confidence=elem.confidence,
            method="ocr",
            refine_center=refined,
        )
    
    def locate_all(self, text: str, fuzzy: bool = True,
                   min_confidence: float = 0.3) -> List[LocateResult]:
        """定位所有匹配的文字"""
        ss = self.screenshot()
        elements = self.vision.find_text(ss, text, fuzzy, min_confidence)
        
        results = []
        for elem in elements:
            results.append(LocateResult(
                element=elem,
                screen_region=(elem.x, elem.y, elem.width, elem.height),
                confidence=elem.confidence,
                method="ocr",
            ))
        return results
    
    def click(self, text: str, fuzzy: bool = True,
              wait: float = 0.4, refine: bool = True) -> bool:
        """找文字并点击"""
        locate_result = self.locate(text, fuzzy)
        if not locate_result:
            log(f"❌ 未找到文字: [{text}]", "WARN")
            return False
        
        cx, cy = locate_result.refine_center if refine else locate_result.element.center
        log(f"🖱️ 点击: [{text}] → ({cx},{cy})", "ACT")
        self.mouse.click(cx, cy, wait)
        return True
    
    def click_region(self, x: int, y: int, wait: float = 0.4,
                     refine: bool = True) -> Tuple[int, int]:
        """点击坐标（可选精修）"""
        if refine:
            ss = self.screenshot()
            cx, cy = self.vision.refine_center_opencv(ss, x, y)
        else:
            cx, cy = x, y
        self.mouse.click(cx, cy, wait)
        return (cx, cy)
    
    def type(self, text: str, interval: float = 0.05) -> None:
        self.mouse.type(text, interval)
    
    def press(self, key: str, times: int = 1) -> None:
        self.mouse.press(key, times)
    
    def verify(self, text: str, timeout: float = 3.0) -> bool:
        """验证文字是否在timeout内出现"""
        success, elapsed = self.verify.verify_text_appears(text, timeout)
        if success:
            log(f"✅ 验证: [{text}] 在{elapsed:.1f}s内出现", "VERIFY")
        else:
            log(f"❌ 验证: [{text}] 超时{timeout}s未出现", "VERIFY")
        return success
    
    def describe(self) -> List[str]:
        """描述当前屏幕内容"""
        ss = self.screenshot()
        return self.vision.describe(ss)
    
    def wait_and_click(self, text: str, timeout: float = 5.0,
                       interval: float = 0.5) -> bool:
        """等待文字出现并点击"""
        log(f"⏳ 等待 [{text}] 出现...", "WAIT")
        t0 = time.time()
        while time.time() - t0 < timeout:
            locate_result = self.locate(text)
            if locate_result:
                log(f"✅ 找到 [{text}]", "OK")
                self.mouse.click(locate_result.refine_center[0],
                                 locate_result.refine_center[1])
                return True
            time.sleep(interval)
        log(f"❌ [{text}] 在{timeout}s内未出现", "WARN")
        return False


# ============================================================
# 8. 示例用法
# ============================================================

def demo():
    """快速演示 ComputerUseAgent 功能"""
    agent = ComputerUseAgent()
    
    log("=" * 60, "STEP")
    log("🖥️ ComputerUseAgent 功能检测", "STEP")
    log("=" * 60)
    
    # 1. 截屏
    log("\n1️⃣ 截屏", "VISION")
    ss = agent.screenshot()
    log(f"   尺寸: {ss.width}x{ss.height}", "OK")
    
    # 2. 描述屏幕
    log("\n2️⃣ 屏幕描述 (OCR)", "VISION")
    desc = agent.describe()
    log(f"   识别到 {len(desc)} 个文字", "OK")
    for line in desc[:10]:
        log(f"   {line}", "DET")
    
    # 3. 文字定位
    log("\n3️⃣ 文字定位", "VISION")
    # 尝试定位常见菜单文字
    for target in ["Window", "Telegram", "Edit", "File"]:
        result = agent.locate(target)
        if result:
            log(f"   [{target}] → 中心({result.element.center[0]},{result.element.center[1]}) "
                f"精修({result.refine_center[0]},{result.refine_center[1]}) "
                f"置信度{result.confidence}%", "OK")
        else:
            log(f"   [{target}] → 未找到", "INFO")
    
    log("\n✅ Agent 就绪", "OK")


if __name__ == "__main__":
    demo()
