from typing import Dict, Any, Callable, Tuple, Any, Awaitable, List
from core.config_loader import load_config
from core.vlm_client import load_vlm_router
from core.interfaces.loader import load_interfaces
from core.interfaces import Interface
from core.oai_tool import OAIFunction
from core.context_manager import ContextManager
from core.serializer import serialize_message_1to2
import asyncio, json, traceback, sys
from openai.types.chat import ChatCompletion, ChatCompletionMessage, ChatCompletionMessageFunctionToolCall
from core.msg import ResponseMsg, InputMsg

class SystemMessage(InputMsg):
    def __init__(self, data):
        self.data = data
    def get_llm_msg(self, context_manager = None):
        return [self.data]
    def get_unique_msgs(self):
        return []

async def main(yaml_fn: str):
    # 1. 读取配置文件
    config = load_config(yaml_fn)
    
    # 2. 建立OpenAI chat封装（根据配置文件，进行model routing逻辑、封装client、chat.completion.create的等等参数）
    vlm_router = load_vlm_router(config)

    # 3. 初始化需要的Interface
    interfaces = load_interfaces(config)
    #    收集system prompts
    system_prompt: str = config.get("system_prompt", "$interface_system_message")
    interface_sytem_prompts = []
    for k, v in interfaces.items():
        if (v.get_system_prompt()):
            interface_sytem_prompts.append(v.get_system_prompt())
    system_prompt = system_prompt.replace("$interface_system_message", "\n\n".join(interface_sytem_prompts))
    
    #    收集工具
    tool_map: Dict[str, Tuple[OAIFunction, Callable[..., Awaitable]]]= {}
    for k, v in interfaces.items():
        for tool_def, tool_fn in v.get_tools():
            tool_map[tool_def.name] = (tool_def, tool_fn)
    tool_ls = [tool_def.to_oai() for tool_def, tool_fn in tool_map.values()]

    # 4. 建立ContextManager
    context_manager = ContextManager(system_prompt)
    
    # 5. 所有Interface的start
    tasks = []
    for k, v in interfaces.items():
        task = asyncio.create_task(v.start())
        tasks.append(task)
    await asyncio.gather(*tasks)

    n_token_max = config.get("num_tokens_max", 65536)
    ctx_trim_ratio  = config.get("num_tokens_trim", 10000) / n_token_max
    # 对话循环
    while (True):
        # 收集输入消息
        try:
            msg_collect_tasks = []
            for k, v in interfaces.items():
                msg_collect_tasks.append(asyncio.create_task(v.collect_input()))
            any_input = False
            for msgs in await asyncio.gather(*msg_collect_tasks):
                for msg in msgs:
                    any_input = True
                    context_manager.add_msg(msg)
            if (not any_input):
                print("no input", interfaces)
                await asyncio.sleep(1)
                continue
            while (True):
                oai_msgs = context_manager.get_openai_messages()

                resp, client_idx = await vlm_router.chat_async(oai_msgs, tool_ls)
                if (resp is None):
                    raise Exception("All VLM routed provider failed")

                resp_msg = resp.choices[0].message
                tokens_used = resp.usage.total_tokens
                if (getattr(resp, "timings", None) is not None):
                    timings = resp.timings
                    cache_n = timings.get("cache_n", None)
                    if (cache_n is not None):
                        print("prefix cache", cache_n)
                else:
                    cache_n = 0
                print(f"{resp.model} Tokens Used/Cached: {tokens_used}/{cache_n}")
                if (tokens_used > config.get("num_tokens_max", 100000)):
                    print("Trimming Context {ctx_trim_ratio}")
                    context_manager.trim_by_round(ctx_trim_ratio)

                print("Thinking", getattr(resp_msg, "reasoning_content", None))
                print("Content ", resp_msg.content)
                print("Tools   ", resp_msg.tool_calls)
                context_manager.add_msg(ResponseMsg(resp_msg))

                tool_tasks: List[Tuple[ChatCompletionMessageFunctionToolCall, asyncio.Task]] = []
                if (resp_msg.tool_calls):
                    for call in resp_msg.tool_calls:
                        fname = call.function.name
                        if (isinstance(call.function.arguments, str)):
                            # work-around llama.cpp/llama-server older bug using \uxxxx cause model hard to generate CJK
                            call.function.arguments = json.dumps(json.loads(call.function.arguments), ensure_ascii=False)
                        else:
                            # work-around llama.cpp/llama-server later bug, expecting str, but llama-server returns json-object as argument
                            call.function.arguments = json.dumps(call.function.arguments, ensure_ascii=False)
                        
                        fargs = json.loads(call.function.arguments)
                        if (fname in tool_map):
                            tool_def, tool_fn = tool_map[fname]
                            coro = tool_fn(**fargs)
                            tool_tasks.append((call, asyncio.create_task(coro)))
                speech_tasks = []
                if (resp_msg.content): # should be list of emotion-speech pair。也许我们应该添加VLM返回的格式错误时的异常处理。
                    speech = None
                    try:
                        speech = json.loads(resp_msg.content)
                    except json.decoder.JSONDecodeError as e:
                        print("cannot load json", resp_msg.content)
                        if (config.get("notice_vlm_about_json", False)):
                            context_manager.add_msg(SystemMessage({"type": "system", "message": "输出的消息格式不符合json格式", "exception": str(e)}))
                        else:
                            raise e
                    if (speech):
                        for k, v in interfaces.items():
                            none_or_coro = v.on_speech(speech)
                            if (none_or_coro is not None):
                                speech_tasks.append(asyncio.create_task(none_or_coro))
                if (speech_tasks):
                    await asyncio.gather(*speech_tasks)
                if (tool_tasks):
                    tool_results = await asyncio.gather(*[task for tool_call, task in tool_tasks])
                    for idx, i in enumerate(tool_tasks):
                        tool_call, task = i
                        result = tool_results[idx]
                        # will we support rich tool result in future?
                        if (not isinstance(result, str)):
                            result = json.dumps(result, ensure_ascii=False)
                        context_manager.add_msg(ResponseMsg({"role": "tool", "tool_call_id": tool_call.id, "content": result}))
                    # 继续VLM Chat循环，让VLM接收到工具返回值后继续完成对话。
                else:
                    break    
        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
            break
    
    # 所有Interface的stop。
    stop_tasks = []
    for k, v in interfaces.items():
        task = asyncio.create_task(v.stop())
        stop_tasks.append(task)
    await asyncio.gather(*stop_tasks)

if (__name__=="__main__"):
    asyncio.run(main(sys.argv[-1]))