"""OpenAI 兼容协议 adapter（默认兜底）。

覆盖 moonshot/deepseek/volcengine/grok/minimax/mimo/groq/aihubmix/aimlapi/
evolink/ollama/oneapi/pollinations 等所有走标准 OpenAI Chat Completions 的 provider。
"""
from openai import OpenAI
from openai.types.chat import ChatCompletion

from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _extract_chat_completion_text


@register_adapter("openai_compatible", default=True)
def generate(ctx: LLMCallContext) -> str:
    client = OpenAI(
        api_key=ctx.api_key,
        base_url=ctx.base_url,
    )

    response = client.chat.completions.create(
        model=ctx.model_name,
        messages=[{"role": "user", "content": ctx.prompt}],
    )
    if response:
        if isinstance(response, ChatCompletion):
            return _extract_chat_completion_text(response, ctx.provider_id)
        raise Exception(
            f'[{ctx.provider_id}] returned an invalid response: "{response}", '
            f"please check your network connection and try again."
        )
    raise Exception(
        f"[{ctx.provider_id}] returned an empty response, please check your "
        f"network connection and try again."
    )
