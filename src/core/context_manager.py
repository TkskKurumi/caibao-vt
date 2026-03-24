"""上下文管理器：ContextManager 类"""

from typing import List, Dict, Union, Any
from .msg import InputMsg, ResponseMsg, UniqueMsg
from .serializer import serialize_message_1to2
from .vlm_client import VLMRouter

from openai.types.chat import ChatCompletion

class ContextManager:
    """上下文管理器，管理输入消息和回复消息
    
    支持增量式更新 stage1_msgs（List[Any | ResponseMsg]）
    System prompt 通过 ResponseMsg(role="system") 添加
    """
    
    def __init__(self, system_prompt):
        self.msgs: List[Union[InputMsg, ResponseMsg]] = []
        self.unique_msgs: Dict[UniqueMsg, UniqueMsg] = {}
        
        # 增量式存储 Stage 1 的结果：List[Any | ResponseMsg]
        # 包含 system prompt（ResponseMsg(role="system")）、InputMsg 的 stage1 内容、ResponseMsg
        self.system_prompt = system_prompt
        self.stage1_msgs: List[Union[Any, ResponseMsg]] = [ResponseMsg(
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}]
            }
        )]
    
    def add_msg(self, msg: Union[InputMsg, ResponseMsg]) -> None:
        """添加消息（统一入口，增量式更新 stage1_msgs）
        
        根据消息类型调用内部逻辑：
        - InputMsg: 去重处理，追加 UniqueMsg 和 InputMsg 的内容
        - ResponseMsg: 直接追加
        """
        self.msgs.append(msg)
        
        if isinstance(msg, ResponseMsg):
            # ResponseMsg: 直接追加
            self.stage1_msgs.append(msg)
        elif isinstance(msg, InputMsg):
            # InputMsg: 处理 UniqueMsg
            for unique_msg in msg.get_unique_msgs():
                if unique_msg.should_add_to_context(self):
                    # 追加 UniqueMsg 的内容到 stage1_msgs（传入 self 作为 context_manager）
                    self.stage1_msgs.append(unique_msg.get_llm_msg(self))
                    self.unique_msgs[unique_msg] = unique_msg
            # 追加 InputMsg 的内容到 stage1_msgs
            self.stage1_msgs.append(msg.get_llm_msg(self))
    
    def get_openai_messages(self) -> List[Dict[str, Any]]:
        """返回 OpenAI API 兼容的消息列表（完整序列化）
        
        直接使用 stage1_msgs 进行 Stage 2 和 Stage 3 序列化
        """
        return serialize_message_1to2(self.stage1_msgs)
    
    def trim_by_round(self, ratio: float) -> None:
        """按对话轮次剪裁
        
        Args:
            ratio: 保留的比例（0-1），例如 0.5 表示保留 50% 的 round
        
        Round 定义：
        - 开始：消息列表开始或上一个 round 结束
        - 结束：遇到 ResponseMsg(role="assistant", content 非空)
        
        实现：清空后重新 add_msg，确保逻辑一致
        """
        if len(self.msgs) <= 1:
            return
        
        # 按 ResponseMsg(role="assistant", content 非空) 分割成 rounds
        rounds: List[List[Union[InputMsg, ResponseMsg]]] = [[self.msgs[0]]] # 第一条消息是系统提示词
        current_round: List[Union[InputMsg, ResponseMsg]] = []
        
        for msg in self.msgs[1:]:
            current_round.append(msg)
            
            # 检查是否 round 结束
            if isinstance(msg, ResponseMsg) and msg.message.role == "assistant" and msg.message.content:
                rounds.append(current_round)
                current_round = []
        
        # 处理剩余的 round（可能未完成）
        if current_round:
            rounds.append(current_round)
        
        # 计算保留的 round 数量
        keep_count = max(1, int(len(rounds) * ratio))
        
        print(f"Trim Context Round {len(rounds)} -> {keep_count}")

        # 保留最新的 round
        kept_rounds = rounds[-keep_count:]
        
        # 清空后重新构建（复用 add_msg 逻辑）
        self.msgs = []
        self.unique_msgs = {}
        self.stage1_msgs = []
        
        for round_msgs in kept_rounds:
            for msg in round_msgs:
                self.add_msg(msg)
