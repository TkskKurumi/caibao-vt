"""消息管理：Msg、InputMsg、ResponseMsg、UniqueMsg 抽象基类"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .context_manager import ContextManager


# ============================================================================
# UniqueMsg 基类
# ============================================================================

class UniqueMsg(ABC):
    """唯一消息，支持去重
    
    使用 get_unique_id() 实现 __hash__ 和 __eq__：
    - __hash__ 使用 get_unique_id() 的哈希值
    - __eq__ 检查类型相同且 get_unique_id() 相同
    """
    
    @abstractmethod
    def get_unique_id(self) -> str:
        """子类必须实现，返回唯一标识符"""
        pass
    
    def __hash__(self) -> int:
        """使用 get_unique_id() 实现哈希"""
        return hash(self.get_unique_id())
    
    def __eq__(self, other: Any) -> bool:
        """检查类型相同且 get_unique_id() 相同"""
        if not isinstance(other, UniqueMsg):
            return False
        if type(self) != type(other):
            return False
        return self.get_unique_id() == other.get_unique_id()
    
    @abstractmethod
    def get_llm_msg(self, context_manager: "ContextManager" = None) -> Any:
        """返回消息内容（任意格式，由子类决定）
        
        Args:
            context_manager: 可选，用于动态判断（如 UniqueMemory 的 updated 标志）
        """
        pass
    
    def should_add_to_context(self, context_manager: "ContextManager") -> bool:
        """决定是否将该消息添加到上下文
        
        默认实现：如果消息不在 context_manager.unique_msgs 中，则添加
        子类可以重写此方法以实现自定义逻辑
        """
        return self not in context_manager.unique_msgs


# ============================================================================
# Msg 基类
# ============================================================================

class Msg(ABC):
    """消息基类
    
    所有消息都从此类派生，分为 InputMsg 和 ResponseMsg 两类
    """
    
    @abstractmethod
    def get_llm_msg(self, context_manager: "ContextManager" = None) -> Any:
        """返回消息内容（任意格式，由子类决定）
        
        Args:
            context_manager: 可选，用于动态判断
        """
        pass
    
    @abstractmethod
    def get_unique_msgs(self) -> List[UniqueMsg]:
        """返回唯一消息列表（用于去重）
        
        ResponseMsg 返回空列表，因为不需要去重
        """
        pass


# ============================================================================
# InputMsg 抽象基类
# ============================================================================

class InputMsg(Msg):
    """输入消息抽象基类
    
    所有 Interface 的输入消息都从此类派生
    """
    
    @abstractmethod
    def get_llm_msg(self, context_manager: "ContextManager" = None) -> Any:
        """返回输入消息内容"""
        pass


# ============================================================================
# ResponseMsg 类
# ============================================================================

from openai.types.chat import ChatCompletionMessage

class ResponseMsg(Msg):
    """LLM 回复消息
    
    直接存储 OpenAI 的 ChatCompletionMessage 对象
    不需要去重，get_unique_msgs() 返回空列表
    """
    
    def __init__(self, message: ChatCompletionMessage):
        """
        Args:
            message: OpenAI 的 ChatCompletionMessage 对象
                   包含 role, content, tool_calls 等字段
        """
        self.message = message
    
    def get_llm_msg(self, context_manager: "ContextManager" = None) -> ChatCompletionMessage:
        """直接返回 ChatCompletionMessage 对象
        
        在 stage2 序列化时，OpenAI 库会自动处理
        """
        return self.message
    
    def get_unique_msgs(self) -> List[UniqueMsg]:
        """ResponseMsg 不需要去重"""
        return []