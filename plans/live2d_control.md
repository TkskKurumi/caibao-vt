# Live2D 模型控制设计

## 概述

本文档整理如何控制 Live2D 模型（通过 VTube Studio API 或第三方 Python 接口）实现：
1. **待机动作**：让模型自然地进行随机动作，避免定着不动
2. **发言动作**：与 TTS 语音同步，控制张嘴闭嘴和情感表达

## 性能考虑：FPS 和 CPU 占用

### 关键问题

1. **参数控制能否达到 >60 FPS？**
   - 需要确认 VTube Studio API 的调用频率限制
   - 高频率调用是否会被限制或丢弃

2. **VTube Studio 是否会平滑插值？**
   - 不确定 VTube Studio 是否会自动在两次 API 调用之间插值
   - 如果不插值，参数突变会导致模型动作不流畅

3. **主程序高频率循环的 CPU 占用**
   - >60 FPS 的循环会占用大量 CPU 资源
   - 需要权衡流畅度和性能

### 待验证事项

- [ ] VTube Studio API 的最大推荐调用频率
- [ ] VTube Studio 是否自动插值处理参数变化
- [ ] 高频率 API 调用是否会被限流或丢弃
- [ ] 60 FPS 循环对 CPU 的实际占用

### 建议的测试方案

1. **测试插值行为**：
   - 以不同频率（10Hz, 30Hz, 60Hz, 100Hz）调用参数设置 API
   - 观察模型动作是否流畅
   - 如果 30Hz 已经足够流畅，说明 VTube Studio 有插值

2. **测试 CPU 占用**：
   - 运行 60 FPS 循环，观察 CPU 占用
   - 如果占用过高，考虑降低频率或使用固定动画

3. **查阅 VTube Studio API 文档**：
   - 确认是否有频率限制
   - 确认是否有插值机制说明

## VTube Studio API 能力

VTube Studio 支持通过 API 控制 Live2D 模型，主要有两种方式：

### 1. 播放固定动画
- **优点**：简单好控制，Cubism Editor 可以可视化编辑动画
- **缺点**：灵活性较低，需要预先编辑好所有动画
- **性能**：无额外 CPU 占用（VTube Studio 内部处理）

### 2. 设定参数值
- **优点**：自由度更高，可以实时控制任何参数
- **缺点**：需要程序不断更新参数（如嘴巴开合），实现复杂
- **性能**：需要持续调用 API，频率未知，可能占用 CPU
- **待确认**：VTube Studio 是否自动插值？是否需要客户端实现插值？

## 待机动作控制

### 目标
- 让模型每隔一段时间进行随机动作
- 避免循环动画，保持自然感
- 不要定着不动

### 控制参数
主要控制以下参数（范围通常为 -1.0 到 1.0）：
- `BodyX`：身体左右移动
- `BodyY`：身体上下移动
- `FaceX`：脸部左右转动
- `FaceY`：脸部上下转动
- `EyeX`：眼睛左右移动
- `EyeY`：眼睛上下移动

### 实现思路
```python
async def idle_loop():
    while running:
        # 每隔 2-5 秒随机设定参数
        await asyncio.sleep(random.uniform(2, 5))
        
        # 随机设定参数值
        params = {
            "PARAM_BODY_X": random.uniform(-0.2, 0.2),
            "PARAM_BODY_Y": random.uniform(-0.1, 0.1),
            "PARAM_FACE_X": random.uniform(-0.3, 0.3),
            "PARAM_FACE_Y": random.uniform(-0.2, 0.2),
            "PARAM_EYE_X": random.uniform(-0.3, 0.3),
            "PARAM_EYE_Y": random.uniform(-0.2, 0.2),
        }
        
        await vts_api.set_parameters(params)
        
        # 参数保持一段时间后恢复默认
        await asyncio.sleep(random.uniform(1, 3))
        await vts_api.reset_parameters()
```

### 注意事项
- 参数变化幅度不宜过大，避免突兀
- 恢复默认参数时可以使用缓动效果
- 避免与发言动画冲突（见下文）

## 发言动作控制

### 目标
- 与 TTS 语音同步
- 控制张嘴闭嘴（口型）
- 控制情感表达（害羞、笑、生气等）

### 方案对比

#### 方案 A：固定动画
- 预先在 Cubism Editor 中编辑好：
  - 张嘴动画
  - 闭嘴动画
  - 各种情感动画（害羞、笑、生气等）
- 播放时调用对应动画

**优点**：
- 实现简单
- 动画质量高（可视化编辑）
- 容易管理

**缺点**：
- 需要预先编辑所有动画
- 口型同步可能不够精确

#### 方案 B：参数控制
- 实时控制参数：
  - 嘴巴开合参数（根据语音音量或音素）
  - 情感参数（害羞、笑、生气等）

**优点**：
- 灵活性高
- 可以实现精确的口型同步

**缺点**：
- 实现复杂
- 需要实时更新参数
- 需要处理参数平滑过渡

### 推荐方案：混合方案

结合两种方案的优点：

1. **情感表达**：使用固定动画
   - 预先编辑好各种情感动画
   - 根据 LLM 输出的 emotion 字段播放对应动画

2. **口型同步**：使用参数控制
   - 根据 TTS 音频的音量或音素实时控制嘴巴开合参数
   - 可以使用简单的音量检测，或使用更复杂的音素识别

### 实现思路

```python
async def on_speech(speech_items):
    for item in speech_items:
        content = item["content"]
        emotion = item["emotion"]
        
        # 1. 播放情感动画（如果有）
        if emotion:
            await vts_api.play_animation(f"emotion_{emotion}")
        
        # 2. 播放 TTS 音频，同时控制口型
        audio_path = await tts_backend.generate(content)
        
        # 同步播放音频和控制口型
        await sync_audio_and_mouth(audio_path)
        
        # 3. 播放结束后恢复默认状态
        await vts_api.reset_parameters()
        await vts_api.stop_animation()

async def sync_audio_and_mouth(audio_path):
    """播放音频并同步控制嘴巴开合"""
    import soundfile as sf
    import numpy as np
    
    # 读取音频文件
    data, samplerate = sf.read(audio_path)
    
    # 分帧处理（每帧 20ms）
    frame_size = int(samplerate * 0.02)
    hop_size = int(samplerate * 0.01)
    
    for i in range(0, len(data) - frame_size, hop_size):
        frame = data[i:i + frame_size]
        
        # 计算音量（RMS）
        rms = np.sqrt(np.mean(frame ** 2))
        
        # 根据音量控制嘴巴开合参数
        # 音量越大，嘴巴开得越大
        mouth_open = min(1.0, rms / 0.1)  # 归一化
        
        await vts_api.set_parameter("PARAM_MOUTH_OPEN", mouth_open)
        
        await asyncio.sleep(0.01)  # 10ms
    
    # 最后关闭嘴巴
    await vts_api.set_parameter("PARAM_MOUTH_OPEN", 0)
```

## 避免动画冲突

### 问题
- 待机动画和发言动画可能同时触发，导致冲突
- 参数控制可能覆盖固定动画的效果

### 解决方案

#### 方案 1：优先级系统
- 发言动画优先级 > 待机动画
- 发言时暂停待机动画
- 发言结束后恢复待机动画

```python
class Live2DController:
    def __init__(self):
        self.is_speaking = False
        self.idle_task = None
    
    async def start_idle(self):
        self.idle_task = asyncio.create_task(self.idle_loop())
    
    async def stop_idle(self):
        if self.idle_task:
            self.idle_task.cancel()
            try:
                await self.idle_task
            except asyncio.CancelledError:
                pass
    
    async def on_speech_start(self):
        self.is_speaking = True
        await self.stop_idle()
    
    async def on_speech_end(self):
        self.is_speaking = False
        await self.start_idle()
```

#### 方案 2：参数分组
- 待机动画只控制部分参数（如 BodyX, FaceX）
- 发言动画控制其他参数（如 MouthOpen, Emotion）
- 避免同时控制同一参数

#### 方案 3：动画层
- VTube Studio 支持动画层（Layer）
- 待机动画放在底层
- 发言动画放在顶层
- 顶层动画可以覆盖底层动画

## 推荐实现架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Live2DController                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │  IdleController │    │ SpeechController│                │
│  │  (待机控制)     │    │ (发言控制)      │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      ↓                                      │
│              ┌───────────────┐                              │
│              │ VTS API Client│                              │
│              └───────────────┘                              │
└─────────────────────────────────────────────────────────────┘

IdleController:
  - 定期随机参数
  - 发言时暂停

SpeechController:
  - 播放情感动画
  - 同步音频和口型
  - 发言结束后恢复待机
```

## 待办事项

1. **研究 VTube Studio API**：
   - 确认支持的参数列表
   - 确认动画播放 API
   - 确认参数设置 API

2. **选择第三方库**：
   - 查找现有的 VTube Studio Python 接口
   - 评估是否满足需求

3. **实现待机控制**：
   - 实现随机参数控制
   - 测试自然度

4. **实现发言控制**：
   - 实现情感动画播放
   - 实现口型同步（先简单音量检测，后考虑音素识别）

5. **测试和优化**：
   - 测试动画冲突问题
   - 优化参数变化幅度
   - 优化口型同步精度

## 参考资料

- VTube Studio API 文档
- Cubism Editor 教程
- 第三方 VTube Studio Python 库（待查找）