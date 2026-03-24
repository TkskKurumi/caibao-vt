"""Interface 抽象基类"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Awaitable, Optional, Tuple, Callable, Type
from ..oai_tool import OAIFunction
from ..msg import InputMsg
import asyncio

# Interface 注册表：name -> Interface 类
_INTERFACE_REGISTRY: Dict[str, Callable] = {}


def register_interface(name: str):
    """
    Interface 注册装饰器
    
    用法：
    ```python
    @register_interface("bili_danmaku")
    class BiliDanmakuInterface(Interface):
        pass
    ```
    """
    def decorator(cls: type):
        _INTERFACE_REGISTRY[name] = cls
        return cls
    return decorator


def get_interface_class(name: str) -> Type[Interface]:
    """根据名称获取 Interface 类"""
    return _INTERFACE_REGISTRY.get(name)


class Interface(ABC):
    """Interface 抽象基类
    
    所有模块（STT、Game、Danmaku、Avatar、Memory）都继承自此类
    """
    @classmethod
    @abstractmethod
    def from_cfg(cls, cfg) -> Interface:
        pass

    def get_tools(self) -> List[Tuple[OAIFunction, Callable[..., Awaitable]]]:
        """
        返回该 Interface 提供的工具描述
        
        Visual LLM 不使用工具时返回空列表
        """
        return []
    
    
    async def start(self) -> None:
        """
        启动 Interface（如连接弹幕服务器、启动录音等）
        
        可选实现，子类可选择是否提供
        """
        pass
    
    async def stop(self) -> None:
        """
        停止 Interface（如断开连接、停止录音等）
        
        可选实现，子类可选择是否提供
        """
        pass
    
    def get_system_prompt(self) -> str:
        """
        返回该 Interface 的 system prompt 片段
        
        该片段将被插入到主 system prompt 的 $interface_system_message 占位符处。
        需要向 VLM 解释：
        - 该 Interface 会提供什么类型的输入消息
        - 消息的格式和意义
        - 该 Interface 支持什么工具（如果有）
        
        可选实现，子类可选择是否提供
        
        返回格式示例：
        ```
        ## 弹幕输入
        - 监听直播间：209729
        - 观众发送弹幕、赠送礼物、上舰
        - 弹幕消息格式：{"type": "bili_danmaku", "sender": uid, "content": str, "roomid": int}
        - 礼物消息格式：{"type": "bili_gift", "sender": uid, "gift_num": int, "gift_name": str, "price": str}
        - 上舰消息格式：{"type": "bili_buy_guard", "guard_name": str, "price": str, "uid": int}
        ```
        """
        return ""
    
    async def on_speech(self, speech: List[Dict[str, Any]]) -> Awaitable:
        """
        发言时通知，返回 awaitable
        
        可选实现，子类可选择是否监听
        实现中应等待发言完成（如 TTS 播放完毕）
        """
        pass
    
    def add_to_buffer(self, data: Dict[str, Any]) -> None:
        """
        将数据加入暂存区，供下次循环使用
        
        用于反馈错误信息、游戏状态等
        """
        if not hasattr(self, "_buffer"):
            self._buffer: List[Dict[str, Any]] = []
        self._buffer.append(data)
    
    def get_buffer(self) -> List[Dict[str, Any]]:
        """获取暂存区内容并清空"""
        buffer = getattr(self, "_buffer", [])
        self._buffer = []
        return buffer
    @abstractmethod
    async def collect_input(self) -> List[InputMsg]:
        pass
    async def run_in_threadpool(self, func: callable, *args, **kwargs) -> Any:
        """
        在线程池中运行同步函数
        
        使用 asyncio.to_thread 包装同步操作
        """
        return await asyncio.to_thread(func, *args, **kwargs)