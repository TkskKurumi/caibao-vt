"""序列化器：将消息转换为 OpenAI API 兼容格式"""

from dataclasses import dataclass
from typing import List, Union, Any, Dict
from .msg import ResponseMsg
from .image import ImageObject

# stage0: InputMsg | ReponseMsg | UniqueMsg
# stage1: Any | ResponseMsg
# stage1.5: List[str|ImageObject|ResponseMsg]
# stage2: OpenAI Message
# 0 -> 1 is converted in ContextManager
STAGE15_T = List[Union[str, ImageObject, ResponseMsg]]
def serialize_message_1to15(stage1_messages: List[Any|ResponseMsg]) -> STAGE15_T:
    def serialize_recur(obj, buffer: STAGE15_T):
        if (isinstance(obj, str)):
            buffer.append(f'"{obj}"')
        elif (isinstance(obj, (int, float))):
            buffer.append(f'{obj}')
        elif (isinstance(obj, (bool))):
            buffer.append(f'{obj}'.lower())
        elif (obj is None):
            buffer.append("null")
        elif (isinstance(obj, ImageObject)):
            buffer.append("{")
            buffer.append(f'"image_id": "{obj.image_id}", "image_data": ')
            buffer.append(obj)
            buffer.append("}")
        elif (isinstance(obj, Dict)):
            buffer.append('{')
            first = True
            for k, v in obj.items():
                if (not first):
                    buffer.append(", ")
                serialize_recur(k, buffer)
                buffer.append(": ")
                serialize_recur(v, buffer)
                first = False
            buffer.append('}')
        elif (isinstance(obj, List)):
            buffer.append("[")
            for idx, i in enumerate(obj):
                if (idx):
                    buffer.append(", ")
                serialize_recur(i, buffer)
            buffer.append("]")
        elif (isinstance(obj, ResponseMsg)):
            buffer.append(obj)
        else:
            raise TypeError(type(obj))
    ret = []
    for i in stage1_messages:
        serialize_recur(i, ret)
    return ret

DEBUG = False

def serialize_message_1to2(msgs_stage1):
    global DEBUG
    if (DEBUG):
        print("DEBUG: STAGE1  :", msgs_stage1)
    msgs_stage15 = serialize_message_1to15(msgs_stage1)
    
    if (DEBUG):
        print("DEBUG: STAGE15 :", msgs_stage15)
    curr_str = []
    msgs_sage15_merge_str: List[STAGE15_T] = []
    for i in msgs_stage15:
        if (isinstance(i, str)):
            curr_str.append(i)
        else:
            if (curr_str):
                msgs_sage15_merge_str.append("".join(curr_str))
                curr_str = []
            msgs_sage15_merge_str.append(i)
    if (curr_str):
        msgs_sage15_merge_str.append("".join(curr_str))
    
    msg_stage2 = []
    user_content = []
    for i in msgs_sage15_merge_str:
        if (isinstance(i, str)):
            user_content.append({"type": "text", "text": i})
        elif (isinstance(i, ImageObject)):
            user_content.append({"type": "image_url", "image_url": {"url": i.url}})
        elif (isinstance(i, ResponseMsg)):
            if (user_content):
                msg_stage2.append({"role": "user", "content": user_content})
                user_content = []
            msg_stage2.append(i.get_llm_msg())
    if (user_content):
        msg_stage2.append({"role": "user", "content": user_content})
    if (DEBUG):
        print("DEBUG: STAGE2  :", msg_stage2)
    return msg_stage2
        