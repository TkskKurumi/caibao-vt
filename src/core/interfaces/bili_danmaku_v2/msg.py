"""BiliDanmakuInterface v2 消息类"""
from typing import List, Dict, Any, Optional
from PIL.Image import Image
from ...image import ImagePIL
from ...msg import InputMsg, UniqueMsg


class BiliUserUniqueMsg(UniqueMsg):
    """Bilibili 用户唯一标识"""
    
    def __init__(self, uid: int, username: str, guard_level: int = 0,
                 face_image: Image = None,
                 gender: str = "", sign: str = ""):
        self.uid = uid
        self.username = username
        self.guard_level = guard_level
        self.face_image = face_image
        self.gender = gender
        self.sign = sign
        self.guard_name = {1: "舰长", 2: "提督", 3: "总督"}.get(guard_level, "")
    
    def get_unique_id(self) -> str:
        return f"BiliUser({self.uid})"
    
    def get_llm_msg(self, context_manager = None) -> Dict[str, Any]:
        """返回用户信息"""
        result = {
            "type": "bili_user",
            "uid": self.uid,
            "username": self.username,
        }
        if self.guard_level > 0:
            result["guard_level"] = self.guard_level
            result["guard_name"] = self.guard_name
        if self.gender:
            result["gender"] = self.gender
        if self.sign:
            result["sign"] = self.sign
        # 如果有 face_image，添加到结果中
        if self.face_image is not None:
            result["face_image"] = ImagePIL(self.face_image, f"bili_user_face_{self.uid}")
        return result


class BiliDanmakuMsg(InputMsg):
    """Bilibili 弹幕消息"""
    
    def __init__(self, data: Dict[str, Any], user_unique: BiliUserUniqueMsg = None):
        self.data = data
        self.user_unique = user_unique
    
    def get_llm_msg(self, context_manager = None) -> Dict[str, Any]:
        return self.data
    
    def get_unique_msgs(self) -> List[UniqueMsg]:
        if self.user_unique:
            return [self.user_unique]
        return []
