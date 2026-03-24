"""STT (Speech-to-Text) Interface"""
from __future__ import annotations
import asyncio
import sys
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from ..msg import InputMsg
from .base import Interface, register_interface


# ============================================================================
# STT Backend 抽象基类
# ============================================================================

class STTBackend(ABC):
    """STT 后端抽象基类"""
    
    @abstractmethod
    async def start(self) -> None:
        """启动 STT 识别（开始麦克风监听循环）"""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止 STT 识别"""
        pass
    
    @abstractmethod
    def collect_input(self) -> List[str]:
        """
        收集已识别的文本
        
        返回：已识别的文本列表（非空字符串）
              实现方应负责清空内部缓冲区
        """
        pass


# ============================================================================
# STTMsg 消息类
# ============================================================================

class STTMsg(InputMsg):
    """STT 识别消息"""
    
    def __init__(self, text: str, timestamp: float = None):
        """
        Args:
            text: 识别的文本内容
            timestamp: 时间戳（可选，默认使用当前时间）
        """
        import time
        self.text = text
        self.timestamp = timestamp if timestamp is not None else time.time()
    
    def get_llm_msg(self, context_manager = None) -> Dict[str, Any]:
        """转换为 LLM 可理解的格式"""
        return {
            "type": "stt",
            "content": self.text,
            "timestamp": self.timestamp
        }
    
    def get_unique_msgs(self) -> List[Any]:
        """STT 消息不需要去重"""
        return []


# ============================================================================
# SherpaNCNN Backend 实现
# ============================================================================

class STTSherpaNCNNBackend(STTBackend):
    """Sherpa-NCNN STT 后端实现"""
    
    def __init__(self, model_dir: str, num_threads: int = 4, device_idx: int = None):
        """
        Args:
            model_dir: 模型目录（包含 tokens.txt 和模型文件）
            num_threads: 线程数
            device_idx: 麦克风设备索引（None 表示使用默认设备）
        """
        self.model_dir = model_dir
        self.num_threads = num_threads
        self.device_idx = device_idx
        
        self._recognizer = None
        self._running = False
        self._last_result = ""
        self._buffer: List[str] = []  # 已识别的文本缓冲区
        
        # 延迟导入，避免未安装时出错
        self._sd = None
        self._sherpa = None
    
    def _init_dependencies(self) -> None:
        """初始化依赖库"""
        try:
            import sounddevice as sd
            import sherpa_ncnn
            self._sd = sd
            self._sherpa = sherpa_ncnn
        except ImportError as e:
            raise ImportError(
                "STT SherpaNCNN 需要安装 sounddevice 和 sherpa-ncnn:\n"
                "  pip install sounddevice sherpa-ncnn"
            ) from e
    
    def _create_recognizer(self):
        """创建 Sherpa 识别器"""
        # 模型文件路径（根据实际目录结构调整）
        tokens = f"{self.model_dir}/tokens.txt"
        encoder_param = f"{self.model_dir}/encoder_jit_trace-pnnx.ncnn.param"
        encoder_bin = f"{self.model_dir}/encoder_jit_trace-pnnx.ncnn.bin"
        decoder_param = f"{self.model_dir}/decoder_jit_trace-pnnx.ncnn.param"
        decoder_bin = f"{self.model_dir}/decoder_jit_trace-pnnx.ncnn.bin"
        joiner_param = f"{self.model_dir}/joiner_jit_trace-pnnx.ncnn.param"
        joiner_bin = f"{self.model_dir}/joiner_jit_trace-pnnx.ncnn.bin"
        
        self._recognizer = self._sherpa.Recognizer(
            tokens=tokens,
            encoder_param=encoder_param,
            encoder_bin=encoder_bin,
            decoder_param=decoder_param,
            decoder_bin=decoder_bin,
            joiner_param=joiner_param,
            joiner_bin=joiner_bin,
            num_threads=self.num_threads,
            rule1_min_trailing_silence=120,
            rule2_min_trailing_silence=0.8, # 0.8秒内无声音识别为断句
            rule3_min_utterance_length=120,
            enable_endpoint_detection=True
        )
    
    async def start(self) -> None:
        """启动麦克风监听循环"""
        self._init_dependencies()
        self._create_recognizer()
        
        sample_rate = self._recognizer.sample_rate
        samples_per_read = int(0.1 * sample_rate)  # 100ms
        
        self._running = True
        
        # 在后台线程中运行阻塞的麦克风读取
        asyncio.create_task(self._mic_loop(sample_rate, samples_per_read))
    
    async def _mic_loop(self, sample_rate: float, samples_per_read: int) -> None:
        """麦克风监听循环（在后台运行）"""
        _last_result = None 
        with self._sd.InputStream(
            device=self.device_idx,
            channels=1,
            dtype="float32",
            samplerate=sample_rate
        ) as s:
            while self._running:
                # 使用 to_thread 包装阻塞调用，避免阻塞事件循环
                samples, _ = await asyncio.to_thread(s.read, samples_per_read)
                samples = samples.reshape(-1)
                
                # accept_waveform 也是阻塞调用，同样用 to_thread 包装
                await asyncio.to_thread(self._recognizer.accept_waveform, sample_rate, samples)
                
                if (self._recognizer.text != _last_result):
                    _last_result = self._recognizer.text
                    print("STT", _last_result, self._recognizer.is_endpoint)
                if (self._recognizer.is_endpoint):
                    if (self._recognizer.text):
                        print(self._recognizer.text)
                        self._buffer.append(self._recognizer.text)
                    self._recognizer.reset()
    async def stop(self) -> None:
        """停止麦克风监听"""
        self._running = False
    
    def collect_input(self) -> List[str]:
        """
        收集已识别的文本并清空缓冲区
        
        返回：非空文本列表
        """
        # 获取并清空
        ret = self._buffer
        self._buffer = []
        return ret


# ============================================================================
# STT Interface 实现
# ============================================================================

@register_interface("stt")
class STTInterface(Interface):
    """STT (Speech-to-Text) Interface
    
    通过麦克风监听用户语音，识别为文字后作为输入消息
    """
    
    def __init__(self, backend: STTBackend):
        """
        Args:
            backend: STT 后端实现
        """
        self.backend = backend
        self._stt_buffer: List[STTMsg] = []
    
    @classmethod
    def from_cfg(cls, cfg: Dict) -> "STTInterface":
        """从配置创建 STTInterface"""
        backend_type = cfg.get("stt_type", "sherpa_ncnn")
        
        if backend_type == "sherpa_ncnn":
            backend = STTSherpaNCNNBackend(
                model_dir=cfg.get("model_dir", "./sherpa-models"),
                num_threads=cfg.get("num_threads", 4),
                device_idx=cfg.get("device_idx", None)
            )
        else:
            raise ValueError(f"不支持的 STT 后端类型：{backend_type}")
        
        return cls(backend=backend)
    
    async def start(self) -> None:
        """启动 STT 识别"""
        await self.backend.start()
    
    async def stop(self) -> None:
        """停止 STT 识别"""
        await self.backend.stop()
    
    async def collect_input(self) -> List[InputMsg]:
        """
        收集 STT 识别的文本输入
        
        返回：STTMsg 列表（仅包含非空文本）
        """
        texts = self.backend.collect_input()
        
        # 仅当有非空文本时才创建消息
        if not texts:
            return []
        
        return [STTMsg(text=text) for text in texts]
    
    def get_tools(self) -> List[tuple]:
        """STT Interface 不提供工具"""
        return []
    
    def get_system_prompt(self) -> str:
        """返回 STT Interface 的 system prompt 片段"""
        return """## 语音输入
- 用户通过麦克风语音输入
- 语音被识别为文字后作为输入
- 语音消息格式：{"type": "stt", "content": str, "timestamp": float}
"""
