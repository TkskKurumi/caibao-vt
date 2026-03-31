"""DanmakuConverter - 弹幕消息转换器（async）"""
from typing import Optional, Union
import blivedm
import blivedm.models.web as web_models

from ...msg import InputMsg
from .msg import BiliDanmakuMsg, BiliUserUniqueMsg
from .fetcher import BiliUserFetcher


class DanmakuConverter:
    """弹幕消息转换器（async）
    
    fetcher 作为成员变量，在初始化时传入
    """
    
    def __init__(self, fetcher: BiliUserFetcher,
                 fetch_user_info: bool = False,
                 fetch_user_avatar: bool = False):
        self._fetcher = fetcher
        self._fetch_user_info = fetch_user_info
        self._fetch_user_avatar = fetch_user_avatar
    
    async def convert_blivedm2input_msg(
        self, 
        client: blivedm.BLiveClient, 
        blivedm_message: Union[
            web_models.DanmakuMessage,
            web_models.GiftMessage,
            web_models.GuardBuyMessage,
            web_models.SuperChatMessage,
            web_models.UserToastV2Message
        ]
    ) -> InputMsg:
        """
        将 blivedm 消息转换为 InputMsg（共用入口）
        
        Args:
            client: blivedm 客户端
            blivedm_message: blivedm 消息对象
            
        Returns:
            InputMsg 对象（BiliDanmakuMsg）
        """
        # 根据 isinstance 切换转换方式
        if isinstance(blivedm_message, web_models.DanmakuMessage):
            return await self._convert_danmaku(client, blivedm_message)
        elif isinstance(blivedm_message, web_models.GiftMessage):
            return await self._convert_gift(client, blivedm_message)
        elif isinstance(blivedm_message, web_models.GuardBuyMessage):
            return await self._convert_guard(client, blivedm_message)
        elif isinstance(blivedm_message, web_models.SuperChatMessage):
            return await self._convert_superchat(client, blivedm_message)
        elif isinstance(blivedm_message, web_models.UserToastV2Message):
            return await self._convert_user_toast_v2(client, blivedm_message)
        else:
            raise ValueError(f"Unknown message type: {type(blivedm_message)}")
    
    async def _convert_danmaku(self, client: blivedm.BLiveClient, 
                                message: web_models.DanmakuMessage) -> BiliDanmakuMsg:
        """转换弹幕消息"""
        guard_level = message.privilege_type
        user_unique = await self._create_user_unique(
            message.uid, message.uname, guard_level, message.face
        )
        return BiliDanmakuMsg(
            data={
                "type": "bili_danmaku",
                "sender": message.uid,
                "content": message.msg,
                "roomid": client.room_id
            },
            user_unique=user_unique
        )
    
    async def _convert_gift(self, client: blivedm.BLiveClient,
                             message: web_models.GiftMessage) -> BiliDanmakuMsg:
        """转换礼物消息"""
        guard_level = getattr(message, 'guard_level', 0)
        user_unique = await self._create_user_unique(
            message.uid, message.uname, guard_level, getattr(message, 'face', '')
        )
        price = "free" if message.coin_type == "silver" else f"{message.total_coin/1000} CNY"
        return BiliDanmakuMsg(
            data={
                "type": "bili_gift",
                "sender": message.uid,
                "gift_num": message.num,
                "gift_name": message.gift_name,
                "price": price
            },
            user_unique=user_unique
        )
    
    async def _convert_guard(self, client: blivedm.BLiveClient,
                              message: web_models.GuardBuyMessage) -> BiliDanmakuMsg:
        """转换上舰消息（GuardBuyMessage）"""
        username = getattr(message, 'username', '')
        uid = getattr(message, 'uid', 0)
        guard_level = getattr(message, 'guard_level', 0)
        user_unique = await self._create_user_unique(uid, username, guard_level, '')
        guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(guard_level, "未知")
        num = getattr(message, 'num', 0)
        price_per_unit = getattr(message, 'price', 0)
        price = f"{num * price_per_unit / 1000} CNY"
        return BiliDanmakuMsg(
            data={
                "type": "bili_buy_guard",
                "guard_name": guard_name,
                "price": price,
                "uid": uid
            },
            user_unique=user_unique
        )
    
    async def _convert_superchat(self, client: blivedm.BLiveClient,
                                  message: web_models.SuperChatMessage) -> BiliDanmakuMsg:
        """转换醒目留言"""
        guard_level = getattr(message, 'guard_level', 0)
        user_unique = await self._create_user_unique(
            message.uid, message.uname, guard_level, getattr(message, 'face', '')
        )
        price = f"{message.price} CNY"
        return BiliDanmakuMsg(
            data={
                "type": "bili_superchat",
                "sender": message.uid,
                "price": price,
                "content": message.message
            },
            user_unique=user_unique
        )
    
    async def _convert_user_toast_v2(self, client: blivedm.BLiveClient,
                                      message: web_models.UserToastV2Message) -> BiliDanmakuMsg:
        """转换上舰消息（UserToastV2 格式）"""
        username = getattr(message, 'username', getattr(message, 'uname', '未知用户'))
        uid = getattr(message, 'uid', 0)
        guard_level = getattr(message, 'guard_level', 0)
        user_unique = await self._create_user_unique(uid, username, guard_level, '')
        guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(guard_level, "未知")
        num = getattr(message, 'num', 0)
        price_per_unit = getattr(message, 'price', 0)
        price = f"{num * price_per_unit / 1000} CNY"
        return BiliDanmakuMsg(
            data={
                "type": "bili_buy_guard",
                "guard_name": guard_name,
                "price": price,
                "uid": uid
            },
            user_unique=user_unique
        )
    
    async def _create_user_unique(
        self, uid: int, username: str, guard_level: int, face_url_from_blivedm: str
    ) -> Optional[BiliUserUniqueMsg]:
        """创建用户唯一标识（异步获取用户信息/头像）
        
        调用顺序：
        1. 如果需要用户信息，先调用 get_user_info 获取 face_url
        2. 如果需要头像，再调用 get_user_avatar 获取 PIL.Image
        """
        if uid is None or uid <= 0:
            return None
        
        # 默认值
        gender = ""
        sign = ""
        face_url = face_url_from_blivedm
        face_image = None
        
        # 1. 如果需要用户信息，先调用 get_user_info
        if self._fetcher and self._fetch_user_info:
            info = await self._fetcher.get_user_info(uid)
            if info:
                username = info["username"]
                gender = info["gender"]
                sign = info["sign"]
                face_url = info["face_url"]
        
        # 2. 如果需要头像，再调用 get_user_avatar
        if self._fetch_user_avatar:
            if (face_url):
                face_image = await self._fetcher.get_user_avatar(uid, face_url)
            else:
                face_url = await self._fetcher.get_user_info(uid)["face_url"]
                face_image = await self._fetcher.get_user_avatar(uid, face_url)

        
        return BiliUserUniqueMsg(uid, username, guard_level, face_image, gender, sign)
