"""屏幕截图 Interface"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Callable, Awaitable
from ..msg import InputMsg
from ..image import ImagePIL
from .base import Interface, register_interface
from ..oai_tool import OAIFunction
import asyncio
import time, traceback
from datetime import datetime
from PIL import Image
import io
from PIL import ImageGrab

@register_interface("screenshot")
class ScreenshotInterface(Interface):
    """屏幕截图 Interface，定期截图并作为输入消息发送
    
    配置项：
        - frame_rate: 截图频率（fps），例如 1.0 表示每秒 1 帧
        - max_frame: 每次 collect_input 抽取的最大帧数
    """
    
    def __init__(self, frame_rate: float = 1.0, max_frame: int = 5):
        self.frame_rate = frame_rate
        self.max_frame = max_frame
        self._running = False
        self._screenshot_buffer: List[Tuple[Image.Image, float, str]] = []  # (image, timestamp, timehuman)
        self._last_screenshot_time = 0.0
        self._interval = 1.0 / frame_rate if frame_rate > 0 else float('inf')
    
    @classmethod
    def from_cfg(cls, cfg: Dict) -> "ScreenshotInterface":
        return cls(
            frame_rate=cfg.get("frame_rate", 1.0),
            max_frame=cfg.get("max_frame", 5)
        )
    
    async def start(self) -> None:
        """启动截图循环"""
        self._running = True
        asyncio.create_task(self._screenshot_loop())
    
    async def stop(self) -> None:
        """停止截图循环"""
        self._running = False
    
    async def _screenshot_loop(self) -> None:
        """后台截图循环"""
        while self._running:
            now = time.time()
            if now - self._last_screenshot_time >= self._interval:
                # 截图
                try:
                    img = self._capture_screen()
                    timestamp = now
                    timehuman = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
                    self._screenshot_buffer.append((img, timestamp, timehuman))
                    self._last_screenshot_time = now
                except Exception:
                    traceback.print_exc()
            # 控制循环频率
            await asyncio.sleep(self._interval / 3)  # 每 1/10 帧检查一次
    
    def _capture_screen(self) -> Image.Image:
        """截取全屏截图"""
        # 使用 PIL 的 ImageGrab（需要 Pillow 安装）        
        return ImageGrab.grab()
    @property
    def n_buffer(self):
        return len(self._screenshot_buffer)
    
    async def collect_input(self) -> List[InputMsg]:
        """从缓冲区抽取最多 max_frame 帧，建立 ScreenshotMsg"""
        # 抽取最多 max_frame 帧
        screenshots = []
        if (len(self._screenshot_buffer) > self.max_frame):
            if (self.max_frame == 1):
                self._screenshot_buffer = [self._screenshot_buffer[-1]]
            else:
                self._screenshot_buffer = [
                    self._screenshot_buffer[min(int(i/self.max_frame*self.n_buffer), self.n_buffer-1)]
                    for i in range(self.max_frame)
                ]
        
        # 建立 ScreenshotMsg
        ret = [ScreenshotMsg(self._screenshot_buffer)]
        self._screenshot_buffer = []
        return ret
    
    def get_tools(self) -> List[Tuple[OAIFunction, Callable[..., Awaitable]]]:
        """截图 Interface 不提供工具"""
        return []
    
    def get_system_prompt(self) -> str:
        """返回截图 Interface 的 system prompt 片段"""
        return f"""## 屏幕截图输入
- 定期截取全屏截图
- 截图频率：{self.frame_rate} fps
- 每次最多提供 {self.max_frame} 帧
"""


class ScreenshotMsg(InputMsg):
    """屏幕截图消息
    
    包含多帧截图，每帧包含：
        - image: ImagePIL 对象
        - timestamp: 时间戳（float）
        - timehuman: 人类可读时间（str）
    """
    
    def __init__(self, screenshots: List[Tuple[Image.Image, float, str]]):
        """
        Args:
            screenshots: 截图列表，每个元素为 (PIL.Image, timestamp, timehuman)
        """
        self.screenshots = screenshots
        # 转换为 ImageObject 格式
        self._image_objects: List[Dict[str, Any]] = []
        for img, timestamp, timehuman in screenshots:
            image_obj = ImagePIL(img, image_id=f"screenshot-{timehuman}-{timestamp}")
            self._image_objects.append({
                "image": image_obj,
                "timestamp": timestamp,
                "timehuman": timehuman
            })
    
    def get_llm_msg(self, context_manager = None) -> Dict[str, Any]:
        """转换为 LLM 可理解的格式"""
        return {
            "type": "screenshot",
            "screenshots": self._image_objects
        }
    
    def get_unique_msgs(self) -> List[Any]:
        """截图消息不需要去重，返回空列表"""
        return []
