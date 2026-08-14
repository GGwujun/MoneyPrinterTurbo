"""阿里云 DashScope (Qwen) adapter。

DashScope 不用 OpenAI SDK，而是自带 Generation.call，且通过模块级
``dashscope.api_key`` 注入凭据。
"""
from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _extract_qwen_generation_text


@register_adapter("qwen")
def generate(ctx: LLMCallContext) -> str:
    import dashscope
    from dashscope.api_entities.dashscope_response import GenerationResponse

    dashscope.api_key = ctx.api_key
    response = dashscope.Generation.call(
        model=ctx.model_name, messages=[{"role": "user", "content": ctx.prompt}]
    )
    if response:
        if isinstance(response, GenerationResponse):
            status_code = response.status_code
            if status_code != 200:
                raise Exception(
                    f'[{ctx.provider_id}] returned an error response: "{response}"'
                )
            return _extract_qwen_generation_text(response)
        raise Exception(
            f'[{ctx.provider_id}] returned an invalid response: "{response}"'
        )
    raise Exception(f"[{ctx.provider_id}] returned an empty response")
