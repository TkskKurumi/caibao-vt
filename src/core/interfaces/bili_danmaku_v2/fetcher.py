"""BiliUserFetcher - 用户信息/头像获取器（双缓存）"""
import asyncio
from typing import Dict, Optional, Any
from PIL.Image import Image
from bilibili_api import Credential
from bilibili_api.user import User
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
                 max_concurrent: int = 5,
                 debug: bool = False):
        self._credential = credential
        self._info_cache_size = info_cache_size
        self._avatar_cache_size = avatar_cache_size
        self._debug = debug
        
        # 双缓存
        self._info_cache: Dict[int, Dict] = {}
        self._avatar_cache: Dict[int, Image] = {}
        
        # 两个缓存使用不同的锁，避免死锁
        self._info_lock = asyncio.Lock()
        self._avatar_lock = asyncio.Lock()
        
        # 并发控制
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
        # aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self) -> None:
        """异步初始化（创建 aiohttp session）"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
    
    async def get_user_info(self, uid: int) -> Dict[str, Any]:
        """获取用户信息（带缓存）
        
        Args:
            uid: 用户 ID
            
        Returns:
            用户信息字典，包含 username, gender, sign, face_url 等
        """
        if uid <= 0:
            return {}
        
        # 1. 检查缓存（使用 info_lock）
        async with self._info_lock:
            if uid in self._info_cache:
                return self._info_cache[uid]
        
        # 2. 限制并发获取
        async with self._semaphore:
            info = await self._fetch_user_info(uid)
        
        # 3. 更新缓存
        async with self._info_lock:
            # 缓存溢出时删除最旧的
            if len(self._info_cache) >= self._info_cache_size:
                oldest_uid = next(iter(self._info_cache))
                del self._info_cache[oldest_uid]
            self._info_cache[uid] = info
        
        return info
    
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
        if uid <= 0 or not face_url:
            return None
        
        # 1. 检查缓存（使用 avatar_lock）
        async with self._avatar_lock:
            if uid in self._avatar_cache:
                return self._avatar_cache[uid]
        
        # 2. 限制并发下载
        async with self._semaphore:
            img = await self._fetch_user_avatar(face_url)
        
        # 3. 更新缓存
        async with self._avatar_lock:
            if img is not None:
                # 缓存溢出时删除最旧的
                if len(self._avatar_cache) >= self._avatar_cache_size:
                    oldest_uid = next(iter(self._avatar_cache))
                    del self._avatar_cache[oldest_uid]
                self._avatar_cache[uid] = img
        
        return img
    
    async def _fetch_user_info(self, uid: int) -> Dict[str, Any]:
        """调用 bilibili_api 获取用户信息"""
        try:
            user = User(uid, credential=self._credential)
            info = await user.get_user_info()
            if self._debug:
                print(f"[BiliUserFetcher DEBUG] uid={uid} API 返回：{info}")
            return {
                "uid": info["mid"],
                "username": info["name"],
                "gender": info["gender"],
                "sign": info["sign"],
                "face_url": info["face"],
            }
        except Exception as e:
            print(f"[BiliUserFetcher] 获取用户信息失败 uid={uid}: {e}")
            return {}
    
    async def _fetch_user_avatar(self, face_url: str) -> Optional[Image]:
        """下载头像图片为 PIL.Image"""
        try:
            from PIL import Image as PILImage
            import io
            
            async with self._session.get(face_url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                img = PILImage.open(io.BytesIO(data))
                return img
        except Exception as e:
            print(f"[BiliUserFetcher] 下载头像失败 url={face_url}: {e}")
            return None
    
    async def close(self) -> None:
        """关闭 aiohttp session"""
        if self._session:
            await self._session.close()
            self._session = None
