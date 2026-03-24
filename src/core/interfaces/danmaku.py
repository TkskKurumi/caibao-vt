"""Bilibili 弹幕 Interface"""
from __future__ import annotations
import asyncio
import http.cookies
from typing import List, Dict, Any, Optional, Tuple, Awaitable

import aiohttp
import blivedm
import blivedm.models.web as web_models

from .base import Interface, register_interface
from ..msg import InputMsg, UniqueMsg

class BiliDanmakuMsg(InputMsg):
    """Bilibili 弹幕消息"""
    def __init__(self, data, user_unique: BiliUserUniqueMsg = None):
        self.data = data
        self.user_unique = user_unique
    
    def get_llm_msg(self, context_manager = None):
        return self.data
    
    def get_unique_msgs(self):
        if (self.user_unique):
            return [self.user_unique]
        else:
            return []

class BiliUserUniqueMsg(UniqueMsg):
    """Bilibili 用户唯一标识"""
    def __init__(self, uid, username, guard_level: int = 0):
        self.uid = uid
        self.username = username
        self.guard_level = guard_level
        self.guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(guard_level, "")
    
    def get_unique_id(self):
        return f"BiliUser({self.uid})"
    
    def get_llm_msg(self, context_manager = None):
        result = {
            "type": "bili_user",
            "uid": self.uid,
            "username": self.username,
        }
        if self.guard_level > 0:
            result["guard_level"] = self.guard_level
            result["guard_name"] = self.guard_name
        return result

def bili_danmaku_to_input_msg(message: web_models.DanmakuMessage, client: blivedm.BLiveClient) -> BiliDanmakuMsg:
    """将弹幕消息转换为 BiliDanmakuMsg"""
    # DanmakuMessage 有 privilege_type 字段（0 非舰队，1 总督，2 提督，3 舰长）
    guard_level = message.privilege_type if hasattr(message, 'privilege_type') else 0
    sender = BiliUserUniqueMsg(message.uid, message.uname, guard_level) if message.uid else None
    return BiliDanmakuMsg(
        data={"type": "bili_danmaku", "sender": message.uid, "content": message.msg, "roomid": client.room_id},
        user_unique=sender
    )

def bili_gift_to_input_msg(message: web_models.GiftMessage, client: blivedm.BLiveClient) -> BiliDanmakuMsg:
    """将礼物消息转换为 BiliDanmakuMsg"""
    # GiftMessage 有 guard_level 字段（0 非舰队，1 总督，2 提督，3 舰长）
    guard_level = getattr(message, 'guard_level', 0)
    sender = BiliUserUniqueMsg(message.uid, message.uname, guard_level) if message.uid else None
    price = "free" if message.coin_type == "silver" else f"{message.total_coin/1000} CNY"
    return BiliDanmakuMsg(
        data={"type": "bili_gift", "sender": message.uid, "gift_num": message.num, "gift_name": message.gift_name, "price": price},
        user_unique=sender
    )

def bili_guard_to_input_msg(message: web_models.GuardBuyMessage | web_models.UserToastV2Message, client: blivedm.BLiveClient) -> BiliDanmakuMsg:
    """将上舰消息转换为 BiliDanmakuMsg"""
    username = getattr(message, 'username', getattr(message, 'uname', '未知用户'))
    uid = getattr(message, 'uid', 0)
    guard_level = getattr(message, 'guard_level', 0)
    sender = BiliUserUniqueMsg(uid, username, guard_level) if uid else None
    guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(guard_level, "未知")
    num = getattr(message, 'num', 0)
    price_per_unit = getattr(message, 'price', 0)
    price = f"{num * price_per_unit / 1000} CNY"
    return BiliDanmakuMsg(
        data={"type": "bili_buy_guard", "guard_name": guard_name, "price": price, "uid": uid},
        user_unique=sender
    )

def bili_superchat_to_input_msg(message: web_models.SuperChatMessage, client: blivedm.BLiveClient) -> BiliDanmakuMsg:
    """将醒目留言消息转换为 BiliDanmakuMsg"""
    # SuperChatMessage 有 guard_level 字段（0 非舰队，1 总督，2 提督，3 舰长）
    guard_level = getattr(message, 'guard_level', 0)
    sender = BiliUserUniqueMsg(message.uid, message.uname, guard_level) if message.uid else None
    price = f"{message.price} CNY"
    return BiliDanmakuMsg(
        data={"type": "bili_superchat", "sender": message.uid, "price": price, "content": message.message},
        user_unique=sender
    )

@register_interface("bili_danmaku")
class BiliDanmakuInterface(Interface):
    """Bilibili 弹幕 Interface
    
    使用 blivedm 库连接 Bilibili 直播间，收集弹幕、礼物等消息
    """
    
    def __init__(self, roomids: List[int], bili_sessdata: str = "", debug_danmaku_content: bool = False):
        """
        Args:
            roomids: 直播间 ID 列表
            bili_sessdata: Bilibili SESSDATA Cookie（可选，用于获取完整用户信息）
            debug_danmaku_content: 是否打印弹幕内容用于调试
        """
        self.roomids = roomids
        self.bili_sessdata = bili_sessdata
        self.debug_danmaku_content = debug_danmaku_content
        self._clients: List[blivedm.BLiveClient] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
    
    @classmethod
    def from_cfg(cls, cfg: Dict) -> "BiliDanmakuInterface":
        """从配置字典创建实例"""
        return cls(
            roomids=cfg.get("roomids", []),
            bili_sessdata=cfg.get("bili_sessdata", ""),
            debug_danmaku_content=cfg.get("debug_danmaku_content", False)
        )
    
    async def start(self) -> None:
        """启动弹幕客户端"""
        # 创建 aiohttp 会话
        self._session = aiohttp.ClientSession()
        
        # 设置 Cookie（如果提供了 SESSDATA）
        if self.bili_sessdata:
            cookies = http.cookies.SimpleCookie()
            cookies['SESSDATA'] = self.bili_sessdata
            cookies['SESSDATA']['domain'] = 'bilibili.com'
            self._session.cookie_jar.update_cookies(cookies)
        
        # 创建并启动客户端
        for room_id in self.roomids:
            client = blivedm.BLiveClient(room_id, session=self._session)
            handler = DanmakuHandler(self._message_queue, self.debug_danmaku_content)
            client.set_handler(handler)
            client.start()
            self._clients.append(client)
    
    async def stop(self) -> None:
        """停止并关闭所有弹幕客户端"""
        for client in self._clients:
            await client.stop_and_close()
        self._clients.clear()
        
        if self._session:
            await self._session.close()
            self._session = None
    
    async def collect_input(self) -> List[InputMsg]:
        """
        收集弹幕输入
        
        从消息队列中获取所有已转换好的 BiliDanmakuMsg
        """
        msgs = []
        while not self._message_queue.empty():
            try:
                msg: BiliDanmakuMsg = await asyncio.wait_for(self._message_queue.get(), timeout=0.001)
                msgs.append(msg)
            except asyncio.TimeoutError:
                break
        return msgs
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """弹幕 Interface 不提供工具"""
        return []
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Awaitable]]:
        """弹幕 Interface 不接受工具调用"""
        raise NotImplementedError("弹幕 Interface 不接受工具调用")
    
    def get_system_prompt(self) -> str:
        """返回弹幕的 system prompt 片段"""
        return f"""## 弹幕输入
- 监听直播间：{', '.join(str(r) for r in self.roomids)}
- 观众发送弹幕、赠送礼物、上舰
- 请优先回应礼物和superchat和上舰信息，要感谢给主播打赏的粉丝。
"""


class DanmakuHandler(blivedm.BaseHandler):
    """弹幕消息处理器
    
    将 blivedm 的消息转换为 InputMsg 后推送到队列
    """
    
    def __init__(self, message_queue: asyncio.Queue, debug_danmaku_content: bool = False):
        self._queue = message_queue
        self._debug = debug_danmaku_content
    
    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        """处理弹幕消息"""
        if self._debug:
            print(f"[DEBUG Danmaku] Room {client.room_id}: {message.uname} [{message.uid}]: {message.msg}")
        self._queue.put_nowait(bili_danmaku_to_input_msg(message, client))
    
    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        """处理礼物消息"""
        if self._debug:
            print(f"[DEBUG Gift] Room {client.room_id}: {message.uname} [{message.uid}] x{message.num} {message.gift_name} ({message.coin_type})")
        self._queue.put_nowait(bili_gift_to_input_msg(message, client))
    
    def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
        """处理心跳消息（可选，这里不推送）"""
        if self._debug:
            print(f"[DEBUG Heartbeat] Room {client.room_id}: popularity = {message.popularity}")
        pass
    
    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        """处理醒目留言（可选）"""
        if self._debug:
            print(f"[DEBUG SuperChat] Room {client.room_id}: {message.uname} [{message.uid}]: ¥{message.price/1000} {message.message}")
        self._queue.put_nowait(bili_superchat_to_input_msg(message, client))
    
    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        """处理上舰消息"""
        if self._debug:
            guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(getattr(message, 'guard_level', 0), "未知")
            print(f"[DEBUG Guard] Room {client.room_id}: {getattr(message, 'username', getattr(message, 'uname', '未知'))} [{getattr(message, 'uid', 0)}] 上舰 {guard_name} x{getattr(message, 'num', 1)}")
        self._queue.put_nowait(bili_guard_to_input_msg(message, client))
    
    def _on_user_toast_v2(self, client: blivedm.BLiveClient, message: web_models.UserToastV2Message):
        """处理上舰消息（另一种格式）"""
        if message.source != 2:  # 排除某些来源
            if self._debug:
                guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(getattr(message, 'guard_level', 0), "未知")
                print(f"[DEBUG GuardV2] Room {client.room_id}: {getattr(message, 'username', getattr(message, 'uname', '未知'))} [{getattr(message, 'uid', 0)}] 上舰 {guard_name}")
            self._queue.put_nowait(bili_guard_to_input_msg(message, client))
