"""LLM provider adapter 注册表与调用上下文。

每个 adapter 负责一种 SDK 协议的「构造 client → 调用 → 解析响应」流程，
统一签名 ``generate(ctx: LLMCallContext) -> str``。llm.py 的 _generate_response
完成前置公共逻辑（解析 provider、读取配置、校验必填项、处理 ollama/azure 特例）
后，构造 LLMCallContext 并经 get_adapter 分发。

LLMProviderSpec.adapter 字段是这里的查表 key；Registry 本身保持纯数据不动。
新增协议不同的 provider 时，只需在此目录加一个 adapter 模块并注册，不再修改
_generate_response。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict


@dataclass
class LLMCallContext:
    """一次 LLM 调用所需的全部已解析参数。"""
    provider_id: str  # 用于错误消息中的 [{llm_provider}] 前缀
    prompt: str
    api_key: str
    model_name: str
    base_url: str
    api_version: str = ""
    extra_values: dict = field(default_factory=dict)


# adapter 注册表：{adapter_name: generate_callable}。
# 在模块底部由各 adapter 模块填充，避免顶层循环导入。
_ADAPTERS: Dict[str, Callable[[LLMCallContext], str]] = {}


def register_adapter(name: str, default: bool = False):
    """装饰器：把一个 generate 函数注册为指定 adapter 名的处理函数。

    ``default=True`` 的 adapter 同时作为未知 adapter 的兜底。
    """

    def _wrap(func: Callable[[LLMCallContext], str]):
        _ADAPTERS[name] = func
        if default:
            _ADAPTERS[None] = func  # type: ignore[index]
        return func

    return _wrap


def get_adapter(name: str) -> Callable[[LLMCallContext], str]:
    """按 adapter 名查表返回 generate 函数；未注册时回退默认（openai_compatible）。"""
    # 触发各 adapter 模块加载与注册（首次调用时）。
    _ensure_adapters_loaded()
    return _ADAPTERS.get(name) or _ADAPTERS[None]


_adapters_loaded = False


def _ensure_adapters_loaded():
    global _adapters_loaded
    if _adapters_loaded:
        return
    # 显式 import 触发各 adapter 的 @register_adapter 注册。
    from app.services.llm_adapters import (  # noqa: F401
        azure,
        cloudflare,
        gemini,
        litellm,
        modelscope,
        openai_compatible,
        qwen,
    )
    _adapters_loaded = True
