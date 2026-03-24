import time
from .base import Interface, register_interface
from ..msg import InputMsg
class HeatbeatMsg(InputMsg):
    def __init__(self, content):
        self.content = content
    def get_llm_msg(self, context_manager = None):
        return [self.content]
    def get_unique_msgs(self):
        return []
    
@register_interface("heartbeat")
class HeatbeatInterface(Interface):
    @classmethod
    def from_cfg(cls, cfg: dict):
        return cls(cfg.get("interval", 5))
    def get_system_prompt(self):
        return """
## 心跳消息
格式: {"type": "heartbeat", "time": 时间戳}
无实际意义，定期发送。

"""
    def __init__(self, interval=5):
        self.last_t = 0
        self.interval = interval
    async def collect_input(self):
        if (time.time() >= self.last_t + self.interval):
            self.last_t = time.time()
            return [HeatbeatMsg({"type": "heartbeat", "time": time.time()})]
        else:
            return []
    async def on_speech(self, speech):
        print(speech)
        return

