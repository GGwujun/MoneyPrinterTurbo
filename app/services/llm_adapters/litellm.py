"""LiteLLM adapter（函数式，无 client 对象）。

LiteLLM 通过环境变量配置目标 provider 凭据，使用 ``provider/model`` 格式路由。
"""
from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _extract_chat_completion_text


@register_adapter("litellm")
def generate(ctx: LLMCallContext) -> str:
    import litellm

    if not ctx.model_name:
        raise ValueError(
            f"{ctx.provider_id}: model_name is not set, please set it in the config.toml file."
        )

    response = litellm.completion(
        model=ctx.model_name,
        messages=[{"role": "user", "content": ctx.prompt}],
        drop_params=True,
    )

    if not response:
        raise ValueError(f"[{ctx.provider_id}] returned empty response")
    if not getattr(response, "choices", None):
        raise ValueError(f"[{ctx.provider_id}] returned empty response")

    return _extract_chat_completion_text(response, ctx.provider_id)
