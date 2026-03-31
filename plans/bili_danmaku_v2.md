# BiliDanmakuInterface v2 设计文档

## 概述

v2 版本对现有 BiliDanmakuInterface 进行重构，主要改进：
1. **模块分离**：将消息转换、用户信息获取、Interface 主体等模块分开
2. **支持用户头像**：通过 bilibili_api 获取用户头像（配置项可选）
3. **缓存管理**：用户信息缓存（dict）和用户头像缓存（PIL Image）由同一个 Fetcher 管理
4. **并发控制**：限制获取用户信息/头像的并发数
5. **异步转换**：消息转换在 collect_input 时进行（async），Handler 只放原始 blivedm 消息（sync）

## 模块结构

```
src/core/interfaces/bili_danmaku_v2/
├── __init__.py              # 导出 BiliDanmakuInterfaceV2
├── interface.py             # Interface 主体（连接管理、生命周期、collect_input）
├── converter.py             # 消息转换（async，blivedm 消息 -> InputMsg）
├── fetcher.py               # 用户信息/头像获取（bilibili_api + 双缓存）
└── msg.py                   # 消息类（BiliDanmakuMsg, BiliUserUniqueMsg）
```

## 配置文件格式

```yaml
interfaces:
  bili_danmaku:
    type: bili_danmaku_v2
    roomids: [209729]
    bili_sessdata: "$env:{BILI_SESSDATA}"
    debug_danmaku_content: false
    fetch_user_info: true       # 是否获取用户信息（昵称、性别等）
    fetch_user_avatar: true     # 是否获取用户头像（PIL Image）
    user_info_cache_size: 100   # 用户信息缓存大小
    user_avatar_cache_size: 50  # 用户头像缓存大小（PIL Image 占用内存较大）
    user_max_concurrent: 5      # 获取用户信息/头像的最大并发数
```

## 核心设计思路

### 为什么消息转换在 collect_input 中进行？

1. **blivedm 库的限制**：`DanmakuHandler._on_xxx` 必须是同步函数
2. **用户信息获取是 async**：需要调用 bilibili_api 进行网络请求
3. **解决方案**：
   - Handler 中只把 blivedm 原始消息对象 + client 放入 queue（sync）
   - collect_input 中进行 async 消息转换

### 数据流

```
blivedm 事件
    ↓
DanmakuHandler._on_xxx (sync)
    ↓
queue.put((blivedm_message, client))
    ↓
asyncio.Queue
    ↓
collect_input (async)
    ↓
DanmakuConverter.convert_blivedm2input_msg (async)
    ↓
BiliDanmakuMsg (包含用户信息/头像)
```

## blivedm 消息类型

根据 `blivedm/models/web.py`，需要处理的消息类型：

```python
from blivedm.models.web import (
    DanmakuMessage,      # 弹幕消息
    GiftMessage,         # 礼物消息
    GuardBuyMessage,     # 上舰消息
    SuperChatMessage,    # 醒目留言
    UserToastV2Message,  # 上舰消息（另一种格式）
)
```

## 模块详细设计

### 1. msg.py - 消息类

```python
from typing import List, Dict, Any, Optional
from PIL.Image import Image
from ..msg import InputMsg, UniqueMsg

class BiliUserUniqueMsg(UniqueMsg):
    """Bilibili 用户唯一标识"""
    
    def __init__(self, uid: int, username: str, guard_level: int = 0, 
                 face_url: str = "", face_image: Image = None,
                 gender: str = "", sign: str = ""):
        self.uid = uid
        self.username = username
        self.guard_level = guard_level
        self.face_url = face_url
        self.face_image = face_image
        self.gender = gender
        self.sign = sign
        self.guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(guard_level, "")
    
    def get_unique_id(self) -> str:
        return f"BiliUser({self.uid})"
    
    def get_llm_msg(self, context_manager = None) -> Dict[str, Any]:
        # 返回用户信息，包含头像 URL 或 ImageObject
        pass


class BiliDanmakuMsg(InputMsg):
    """Bilibili 弹幕消息"""
    
    def __init__(self, data: Dict[str, Any], user_unique: BiliUserUniqueMsg = None):
        self.data = data
        self.user_unique = user_unique
    
    def get_llm_msg(self, context_manager = None) -> Dict[str, Any]:
        return self.data
    
    def get_unique_msgs(self) -> List[UniqueMsg]:
        return [self.user_unique] if self.user_unique else []
```

### 2. fetcher.py - 用户信息/头像获取（双缓存）

```python
import asyncio
from typing import Dict, Optional
from PIL.Image import Image
from bilibili_api import Credential
import aiohttp

class BiliUserFetcher:
    """B 站用户信息/头像获取器（双缓存）
    
    管理两份缓存：
    1. 用户信息缓存：uid -> {username, gender, sign, face_url, ...}
    2. 用户头像缓存：uid -> PIL.Image
    
    注意：
    - 使用 Credential 对象而不是 sessdata 字符串
    - 两个缓存使用不同的锁，避免死锁
    - get_user_avatar 需要 face_url 作为参数，由调用者提供
    """
    
    def __init__(self, credential: Credential, 
                 info_cache_size: int = 100, 
                 avatar_cache_size: int = 50,
                 max_concurrent: int = 5):
        # 初始化缓存、锁、信号量、aiohttp session
        # self._credential = credential
        # self._info_cache: Dict[int, Dict] = {}
        # self._avatar_cache: Dict[int, Image] = {}
        # self._info_lock = asyncio.Lock()
        # self._avatar_lock = asyncio.Lock()
        # self._semaphore = asyncio.Semaphore(max_concurrent)
        pass
    
    async def get_user_info(self, uid: int) -> Dict[str, Any]:
        """获取用户信息（带缓存）
        
        Args:
            uid: 用户 ID
            
        Returns:
            用户信息字典，包含 username, gender, sign, face_url 等
        """
        # 1. 检查缓存（使用 info_lock）
        # 2. 如果不在缓存，限制并发获取
        # 3. 更新缓存
        pass
    
    async def get_user_avatar(self, uid: int, face_url: str) -> Optional[Image]:
        """获取用户头像（带缓存）
        
        注意：需要 face_url 作为参数，由调用者提供
        如果调用者没有 face_url，应先调用 get_user_info 获取
        
        Args:
            uid: 用户 ID
            face_url: 头像 URL（从用户信息中获取）
            
        Returns:
            PIL.Image 对象，失败返回 None
        """
        # 1. 检查缓存（使用 avatar_lock）
        # 2. 如果不在缓存，限制并发下载
        # 3. 更新缓存
        pass
    
    async def _fetch_user_info(self, uid: int) -> Dict[str, Any]:
        """调用 bilibili_api 获取用户信息"""
        pass
    
    async def _fetch_user_avatar(self, face_url: str) -> Optional[Image]:
        """下载头像图片为 PIL.Image"""
        pass
    
    async def close(self) -> None:
        """关闭 aiohttp session"""
        pass
```

### 3. converter.py - 消息转换（async）

```python
from typing import Optional, Union
import blivedm
import blivedm.models.web as web_models
from ..msg import InputMsg
from .fetcher import BiliUserFetcher

class DanmakuConverter:
    """弹幕消息转换器（async）
    
    fetcher 作为成员变量，在初始化时传入
    """
    
    def __init__(self, fetcher: Optional[BiliUserFetcher] = None,
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
    
    async def _convert_danmaku(self, client, message) -> InputMsg:
        """转换弹幕消息"""
        pass
    
    async def _convert_gift(self, client, message) -> InputMsg:
        """转换礼物消息"""
        pass
    
    async def _convert_guard(self, client, message) -> InputMsg:
        """转换上舰消息"""
        pass
    
    async def _convert_superchat(self, client, message) -> InputMsg:
        """转换醒目留言"""
        pass
    
    async def _convert_user_toast_v2(self, client, message) -> InputMsg:
        """转换上舰消息（UserToastV2 格式）"""
        pass
    
    async def _create_user_unique(
        self, uid: int, username: str, guard_level: int, face_url_from_blivedm: str
    ) -> Optional[BiliUserUniqueMsg]:
        """创建用户唯一标识（异步获取用户信息/头像）
        
        调用顺序：
        1. 如果需要用户信息，先调用 get_user_info 获取 face_url
        2. 如果需要头像，再调用 get_user_avatar 获取 PIL.Image
        """
        pass
```

### 4. interface.py - Interface 主体

```python
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

@register_interface("bili_danmaku_v2")
class BiliDanmakuInterfaceV2(Interface):
    """Bilibili 弹幕 Interface v2"""
    
    def __init__(self, roomids: List[int], bili_sessdata: str = "", 
                 debug_danmaku_content: bool = False,
                 fetch_user_info: bool = False,
                 fetch_user_avatar: bool = False,
                 user_info_cache_size: int = 100,
                 user_avatar_cache_size: int = 50,
                 user_max_concurrent: int = 5):
        # 初始化配置和内部状态
        pass
    
    @classmethod
    def from_cfg(cls, cfg: Dict) -> "BiliDanmakuInterfaceV2":
        """从配置字典创建实例"""
        pass
    
    async def start(self) -> None:
        """启动弹幕客户端
        
        1. 创建 Credential 对象
        2. 初始化用户信息/头像获取器（传入 Credential）
        3. 创建转换器（传入 fetcher）
        4. 创建 aiohttp 会话
        5. 启动 blivedm 客户端
        """
        pass
    
    async def stop(self) -> None:
        """停止并关闭所有客户端"""
        pass
    
    async def collect_input(self) -> List[BiliDanmakuMsg]:
        """收集弹幕输入（async 消息转换）
        
        1. 从 queue 中获取所有 (blivedm_message, client) 元组
        2. 异步转换为 BiliDanmakuMsg
        3. 返回转换后的消息列表
        """
        pass
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """弹幕 Interface 不提供工具"""
        return []
    
    def get_system_prompt(self) -> str:
        """返回弹幕的 system prompt 片段"""
        pass


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
```

## 关键设计点

1. **消息转换在 collect_input 中进行**：
   - Handler 中只放 `(blivedm_message, client)` 元组（sync）
   - collect_input 中进行 async 消息转换

2. **共用转换入口**：
   - `convert_blivedm2input_msg` 是共用入口
   - 内部根据 `isinstance` 切换转换方式

3. **Fetcher 作为 Converter 的成员变量**：
   - 在 Converter 初始化时传入 fetcher
   - 转换函数不需要每次都传入 fetcher
   - 更简洁，符合 OOP 设计

4. **Credential 对象**：
   - Fetcher 接收 Credential 对象而不是 sessdata 字符串
   - 由 Interface 在 start() 时创建并传入

5. **避免死锁**：
   - 用户信息缓存和头像缓存使用不同的锁
   - `get_user_avatar` 需要 `face_url` 作为参数，由调用者提供
   - 调用者先调用 `get_user_info` 获取 `face_url`，再调用 `get_user_avatar`

6. **缓存策略**：
   - 用户信息缓存：uid -> dict（username, gender, sign, face_url）
   - 用户头像缓存：uid -> PIL.Image

7. **并发控制**：使用 `asyncio.Semaphore` 限制同时获取用户信息/头像的并发数

## 待实现功能

- [ ] 用户信息/头像异步获取
- [ ] 缓存过期刷新
- [ ] 测试用例

---

文档完成。请确认内容是否有问题。
