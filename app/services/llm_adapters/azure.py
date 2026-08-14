"""Azure OpenAI adapter。

Azure OpenAI SDK 使用 ``azure_endpoint`` 和 ``api_version`` 生成专用请求地址，
不能复用普通 OpenAI-compatible 的 ``base_url`` 初始化逻辑。
"""
from loguru import logger
from openai import AzureOpenAI
from openai.types.chat import ChatCompletion

from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _extract_chat_completion_text


@register_adapter("azure")
def generate(ctx: LLMCallContext) -> str:
    logger.info(f"requesting azure chat completion, model: {ctx.model_name}")
    client = AzureOpenAI(
        api_key=ctx.api_key,
        api_version=ctx.api_version,
        azure_endpoint=ctx.base_url,
    )
    response = client.chat.completions.create(
        model=ctx.model_name, messages=[{"role": "user", "content": ctx.prompt}]
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
