"""Google Gemini adapter（google-genai SDK）。

使用统一 Client 暴露模型服务，上下文管理器在请求结束后关闭底层 HTTP 连接。
"""
from loguru import logger

from app.services.llm_adapters import LLMCallContext, register_adapter
from app.services.llm_adapters._common import _normalize_text_response


@register_adapter("gemini")
def generate(ctx: LLMCallContext) -> str:
    from google import genai
    from google.genai import types

    http_options = types.HttpOptions(base_url=ctx.base_url) if ctx.base_url else None
    generation_config = types.GenerateContentConfig(
        temperature=0.5,
        top_p=1,
        top_k=1,
        max_output_tokens=2048,
        safety_settings=[
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_ONLY_HIGH",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_ONLY_HIGH",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_ONLY_HIGH",
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_ONLY_HIGH",
            ),
        ],
    )

    try:
        # 新版 google-genai 通过统一 Client 暴露模型服务。上下文管理器
        # 会在请求结束后关闭底层 HTTP 连接，避免频繁生成时积累连接资源。
        with genai.Client(
            api_key=ctx.api_key,
            http_options=http_options,
        ) as client:
            response = client.models.generate_content(
                model=ctx.model_name,
                contents=ctx.prompt,
                config=generation_config,
            )
        generated_text = response.text
    except (AttributeError, IndexError, ValueError) as e:
        logger.warning(f"gemini returned invalid response content: {str(e)}")
        raise ValueError(f"[{ctx.provider_id}] returned invalid response content")

    return _normalize_text_response(generated_text, ctx.provider_id)
