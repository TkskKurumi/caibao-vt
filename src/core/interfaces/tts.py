"""TTS (Text-to-Speech) Interface"""
from __future__ import annotations
import asyncio
import os
from os import path
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from .base import Interface, register_interface
from ..audio.play import play_file_wait_async

# ============================================================================
# TTS Backend 抽象基类
# ============================================================================

class QueuedPlayer:
    """音频队列播放器：消费已生成的音频文件并播放"""
    def __init__(self, maxsize=5, subtitle_filename=None):
        self.q = asyncio.Queue(maxsize=maxsize)
        self._worker_task = None
        self.subtitle_filename = subtitle_filename
    
    async def start(self):
        """启动播放器 worker"""
        assert self._worker_task is None
        self._worker_task = asyncio.create_task(self.worker())
    
    async def check_exc(self):
        """检查 worker 是否有异常"""
        if (self._worker_task and self._worker_task.done() and self._worker_task.exception()):
            raise self._worker_task.exception()
    
    async def stop(self):
        """停止播放器 worker"""
        await self.q.join()
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
    
    async def put(self, emotion, content, audio_fn):
        """将音频文件放入播放队列"""
        return await self.q.put((emotion, content, audio_fn))
    
    async def worker(self):
        """播放器 worker：从队列取文件并播放"""
        while (True):
            emotion, content, fn = await self.q.get()
            try:
                if (self.subtitle_filename):
                    dn = path.dirname(self.subtitle_filename)
                    if (dn):
                        os.makedirs(dn, exist_ok=True)
                    with open(self.subtitle_filename, "w", encoding="utf-8") as f:
                        f.write(content)
                await play_file_wait_async(fn)
            except Exception:
                self.q.task_done()
                raise
            self.q.task_done()

class TTSBackend(ABC):
    """TTS 后端抽象基类：生成音频文件并放入播放队列"""
    def __init__(self, player: QueuedPlayer, maxsize=5):
        self.player = player
        self.q = asyncio.Queue(maxsize=maxsize)
        self._worker_task = None
    
    async def put(self, emotion, content):
        """将 (emotion, content) 放入生成队列"""
        await self.q.put((emotion, content))
    
    async def start(self):
        """启动 TTS 生成 worker"""
        assert self._worker_task is None
        self._worker_task = asyncio.create_task(self.worker())
    
    async def stop(self):
        """停止 TTS 生成 worker"""
        await self.q.join()
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
    
    async def check_exc(self):
        """检查 worker 是否有异常"""
        if (self._worker_task and self._worker_task.done() and self._worker_task.exception()):
            raise self._worker_task.exception()
    
    @abstractmethod
    async def _generate_tts_single(self, emotion, content) -> str:
        """生成单个音频文件（子类实现）"""
        pass
    
    async def worker(self):
        """TTS 生成 worker：从队列取任务，生成音频，放入播放队列"""
        while True:
            emotion, content = await self.q.get()
            try:
                fn = await self._generate_tts_single(emotion, content)
                await self.player.put(emotion, content, fn)
            except:
                self.q.task_done()
                raise
            self.q.task_done()

# ============================================================================
# IndexTTS API Backend 实现
# ============================================================================

class IndexTTSAPIBackend(TTSBackend):
    """IndexTTS API TTS 后端实现"""
    
    def __init__(self, player: QueuedPlayer, base_url: str, voice: str,
                 allow_emotion: bool = False, tmp_audio_dir: str = "./.tmp/indextts",
                 maxsize: int = 5):
        """
        Args:
            player: QueuedPlayer 实例，用于播放生成的音频
            base_url: IndexTTS API 基础 URL
            voice: 音色名称（配置文件中指定）
            allow_emotion: 是否启用情感合成
            tmp_audio_dir: 临时音频文件保存目录
            maxsize: 内部队列最大大小
        """
        super().__init__(player, maxsize=maxsize)
        
        self.base_url = base_url.rstrip('/')
        self.voice = voice
        self.allow_emotion = allow_emotion
        self.tmp_audio_dir = tmp_audio_dir
        
        self._session = None
        
        # 确保临时目录存在
        os.makedirs(self.tmp_audio_dir, exist_ok=True)
    
    async def _ensure_session(self) -> None:
        """确保 aiohttp 会话已创建"""
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
    
    def _get_voice_name(self, emotion: str) -> str:
        """根据情感获取实际使用的音色名"""
        if self.allow_emotion and emotion:
            return f"{self.voice}-{emotion}"
        else:
            return f"{self.voice}-normal"
    
    async def _generate_tts_single(self, emotion: str, content: str) -> str:
        """生成单个音频文件（内部方法）"""
        await self._ensure_session()
        
        use_voice = self._get_voice_name(emotion)
        
        payload = {
            "text": content,
            "voice": use_voice,
            "emotion_strength": 0.6
        }
        
        try:
            import aiohttp
            async with self._session.post(f"{self.base_url}/generate", json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"IndexTTS API 返回错误状态码 {resp.status}: {error_text}")
                
                data = await resp.json()
                
                if data.get("status") != "success":
                    raise Exception(f"IndexTTS 生成失败：{data}")
                
                # 获取远程音频文件名（如：yvette-normal_1773970889.wav）
                remote_filename = data.get("audio_path")
                if not remote_filename:
                    raise Exception("IndexTTS API 未返回 audio_path")
                
                # 下载音频文件到本地
                local_path = os.path.join(self.tmp_audio_dir, remote_filename)
                async with self._session.get(f"{self.base_url}/download/{remote_filename}") as download_resp:
                    if download_resp.status != 200:
                        raise Exception(f"下载音频文件失败：{download_resp.status}")
                    
                    with open(local_path, "wb") as f:
                        f.write(await download_resp.read())
                
                return local_path
                
        except aiohttp.ClientError as e:
            raise Exception(f"IndexTTS API 连接错误：{e}")
        except Exception as e:
            raise Exception(f"IndexTTS 生成音频失败：{e}")
    
    async def stop(self) -> None:
        await super().stop()
        if self._session:
            await self._session.close()
            self._session = None


# ============================================================================
# TTS Interface 实现
# ============================================================================

@register_interface("tts")
class TTSInterface(Interface):
    """TTS (Text-to-Speech) Interface
    
    使用生产 - 消费模型实现并行处理：
    VLM → on_speech() → TTSBackend.put() → TTSBackend.worker() → 生成音频 → player.put() → QueuedPlayer.worker() → 播放
    """
    
    def __init__(self, player: QueuedPlayer, tts_backend: TTSBackend):
        """
        Args:
            player: QueuedPlayer 实例，用于播放生成的音频
            tts_backend: TTSBackend 实例，用于生成音频
        """
        self.player = player
        self.tts_backend = tts_backend

    @classmethod
    def from_cfg(cls, cfg: Dict) -> "TTSInterface":
        """从配置创建 TTSInterface"""
        backend_type = cfg.get("tts_type", "index_tts")
        
        # 创建 QueuedPlayer
        player = QueuedPlayer(maxsize=cfg.get("player_queue_size", 5), subtitle_filename=cfg.get("subtitle_filename", None))
        
        if backend_type == "index_tts":
            backend = IndexTTSAPIBackend(
                player=player,
                base_url=cfg.get("endpoint", "http://localhost:8096"),
                voice=cfg.get("voice", "default"),
                allow_emotion=cfg.get("allow_emotion", False),
                tmp_audio_dir=cfg.get("tmp_audio_dir", "./.tmp/indextts"),
                maxsize=cfg.get("backend_queue_size", 5)
            )
        else:
            raise ValueError(f"不支持的 TTS 后端类型：{backend_type}")
        
        return cls(player=player, tts_backend=backend)
    
    async def collect_input(self):
        """STT 不需要的 Interface，返回空列表"""
        return []
    
    async def start(self) -> None:
        """启动 TTS Interface（启动 player 和 backend 的 worker）"""
        await self.player.start()
        await self.tts_backend.start()
    
    async def stop(self) -> None:
        """停止 TTS Interface（停止 backend 和 player 的 worker）"""
        # 先停止 backend，再停止 player
        await self.tts_backend.stop()
        await self.player.stop()
    
    async def on_speech(self, speech: List[Tuple[str, str]]) -> None:
        """
        处理 LLM 的发言
        
        speech 格式：[(emotion, content), ("happy", "你好！很高兴见到你！"), ...]
        
        将每个非空内容放入 TTSBackend 队列，由 worker 异步生成并播放
        """
        # 检查是否有异常（来自之前的 worker）
        await self.player.check_exc()
        await self.tts_backend.check_exc()
        if (self.tts_backend.q.maxsize == 0):
            await self.tts_backend.q.join()       
        # 将所有非空内容放入队列
        for emotion, content in speech:
            
            if content:
                await self.tts_backend.put(emotion, content)
        
        # 注意：这里不等待播放完成，worker 会异步处理
        # 如果需要等待所有播放完成，可以调用 await self.player.q.join()
    
    def get_tools(self) -> List[tuple]:
        """TTS Interface 不提供工具"""
        return []
    
    def get_system_prompt(self) -> str:
        """返回 TTS Interface 的 system prompt 片段"""
        return """## 语音输出
- LLM 的发言会通过 TTS 转换为语音播放
- 发言格式：[{"content": str, "emotion": str}, ...]
- emotion 字段用于选择情感语音（如果启用）
- 使用生产 - 消费模型实现并行处理，降低 first-audio-latency
"""
