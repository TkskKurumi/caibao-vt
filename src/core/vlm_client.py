"""VLM Client：封装 OpenAI API chat 调用，支持多模型路由"""
from __future__ import annotations
from typing import Dict, List, Any, Optional, Literal, Tuple
from dataclasses import dataclass
import random
import copy, time
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion


def load_vlm_router(config: Dict[str, Any]) -> VLMRouter:
    """
    从配置文件创建 VLMRouter
    
    Args:
        config: 完整的配置字典，VLM 相关配置在 config["vlm"] 中
    
    Returns:
        VLMRouter 实例
    
    配置格式示例（mapping 格式）：
    ```yaml
    vlm:
      route_policy: ordered
      models:
        localQwen120B:
          endpoint: http://192.168.31.117:8091/v1
          model: Qwen3.5-122B
          enabled: true
          priority: 1
          extra_kwargs:
            enable_thinking: false
        localQwen27B:
          endpoint: http://192.168.31.117:8090/v1
          model: Qwen3.5-27B
          enabled: true
          priority: 2
        OpenRouter:
          endpoint: https://openrouter.ai/api/v1
          model: qwen/qwen-2.5-vl-72b-instruct
          enabled: true
          priority: 100
          api_key: $env:{OPENROUTER_KEY}
    ```
    """
    vlm_config = config.get("vlm", {})
    
    route_policy = vlm_config.get("route_policy", "ordered")
    models_data = vlm_config.get("model_configs", {})  # 改为 mapping 格式
    
    # 转换为 {name: VLMConfig} 字典
    model_configs: Dict[str, VLMConfig] = {}
    for name, cfg_data in models_data.items():
        model_configs[name] = VLMConfig(
            name=name,  # 唯一名称
            endpoint=cfg_data.get("endpoint", ""),
            model=cfg_data.get("model", ""),
            enabled=cfg_data.get("enabled", True),
            api_key=cfg_data.get("api_key", ""),
            timeout=cfg_data.get("timeout", 60),
            priority=cfg_data.get("priority", 0),
            extra_kwargs=cfg_data.get("extra_kwargs", {})
        )
    
    return VLMRouter(model_configs, route_policy)


@dataclass
class VLMConfig:
    """单个 VLM 模型配置"""
    name: str             # 唯一名称，如 "localQwen120B"
    endpoint: str         # API 端点，如 "http://localhost:8090/v1"
    model: str            # 模型名称，如 "Qwen3.5-122B"
    enabled: bool = True  # 是否启用
    api_key: str = ""     # API 密钥（可选，本地部署可能不需要）
    timeout: int = 60     # 超时时间（秒）
    priority: int = 0     # 优先级（数值小优先，用于 ordered 路由）
    extra_kwargs: Dict[str, Any] = None  # 额外参数（temperature, max_tokens 等）
    
    def __post_init__(self):
        if self.extra_kwargs is None:
            self.extra_kwargs = {}


class VLMRouter:
    """
    VLM 路由管理器
    
    支持两种路由策略：
    1. ordered: 按优先级依次尝试，失败时调用下一个
    2. balanced: 负载均衡，每次调用时随机打乱相同优先级的模型，然后按 ordered 逻辑
    """
    
    def __init__(self, model_configs: Dict[str, VLMConfig], route_policy: Literal["ordered", "balanced"] = "ordered"):
        """
        Args:
            model_configs: 模型配置字典 {name: VLMConfig}
            route_policy: 路由策略（"ordered" 或 "balanced"）
        """
        self.route_policy = route_policy
        self._configs: Dict[str, VLMConfig] = {}
        self._clients: Dict[str, VLMClient] = {}
        
        # 只启用 enabled 的模型
        for name, config in model_configs.items():
            if config.enabled:
                self._configs[name] = config
                self._clients[name] = VLMClient(config)
    
    def _get_sorted_models(self) -> List[str]:
        """
        获取排序后的模型名称列表
        
        如果是 balanced 模式，相同优先级的模型会随机打乱
        """
        # 按优先级分组
        groups: Dict[int, List[str]] = {}
        for name, config in self._configs.items():
            priority = config.priority
            if priority not in groups:
                groups[priority] = []
            groups[priority].append(name)
        
        # 对每个优先级组内处理
        result: List[str] = []
        sorted_priorities = sorted(groups.keys())
        
        for priority in sorted_priorities:
            group = groups[priority]
            if self.route_policy == "balanced":
                # balanced 模式：每次调用都随机打乱
                random.shuffle(group)
            result.extend(group)
        
        return result
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        start_index: int = 0
    ) -> Tuple[Optional[openai.types.chat.ChatCompletion], int]:
        """
        尝试调用 VLM 进行聊天，按路由策略依次尝试
        
        Args:
            messages: OpenAI 格式的消息列表
            tools: 工具描述列表（可选）
            start_index: 从第几个模型开始尝试（用于递归调用）
        
        Returns:
            (ChatCompletion 对象或 None, 下一个尝试的索引)
            如果成功返回 (result, index)，失败返回 (None, index + 1)
        """
        sorted_models = self._get_sorted_models()
        
        for i in range(start_index, len(sorted_models)):
            model_name = sorted_models[i]
            client = self._clients[model_name]
            try:
                result = client.chat(messages, tools)
                return result, i
            except Exception as e:
                print(f"VLM {model_name} 调用失败：{e}")
                continue
        
        return None, len(sorted_models)
    
    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        start_index: int = 0
    ) -> Tuple[Optional[ChatCompletion], int]:
        """
        异步尝试调用 VLM 进行聊天
        
        Args:
            messages: OpenAI 格式的消息列表
            tools: 工具描述列表（可选）
            start_index: 从第几个模型开始尝试
        
        Returns:
            (ChatCompletion 对象或 None, 下一个尝试的索引)
        """
        sorted_models = self._get_sorted_models()
        
        for i in range(start_index, len(sorted_models)):
            model_name = sorted_models[i]
            client = self._clients[model_name]
            try:
                result = await client.chat_async(messages, tools)
                return result, i
            except Exception as e:
                print(f"VLM {model_name} 异步调用失败：{e}")
                continue
        
        return None, len(sorted_models)


class VLMClient:
    """
    封装 OpenAI API chat 调用的客户端
    
    API 简化：只接受 messages 和 tools 参数，其他参数从配置读取
    同时支持同步和异步调用
    """
    
    def __init__(self, config: VLMConfig):
        """
        Args:
            config: VLMConfig 配置对象
        """
        self.config = config
        self._sync_client = openai.OpenAI(
            base_url=config.endpoint,
            api_key=config.api_key or "",
            timeout=config.timeout
        )
        self._async_client = AsyncOpenAI(
            base_url=config.endpoint,
            api_key=config.api_key or "",
            timeout=config.timeout
        )
        self._model = config.model  # 实际使用的模型名称
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatCompletion:
        """
        同步调用 VLM 进行聊天
        
        Args:
            messages: OpenAI 格式的消息列表
            tools: 工具描述列表（可选）
        
        Returns:
            ChatCompletion 对象
        """
        # 使用配置中的 extra_kwargs
        kwargs = copy.deepcopy(self.config.extra_kwargs)
        
        return self._sync_client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            **kwargs
        )
    
    async def chat_async(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatCompletion:
        """
        异步调用 VLM 进行聊天
        
        Args:
            messages: OpenAI 格式的消息列表
            tools: 工具描述列表（可选）
        
        Returns:
            ChatCompletion 对象
        """
        # 使用配置中的 extra_kwargs
        kwargs = copy.deepcopy(self.config.extra_kwargs)
        
        if (False): # need a configurable flag to toggle debug here in future
            msgs_str = str(messages)
            if (len(msgs_str) > 1000):
                msgs_str = msgs_str[:1000] + "..."
            print(msgs_str)

        t = time.time()
        ret = await self._async_client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            **kwargs
        )

        if (True): # need a configurable flag to toggle debug in future
            elapse = time.time() - t
            print(f"VLM chat request used {elapse:.1f} seconds")
        return ret
