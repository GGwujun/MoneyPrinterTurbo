"""ModelScope (魔搭) adapter。

ModelScope 使用 OpenAI SDK 但强制流式响应（stream=True），并禁用思考模式。
需要手动拼接 chunk 的 delta.content。
"""
from openai import OpenAI

from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _normalize_text_response


@register_adapter("modelscope")
def generate(ctx: LLMCallContext) -> str:
    content = ""
    client = OpenAI(
        api_key=ctx.api_key,
        base_url=ctx.base_url,
    )
    response = client.chat.completions.create(
        model=ctx.model_name,
        messages=[{"role": "user", "content": ctx.prompt}],
        extra_body={"enable_thinking": False},
        stream=True,
    )
    if response:
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                content += delta.content

        if not content.strip():
            raise ValueError("Empty content in stream response")

        return _normalize_text_response(content, ctx.provider_id)
    raise Exception(f"[{ctx.provider_id}] returned an empty response")
