"""TTS (Text-to-Speech) Interface"""
from __future__ import annotations
import asyncio, time
import os, random, yaml
from os import path
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, Protocol
from .base import Interface, register_interface
from ..audio.play import play_file_wait_async
from dataclasses import dataclass
import pyvts
from collections import defaultdict
from pyvts import VTSRequest
from math import sqrt
'''
emotion config example
emotion:
  default:
  - params: [EyeOpenL, EyeOpenR]
    type: blink
  - params: [FaceAngleY]
    type: rnd
    range: [-30, 30]
    trange: [3, 30]
  speech:
    happy:
      on_start:
      - params: [MouthOpen]
        type: loop
        duration: [0.3, 0.3]
        value:    [  1,   1]
      - params: [MouthSmile]
        type: constant
        value: 1
      on_end:
      - params: [MouthOpen]
        type: reset
'''

def interp_fn(x):
    if (x<0):
        return 0
    elif (x>1):
        return 1
    else:
        return sqrt(1-(1-x)*(1-x))
def interp_from_to(x0, x1, y0, y1):
    def f(x):
        return y0 + interp_fn((x-x0)/(x1-x0))*(y1-y0)
    return f
class ActionLoop:
    def __init__(self, values, durations):
        self.values = values
        self.durations = durations
        self.ed = 0
        self.idx = 0
        self.n = len(values)
    def __call__(self, t: float) -> float:
        if (t>self.ed):
            x0 = t
            x1 = t+self.durations[self.idx]
            y0 = self.values[self.idx-1]
            y1 = self.values[self.idx]
            self.ed = x1
            self.idx = (self.idx+1)%self.n
            self.f = interp_from_to(x0, x1, y0, y1)
        return self.f(t)
class ActionRand:
    def __init__(self, v_min, v_max, dur_min, dur_max, t_interp):
        self.v_min = v_min
        self.v_max = v_max
        self.dur_min = dur_min
        self.dur_max = dur_max
        self.v1 = random.uniform(v_min, v_max)
        self.ed = 0
        self.t_interp = t_interp
    def __call__(self, t: float) -> float:
        if (t>self.ed):
            v0 = self.v1
            self.v1 = random.uniform(self.v_min, self.v_max)
            x0 = t
            x1 = t+self.t_interp
            self.ed = t+random.uniform(self.dur_min, self.dur_max)
            self.f = interp_from_to(x0, x1, v0, self.v1)
        return self.f(t)
class ActionProtocol:
    def __call__(self, t: float) -> float:
        ...
class ActionConstant:
    def __init__(self, v):
        self.v = v
    def __call__(self, t):
        return self.v
class ActionStatus:
    _map: Dict[str, ActionProtocol]
    def __init__(self, map):
        self._map = map
    @classmethod
    def from_config(cls, cfg, default: Optional[ActionStatus] = None):
        try:
            map = {}
            for i in cfg:
                action_type = i["type"]
                if (action_type == "constant"):
                    for p in i["params"]:
                        map[p] = ActionConstant(i["value"])
                elif (action_type == "loop"):
                    values = i["value"]
                    durations = i["duration"]
                    action = ActionLoop(values, durations)
                    for p in i["params"]:
                        map[p] = action
                elif (action_type == "reset"):
                    for p in i["params"]:
                        if (default is None):
                            map[p] = ActionConstant(i["missing_default"])
                        elif (p not in default._map):
                            map[p] = ActionConstant(i["missing_default"])
                        else:
                            map[p] = default._map[p]
                elif (action_type == "random"):
                    mn, mx = i["range"]
                    dn, dx = i["duration"]
                    for p in i["params"]:
                        map[p] = ActionRand(mn, mx, dn, dx, i.get("smooth", 1))
                else:
                    raise TypeError(f"action type {action_type}")
            return cls(map)
        except:
            print(yaml.dump(cfg))
            raise
    def update(self, other: ActionStatus):
        self._map.update(other._map)


@dataclass
class VTSClientConfig:
    plugin_name: str
    developer: str
    auth_token_pth: str
    host: str
    port: int
    
    def get_plugin_info(self):
        return {
            "plugin_name": self.plugin_name,
            "developer": self.developer,
            "authentication_token_path": self.auth_token_pth
        }
    def get_vts_api_info(self):
        return {
            "version": "1.0",
            "name": "VTubeStudioPublicAPI",
            "host": self.host,
            "port": self.port
        }
    def create_client(self):
        return pyvts.vts(plugin_info=self.get_plugin_info(), vts_api_info=self.get_vts_api_info())


class AudioWithVTS:
    def __init__(self, vts: pyvts.vts, emotion_config, maxsize=1, subtitle_filename=None):
        self.param_v = dict()
        self.vts_fps = emotion_config.get("fps", 45)
        self.vts_smooth = defaultdict(lambda: 1)
        self.vts_smooth.update(emotion_config.get("smooth", {}))
        self.vts_act_default = ActionStatus.from_config(emotion_config["default"])
        self.vts_act_emo_start = {}
        self.vts_act_emo_end = {}
        for emo, emo_cfg in emotion_config["speech"].items():
            if ("on_start" in emo_cfg):
                self.vts_act_emo_start[emo] = ActionStatus.from_config(emo_cfg["on_start"], self.vts_act_default)
            if ("on_end" in emo_cfg):
                self.vts_act_emo_end[emo] = ActionStatus.from_config(emo_cfg["on_end"], self.vts_act_default)
        
        self.vts_act_curr = ActionStatus(dict(self.vts_act_default._map))
        self.vts_param_smooth = dict()
        self.vts_param_all = set()
        self.vts_param_all.update(self.vts_act_default._map.keys())
        for i in self.vts_act_emo_start.values(): self.vts_param_all.update(i._map.keys())
        for i in self.vts_act_emo_end.values(): self.vts_param_all.update(i._map.keys())

        self.vts = vts        

        self.q = asyncio.Queue(maxsize=maxsize)
        self.subtitle_filename = subtitle_filename
        self._play_task = None
        self._vts_task = None
    
    async def start(self):
        await self.vts.connect()
        await self.vts.request_authenticate_token()
        await self.vts.request_authenticate()

        vts_param_msg = await self.vts.request(self.vts.vts_request.requestTrackingParameterList())
        vts_param_avail = set()
        vts_param_avail.update(i["name"] for i in vts_param_msg["data"]["defaultParameters"])
        vts_param_avail.update(i["name"] for i in vts_param_msg["data"]["customParameters"])
        for i in self.vts_param_all:
            if (i not in vts_param_avail):
                await self.vts.request(self.vts.vts_request.requestCustomParameter(i, 0, 1, 0, i))

        self._play_task = asyncio.create_task(self.play_worker())
        self._vts_task = asyncio.create_task(self.vts_worker())
    
    async def check_exc(self):
        """检查 worker 是否有异常"""
        if (self._play_task and self._play_task.done() and self._play_task.exception()):
            raise self._play_task.exception()
        if (self._vts_task and self._vts_task.done() and self._vts_task.exception()):
            raise self._vts_task.exception()
    
    async def stop(self):
        await self.q.join()
        self._play_task.cancel()
        self._vts_task.cancel()
        try:
            await self._play_task
            await self._vts_task
        except asyncio.CancelledError:
            pass
    
    async def put(self, emotion, content, audio_fn):
        """将音频文件放入播放队列"""
        return await self.q.put((emotion, content, audio_fn))
    async def vts_worker(self):
        while (True):
            t = time.time()
            for param, fn in self.vts_act_curr._map.items():
                val = fn(t)
                if (param not in self.vts_param_smooth):
                    self.vts_param_smooth[param] = val
                self.vts_param_smooth[param] += (val-self.vts_param_smooth[param])*min(1, 1/self.vts_smooth[param]/self.vts_fps)
            params = list(self.vts_param_smooth.keys())
            values = list(self.vts_param_smooth.values())
            await self.vts.request(self.vts.vts_request.requestSetMultiParameterValue(params, values))
            await asyncio.sleep(1/self.vts_fps)

    async def play_worker(self):
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

                for _emo in ["common", emotion]:
                    if (_emo in self.vts_act_emo_start):
                        act = self.vts_act_emo_start[_emo]
                        self.vts_act_curr.update(act)
                    
                await play_file_wait_async(fn)
                
                for _emo in ["common", emotion]:
                    if (_emo in self.vts_act_emo_end):
                        act = self.vts_act_emo_end[_emo]
                        self.vts_act_curr.update(act)
            except Exception:
                self.q.task_done()
                raise
            self.q.task_done()

class TTSBackend(ABC):
    """TTS 后端抽象基类：生成音频文件并放入播放队列"""
    def __init__(self, player: AudioWithVTS, maxsize=5):
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

class IndexTTSAPIBackend(TTSBackend):
    """IndexTTS API TTS 后端实现"""
    
    def __init__(self, player: AudioWithVTS, base_url: str, voice: str,
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

@register_interface("vts_tts")
class VTSTTSInterface(Interface):
    def __init__(self, player: AudioWithVTS, tts_backend: TTSBackend):

        self.player = player
        self.tts_backend = tts_backend

    @classmethod
    def from_cfg(cls, cfg: Dict) -> "VTSTTSInterface":
        backend_type = cfg.get("tts_type", "index_tts")
        
        # 创建 QueuedPlayer
        vts = VTSClientConfig(**(cfg["vts"]["client"])).create_client()
        emo_cfg = cfg["vts"]["emotion"]
        player = AudioWithVTS(vts=vts,
                              emotion_config=emo_cfg,
                              maxsize=cfg.get("player_queue_size", 1),
                              subtitle_filename=cfg.get("subtitle_filename", "speech.txt"))

        
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
        return []
    
    async def start(self) -> None:
        await self.player.start()
        await self.tts_backend.start()
    
    async def stop(self) -> None:
        # 先停止 backend，再停止 player
        await self.tts_backend.stop()
        await self.player.stop()
    
    async def on_speech(self, speech: List[Tuple[str, str]]) -> None:
        await self.player.check_exc()
        await self.tts_backend.check_exc()
        if (self.tts_backend.q.maxsize == 0):
            await self.tts_backend.q.join()       
        for emotion, content in speech:
            
            if content:
                await self.tts_backend.put(emotion, content)

    def get_tools(self) -> List[tuple]:
        return []
    
    def get_system_prompt(self) -> str:
        return """## 语音输出
- 发言会通过 TTS 转换为语音播放，同时发言时会控制Vtube Studio控制Live2D形象的张嘴动作。
"""
