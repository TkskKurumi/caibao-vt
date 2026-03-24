"""测试序列化功能和 VLM 模型"""

import asyncio
import base64
import json
from pathlib import Path

from openai import OpenAI
from src.core.msg import ResponseMsg
from src.core.serializer import ImageObject, serialize_message_1to2
from src.core.image import ImageFile, ImagePIL
from PIL import Image
# VLM 配置
VLM_BASE_URL = "http://192.168.31.117:8090/v1"
VLM_MODEL = "Qwen3.5"
VLM_API_KEY = "dummy"  # 本地模型通常不需要真实 API key

client = OpenAI(api_key=VLM_API_KEY, base_url=VLM_BASE_URL)
def test_A():
    stage1 = [
        ImageFile(r"D:\caibao-bili-vup\assets\avatar_caicai.jpg", image_id="image-A"),
        ImageFile(r"D:\caibao-bili-vup\assets\chibi_yvette.png", image_id="image-B"),
        ImageFile(r"D:\caibao-bili-vup\assets\heart_hatsune_miku.jpg", image_id="image-C"),
        ImageFile(r"D:\caibao-bili-vup\assets\heart_hatsune_miku.jpg", image_id="1ab2c3dd44ef56"),

        "1. Which image is a chibi? ",
        "2. Which image is a black hair catear girl?",
        "3. Which two image is same or similar, give their image IDs. ",
        "Answer in brief and short"
    ]

    stage2 = serialize_message_1to2(stage1)

    print(str(stage2)[:1000])

    resp = client.chat.completions.create(messages=stage2, model=VLM_MODEL)
    print(resp)
def test_B():
    stage1 = [
        {
            "type": "user_info",
            "user_info": {
                "uid": 1514013,
                "username": "菜菜",
                "avatar": ImageFile(r"D:\caibao-bili-vup\assets\avatar_caicai.jpg")#, image_id="avatar-1514013")
            }
        },
        {
            "type": "user_info",
            "user_info": {
                "uid": 998244353,
                "username": "菲小熊",
                "avatar": ImageFile(r"D:\caibao-bili-vup\assets\chibi_yvette.png")#, image_id="avatar-998244353")
            }
        },
        {
            "type": "user_info",
            "user_info": {
                "uid": 114514,
                "username": "千千不太准",
                "avatar": ImageFile(r"D:\caibao-bili-vup\assets\heart_hatsune_miku.jpg")#, image_id="avatar-114514")
            }
        },
        {"type": "screenshot", "screenshot": ImageFile(r"E:\Pics\6ECE732094A12E4FB131C0086957913B.jpg")},
        {"type": "danmaku", "danmaku": {"sender": 114514, "message": "咕咕嘎嘎"}},
        {"type": "danmaku", "danmaku": {"sender": 998244353, "message": "那个头像是黑发猫娘的家伙是谁？"}},
        {"type": "danmaku", "danmaku": {"sender": 1514013, "message": "学鸭子叫的用户的id是多少、用户名是什么？"}},
        {"type": "danmaku", "danmaku": {"sender": 114514, "message": "前面两条消息的用户，头像分别是什么内容？"}},
        {"type": "danmaku", "danmaku": {"sender": 998244353, "message": "主播主播，这是什么游戏，感觉内容怪怪的"}},
        "1. 你看到的以上消息是什么格式？图片以什么方式输入进来了？",
        "2. 请你作为主播逐条回应上述弹幕消息。",
        "3. 总结每条弹幕（列成表格，包含id，用户名, 头像内容简介, 弹幕内容几列）",
    ]

    stage2 = serialize_message_1to2(stage1)

    print(str(stage2)[:1000])

    resp = client.chat.completions.create(messages=stage2, model=VLM_MODEL)
    print(resp)

    print(resp.choices[0].message.content)

def test_C():
    stage1 = [
        {
            "type": "user_info",
            "user_info": {
                "uid": 1514013,
                "username": "菜菜",
                "avatar": ImageFile(r"D:\caibao-bili-vup\assets\avatar_caicai.jpg")#, image_id="avatar-1514013")
            }
        },
        {
            "type": "user_info",
            "user_info": {
                "uid": 998244353,
                "username": "菲小熊",
                "avatar": ImageFile(r"D:\caibao-bili-vup\assets\chibi_yvette.png")#, image_id="avatar-998244353")
            }
        },
        {
            "type": "user_info",
            "user_info": {
                "uid": 114514,
                "username": "千千不太准",
                "avatar": ImageFile(r"D:\caibao-bili-vup\assets\heart_hatsune_miku.jpg")#, image_id="avatar-114514")
            }
        },
        {"type": "screenshot", "screenshot": ImageFile(r"E:\Pics\6ECE732094A12E4FB131C0086957913B.jpg")},
        {"type": "danmaku", "danmaku": {"sender": 114514, "message": "咕咕嘎嘎"}},
        {"type": "danmaku", "danmaku": {"sender": 998244353, "message": "那个头像是黑发猫娘的家伙是谁？"}},
        {"type": "danmaku", "danmaku": {"sender": 1514013, "message": "学鸭子叫的用户的id是多少、用户名是什么？"}},
        {"type": "danmaku", "danmaku": {"sender": 114514, "message": "前面两条消息的用户，头像分别是什么内容？"}},
        {"type": "danmaku", "danmaku": {"sender": 998244353, "message": "主播主播，这是什么游戏，感觉内容怪怪的"}},
        "1. 请你作为主播逐条回应上述弹幕消息。",
    ]

    stage2 = serialize_message_1to2(stage1)

    print(str(stage2)[:1000])

    resp = client.chat.completions.create(messages=stage2, model=VLM_MODEL)
    print(resp)

    print(resp.choices[0].message.content)