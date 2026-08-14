"""Cloudflare AI Gateway adapter。

Cloudflare 当前推荐的 AI Gateway REST API 兼容 OpenAI SDK。Account ID 用于构造
统一端点，Gateway ID 通过请求头选择。
"""
from openai import OpenAI
from openai.types.chat import ChatCompletion

from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _extract_chat_completion_text

_ADAPTER_NAME = "cloudflare_ai_gateway"


@register_adapter(_ADAPTER_NAME)
def generate(ctx: LLMCallContext) -> str:
    account_id = ctx.extra_values["account_id"]
    gateway_id = ctx.extra_values["gateway_id"]
    client = OpenAI(
        api_key=ctx.api_key,
        base_url=(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
        ),
        default_headers={"cf-aig-gateway-id": gateway_id},
    )
    response = client.chat.completions.create(
        model=ctx.model_name,
        messages=[{"role": "user", "content": ctx.prompt}],
    )
    return _extract_chat_completion_text(response, ctx.provider_id)
