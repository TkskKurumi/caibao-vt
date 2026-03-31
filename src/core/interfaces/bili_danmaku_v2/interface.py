"""BiliDanmakuInterfaceV2 - Bilibili 弹幕 Interface v2"""
import asyncio
import http.cookies
from typing import List, Dict, Any, Optional, Tuple, Union
import aiohttp
import blivedm
import blivedm.models.web as web_models
from bilibili_api import Credential

from ..base import Interface, register_interface
from .msg import BiliDanmakuMsg
from .converter import DanmakuConverter
from .fetcher import BiliUserFetcher

# blivedm 消息类型别名
BlivedmMessage = Union[
    web_models.DanmakuMessage,
    web_models.GiftMessage,
    web_models.GuardBuyMessage,
    web_models.SuperChatMessage,
    web_models.UserToastV2Message
]


class DanmakuHandler(blivedm.BaseHandler):
    """弹幕消息处理器（sync）
    
    只负责将 blivedm 原始消息 + client 放入 queue，不进行转换
    """
    
    def __init__(self, message_queue: asyncio.Queue, debug: bool = False):
        self._queue = message_queue
        self._debug = debug
    
    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        """处理弹幕消息（sync）"""
        if self._debug:
            print(f"[DEBUG Danmaku] Room {client.room_id}: {message.uname} [{message.uid}]: {message.msg}")
        self._queue.put_nowait((message, client))
    
    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        """处理礼物消息（sync）"""
        if self._debug:
            print(f"[DEBUG Gift] Room {client.room_id}: {message.uname} [{message.uid}] x{message.num} {message.gift_name}")
        self._queue.put_nowait((message, client))
    
    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        """处理醒目留言（sync）"""
        if self._debug:
            print(f"[DEBUG SuperChat] Room {client.room_id}: {message.uname} [{message.uid}]: ¥{message.price/1000}")
        self._queue.put_nowait((message, client))
    
    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        """处理上舰消息（sync）"""
        if self._debug:
            print(f"[DEBUG Guard] Room {client.room_id}: {getattr(message, 'username', '未知')} [{getattr(message, 'uid', 0)}]")
        self._queue.put_nowait((message, client))
    
    def _on_user_toast_v2(self, client: blivedm.BLiveClient, message: web_models.UserToastV2Message):
        """处理上舰消息（UserToastV2 格式，sync）"""
        if message.source != 2:  # 排除某些来源
            if self._debug:
                print(f"[DEBUG GuardV2] Room {client.room_id}: {getattr(message, 'username', '未知')} [{getattr(message, 'uid', 0)}]")
            self._queue.put_nowait((message, client))


@register_interface("bili_danmaku_v2")
class BiliDanmakuInterfaceV2(Interface):
    """Bilibili 弹幕 Interface v2
    
    使用 blivedm 库连接 Bilibili 直播间，收集弹幕、礼物等消息
    """
    
    def __init__(self, roomids: List[int], bili_sessdata: str = "", 
                 debug_danmaku_content: bool = False,
                 fetch_user_info: bool = False,
                 fetch_user_avatar: bool = False,
                 user_info_cache_size: int = 100,
                 user_avatar_cache_size: int = 50,
                 user_max_concurrent: int = 5,
                 debug_bili_user: bool = False):
        """
        Args:
            roomids: 直播间 ID 列表
            bili_sessdata: Bilibili SESSDATA Cookie（可选，用于获取用户信息）
            debug_danmaku_content: 是否打印弹幕内容用于调试
            fetch_user_info: 是否获取用户信息（昵称、性别等）
            fetch_user_avatar: 是否获取用户头像（PIL Image）
            user_info_cache_size: 用户信息缓存大小
            user_avatar_cache_size: 用户头像缓存大小
            user_max_concurrent: 获取用户信息/头像的最大并发数
            debug_bili_user: 是否打印用户信息获取的 debug 信息
        """
        self.roomids = roomids
        self.bili_sessdata = bili_sessdata
        self.debug_danmaku_content = debug_danmaku_content
        self.fetch_user_info = fetch_user_info
        self.fetch_user_avatar = fetch_user_avatar
        self.user_info_cache_size = user_info_cache_size
        self.user_avatar_cache_size = user_avatar_cache_size
        self.user_max_concurrent = user_max_concurrent
        self.debug_bili_user = debug_bili_user
        
        # 内部状态
        self._clients: List[blivedm.BLiveClient] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._fetcher: Optional[BiliUserFetcher] = None
        self._converter: Optional[DanmakuConverter] = None
    
    @classmethod
    def from_cfg(cls, cfg: Dict) -> "BiliDanmakuInterfaceV2":
        """从配置字典创建实例"""
        return cls(
            roomids=cfg.get("roomids", []),
            bili_sessdata=cfg.get("bili_sessdata", ""),
            debug_danmaku_content=cfg.get("debug_danmaku_content", False),
            fetch_user_info=cfg.get("fetch_user_info", False),
            fetch_user_avatar=cfg.get("fetch_user_avatar", False),
            user_info_cache_size=cfg.get("user_info_cache_size", 100),
            user_avatar_cache_size=cfg.get("user_avatar_cache_size", 50),
            user_max_concurrent=cfg.get("user_max_concurrent", 5),
            debug_bili_user=cfg.get("debug_bili_user", False)
        )
    
    async def start(self) -> None:
        """启动弹幕客户端
        
        1. 创建 Credential 对象
        2. 初始化用户信息/头像获取器（传入 Credential）
        3. 创建转换器（传入 fetcher）
        4. 创建 aiohttp 会话
        5. 启动 blivedm 客户端
        """
        # 1. 创建 Credential 对象
        credential = None
        if self.bili_sessdata:
            credential = Credential(sessdata=self.bili_sessdata)
        
        # 2. 初始化用户信息/头像获取器
        if self.fetch_user_info or self.fetch_user_avatar:
            if credential is None:
                print("[BiliDanmakuInterfaceV2] 警告：fetch_user_info/fetch_user_avatar 为 true，但未提供 bili_sessdata")
            else:
                self._fetcher = BiliUserFetcher(
                    credential=credential,
                    info_cache_size=self.user_info_cache_size,
                    avatar_cache_size=self.user_avatar_cache_size,
                    max_concurrent=self.user_max_concurrent,
                    debug=self.debug_bili_user
                )
                await self._fetcher.initialize()
        
        # 3. 创建转换器
        self._converter = DanmakuConverter(
            fetcher=self._fetcher,
            fetch_user_info=self.fetch_user_info,
            fetch_user_avatar=self.fetch_user_avatar
        )
        
        # 4. 创建 aiohttp 会话
        self._session = aiohttp.ClientSession()
        
        # 5. 设置 Cookie（如果提供了 SESSDATA）
        if self.bili_sessdata:
            cookies = http.cookies.SimpleCookie()
            cookies['SESSDATA'] = self.bili_sessdata
            cookies['SESSDATA']['domain'] = 'bilibili.com'
            self._session.cookie_jar.update_cookies(cookies)
        
        # 6. 创建并启动 blivedm 客户端
        for room_id in self.roomids:
            client = blivedm.BLiveClient(room_id, session=self._session)
            handler = DanmakuHandler(self._message_queue, self.debug_danmaku_content)
            client.set_handler(handler)
            client.start()
            self._clients.append(client)
    
    async def stop(self) -> None:
        """停止并关闭所有客户端"""
        # 停止 blivedm 客户端
        for client in self._clients:
            await client.stop_and_close()
        self._clients.clear()
        
        # 关闭 aiohttp 会话
        if self._session:
            await self._session.close()
            self._session = None
        
        # 关闭 fetcher
        if self._fetcher:
            await self._fetcher.close()
            self._fetcher = None
    
    async def collect_input(self) -> List[BiliDanmakuMsg]:
        """收集弹幕输入（async 消息转换）
        
        1. 从 queue 中获取所有 (blivedm_message, client) 元组
        2. 异步转换为 BiliDanmakuMsg
        3. 返回转换后的消息列表
        """
        msgs = []
        
        # 1. 从 queue 中获取所有原始消息
        raw_messages = []
        while not self._message_queue.empty():
            try:
                raw = await asyncio.wait_for(self._message_queue.get(), timeout=0.001)
                raw_messages.append(raw)
            except asyncio.TimeoutError:
                break

        tasks = []
        for blivedm_message, client in raw_messages:
            try:
                tasks.append(asyncio.create_task(self._converter.convert_blivedm2input_msg(client, blivedm_message)))                
            except Exception as e:
                print(f"[BiliDanmakuInterfaceV2] 消息转换失败：{e}")
        msgs = await asyncio.gather(*tasks, return_exceptions=False)
        return msgs
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """弹幕 Interface 不提供工具"""
        return []
    
    def get_system_prompt(self) -> str:
        """返回弹幕的 system prompt 片段"""
        return f"""## 弹幕输入
- 监听直播间：{', '.join(str(r) for r in self.roomids)}
- 观众发送弹幕、赠送礼物、上舰
- 请优先回应礼物和 superchat 和上舰信息，要感谢给主播打赏的粉丝。
"""
