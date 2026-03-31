"""Interface 模块：所有 Interface 实现的集合"""

from .base import Interface
from .danmaku import BiliDanmakuInterface, BiliDanmakuMsg, BiliUserUniqueMsg
from .screenshot import ScreenshotInterface, ScreenshotMsg
from .heartbeat import HeatbeatInterface
from .stt import STTInterface, STTMsg, STTBackend, STTSherpaNCNNBackend
from .tts import TTSInterface, TTSBackend, IndexTTSAPIBackend
from .vts_tts import VTSTTSInterface
from .bili_danmaku_v2 import BiliDanmakuInterfaceV2
__all__ = [
    "Interface",
    "BiliDanmakuInterface", "BiliDanmakuMsg", "BiliUserUniqueMsg",
    "ScreenshotInterface", "ScreenshotMsg",
    "HearbeatInterface",
    "STTInterface", "STTMsg", "STTBackend", "STTSherpaNCNNBackend",
    "TTSInterface", "TTSBackend", "IndexTTSAPIBackend"
]