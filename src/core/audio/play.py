"""音频播放模块：提供三种播放方式"""

import asyncio
import time
from typing import Optional

import pygame

# 全局初始化状态
_INITED: bool = False


def _init() -> None:
    """初始化 pygame mixer（线程安全）"""
    global _INITED
    if not _INITED:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        _INITED = True


def play_file_and_wait(sound_file: str) -> None:
    """
    播放音频文件并阻塞等待播放完成
    
    使用 time.sleep() 阻塞当前线程，直到播放完毕
    适用于同步场景
    """
    _init()
    snd = pygame.mixer.Sound(sound_file)
    duration_ms = snd.get_length() * 1000
    snd.play()
    time.sleep(duration_ms / 1000.0)  # 转换为秒


def play_file_non_blocked(sound_file: str) -> pygame.mixer.Sound:
    """
    播放音频文件但不阻塞（立即返回）
    
    返回 Sound 对象，调用者可以自行管理播放状态
    适用于需要并发播放或不需要等待的场景
    """
    _init()
    snd = pygame.mixer.Sound(sound_file)
    snd.play()
    return snd


async def play_file_wait_async(sound_file: str) -> None:
    """
    异步版本：播放音频文件并等待播放完成
    
    使用 asyncio.to_thread() 包装同步的 play_file_and_wait()
    适用于 async/await 场景
    """
    await asyncio.to_thread(play_file_and_wait, sound_file)


