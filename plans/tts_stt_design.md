# TTS/STT Interface 设计文档

## 概述

实现语音对话功能，让 AI 主播能够：
1. **听**：通过 STT Interface 识别用户语音输入
2. **说**：通过 TTS Interface 将 LLM 回复转换为语音输出

## 架构设计

### 1. 独立 Interface 设计

TTS 和 STT 是两个独立的 Interface，遵循现有的 Interface 架构：

```
┌─────────────────────────────────────────────────────────────┐
│                      Main Loop                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ STTInterface │    │ Screenshot   │    │ BiliDanmaku  │  │
│  │  (collect)   │    │ (collect)    │    │ (collect)    │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │           │
│         └───────────────────┴───────────────────┘           │
│                           ↓                                 │
│                    ┌──────────────┐                         │
│                    │   Context    │                         │
│                    │  Manager     │                         │
│                    └──────┬───────┘                         │
│                           ↓                                 │
│                    ┌──────────────┐                         │
│                    │    VLM       │                         │
│                    └──────┬───────┘                         │
│                           ↓                                 │
│         ┌─────────────────┴─────────────────┐              │
│         ↓                                   ↓              │
│  ┌──────────────┐                    ┌──────────────┐      │
│  │ TTSInterface │                    │   Other      │      │
│  │  (on_speech) │                    │  Interfaces  │      │
│  └──────────────┘                    └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 2. STT Interface

#### 职责
- 监听麦克风输入
- 将语音转换为文字
- 通过 `collect_input()` 返回识别的文字消息

#### 配置项
```yaml
interfaces:
  stt:
    type: stt
    stt_type: sherpa_ncnn  # 支持的类型见下方
    # 后端特定配置...
```

#### STT 后端接口
```python
class STTBackend(ABC):
    @abstractmethod
    async def start(self, on_result: Callable[[str], None]) -> None:
        """
        开始识别
        on_result: 识别到文字后的回调函数
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止识别"""
        pass
```

#### 支持的 STT 后端
1. **SherpaNCNN**（`sherpa_ncnn`）
   - 使用 sherpa-ncnn 库
   - 本地运行，低延迟
   - 配置：`model_dir`, `provider` (cpu/cuda), `hotwords`

2. **WhisperLocal**（`whisper_local`，预留）
   - 使用 Whisper 模型
   - 配置：`model_size` (tiny/base/large)

3. **AzureSTT**（`azure_stt`，预留）
   - Azure Speech Service
   - 配置：`subscription_key`, `region`

4. **AliyunSTT**（`aliyun_stt`，预留）
   - 阿里云语音识别
   - 配置：`access_key`, `secret_key`, `app_key`

#### STTMsg 消息格式
```python
class STTMsg(InputMsg):
    def __init__(self, text: str, timestamp: float):
        self.text = text
        self.timestamp = timestamp
    
    def get_llm_msg(self, context_manager = None):
        return {
            "type": "stt",
            "content": self.text,
            "timestamp": self.timestamp
        }
    
    def get_unique_msgs(self):
        return []  # 不去重
```

### 3. TTS Interface

#### 职责
- 接收 LLM 的发言内容（通过 `on_speech()`）
- 将文本转换为语音
- 播放语音

#### 配置项
```yaml
interfaces:
  tts:
    type: tts
    tts_type: index_tts  # 支持的类型见下方
    # 后端特定配置...
```

#### TTS 后端接口
```python
class TTSBackend(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> str:
        """
        将文本转换为音频文件
        返回：音频文件路径
        """
        pass
```

#### 支持的 TTS 后端
1. **IndexTTS**（`index_tts`）
   - 调用你提供的 API 端口
   - 配置：`endpoint`, `apikey`, `voice`

2. **LocalTTS**（`local_tts`，预留）
   - 本地运行 TTS 模型
   - 配置：`model_path`, `voice`

3. **AzureTTS**（`azure_tts`，预留）
   - Azure Cognitive Services
   - 配置：`subscription_key`, `region`, `voice`

4. **EdgeTTS**（`edge_tts`，预留）
   - Edge 浏览器 TTS
   - 配置：`voice`

#### on_speech 处理
```python
async def on_speech(self, speech: List[Dict]) -> Awaitable:
    """
    处理 LLM 的发言
    
    speech 格式：[{"content": "你好", "emotion": "happy"}, ...]
    注意：emotion 参数目前不处理，未来 TTS+VTS 集成时会用到
    """
    for item in speech:
        text = item.get("content", "")
        if text:
            audio_path = await self.tts_backend.synthesize(text)
            await play_file_wait_async(audio_path)
```

### 4. 配置示例

#### 完整配置
```yaml
system_prompt: |
  你是一个 AI 虚拟主播，可以通过语音与用户对话。
  用户会通过语音向你提问或聊天，你需要用语音回复。
  $interface_system_message

interfaces:
  # STT Interface
  stt:
    type: stt
    stt_type: sherpa_ncnn
    model_dir: ./sherpa-models
    provider: cpu
    hotwords: "AI, 主播，小助手"
  
  # TTS Interface
  tts:
    type: tts
    tts_type: index_tts
    endpoint: http://192.168.31.117:8101
    apikey: "$env:{INDEX_TTS_APIKEY}"
    voice: "zh_female_xiaoyuan"
  
  # 其他 Interface
  screenshot:
    type: screenshot
    frame_rate: 1.0
    max_frame: 3
  
  bili_danmaku:
    type: bili_danmaku
    roomids: [21302070]
    bili_sessdata: "$env:{BILI_SESSDATA}"
    debug_danmaku_content: true

vlm:
  route_policy: ordered
  model_configs:
    - endpoint: http://192.168.31.117:8091/v1
      model: Qwen3.5
      enabled: true
      priority: 1
```

### 5. 工作流程

#### STT 流程
```
用户语音
    ↓
[STT Interface.start()] 启动识别
    ↓
[STT Backend] 麦克风录音 → 语音识别
    ↓
[on_result callback] 识别到文字
    ↓
[STT Interface] 创建 STTMsg 加入缓冲区
    ↓
[Main Loop] collect_input() → 返回 STTMsg 列表
    ↓
[Main Loop] ContextManager.add_msg(STTMsg)
```

#### TTS 流程
```
[VLM] 生成回复
    ↓
[Main Loop] ResponseMsg
    ↓
[Main Loop] Interface.on_speech(speech)
    ↓
[TTS Interface] 遍历 speech 列表
    ↓
[TTS Backend] synthesize(text) → 音频文件
    ↓
[Audio Play] play_file_wait_async(audio_path)
    ↓
[等待播放完成]
```

### 6. 未来扩展：TTS + VTS 集成

未来可以创建一个 `TTSVTSInterface`，将 TTS 和 VTube Studio 同步：

```python
class TTSVTSInterface(Interface):
    """TTS + VTS 集成 Interface
    
    负责：
    1. 根据 emotion 参数设置 VTS 表情
    2. 同步 TTS 播放和 VTS 动作
    3. 播放语音
    """
    async def on_speech(self, speech: List[Dict]) -> Awaitable:
        for item in speech:
            emotion = item.get("emotion", "neutral")
            content = item.get("content", "")
            
            # 1. 设置 VTS 表情
            await self.vts.set_expression(emotion)
            
            # 2. 合成并播放语音
            audio_path = await self.tts.synthesize(content)
            await self.play_and_sync_vts(audio_path)
```

### 7. 待实现内容清单

#### STT Interface
- [ ] `STTBackend` 基类定义
- [ ] `SherpaNCNNBackend` 实现
- [ ] `STTMsg` 消息类
- [ ] `STTInterface` 实现
- [ ] 其他 STT 后端（预留）

#### TTS Interface
- [ ] `TTSBackend` 基类定义
- [ ] `IndexTTSBackend` 实现
- [ ] `TTSInterface` 实现
- [ ] 其他 TTS 后端（预留）

#### 音频播放
- [ ] 使用现有的 `play.py` 模块
- [ ] 确保异步播放正确

#### 测试
- [ ] STT 识别测试
- [ ] TTS 合成测试
- [ ] 完整语音对话流程测试

### 8. 注意事项

1. **STT 延迟**：持续监听可能产生大量识别结果，需要合理的去重和过滤机制
2. **TTS 延迟**：语音合成需要时间，可能影响对话流畅性
3. **打断机制**：用户说话时可能需要打断当前 TTS 播放（未来功能）
4. **噪声处理**：STT 前可能需要噪声抑制处理（未来功能）
5. **多语言支持**：配置不同语言模型（未来功能）
