"""选题策划 — 基于博主风格生成新选题。

Phase 1 蒸馏时已经产出过一批 topic_ideas (存在档案里); 这里提供「按需再生成」
能力: 给定博主风格 + 可选聚焦方向, 调 LLM 产出本周/本主题的新选题, 供批量生成视频。
复用 distill._generate_json 的 JSON 解析/重试模式。
"""
from typing import Any, Dict, List

from loguru import logger

from app.services import llm
from app.services.blogger import distill

ROLE = "你是资深的短视频/图文选题策划师, 擅长基于某个博主的内容基因, 推演出 TA 还能做、且大概率会火的选题。"


def _style_digest(style: Dict[str, Any]) -> Dict[str, Any]:
    """从完整 style 里抽出对选题最有用的部分, 控制提示词体积。"""
    meta = style.get("meta") or {}
    cognition = style.get("cognition") or {}
    content = style.get("content") or {}
    return {
        "blogger": meta.get("nickname"),
        "platform": meta.get("platform"),
        "value_stance": cognition.get("value_stance") or {},
        "title_formulas": [
            {"name": t.get("name"), "template": t.get("template")}
            for t in (content.get("title_formulas") or [])[:5]
        ],
        "tag_strategy": content.get("tag_strategy") or {},
        "existing_topic_ideas": [
            t.get("direction") for t in (style.get("topic_ideas") or [])[:10] if t.get("direction")
        ],
    }


def suggest_topics(
    style: Dict[str, Any],
    count: int = 15,
    focus: str = "",
) -> List[Dict[str, Any]]:
    """按博主风格生成 count 个新选题。

    Args:
        style: 完整 BloggerStyle (来自 profiles.get_style)
        count: 选题数量 (1-30)
        focus: 可选聚焦方向 (如 "AI 工具" / "职场"), 留空则纯按博主基因发散

    Returns:
        [{direction, difficulty(1-5), potential(1-5), reference_title, why}]
    """
    count = max(1, min(30, int(count or 15)))
    digest = _style_digest(style)
    focus_line = f"\n聚焦方向: {focus}" if focus else "\n聚焦方向: 无, 尽量发散, 覆盖博主能力范围内的不同子方向。"

    prompt = (
        f"{ROLE}\n\n"
        f"博主风格摘要:\n{distill._ctx_json(digest)}\n"
        f"{focus_line}\n"
        f"{distill.JSON_RULE}\n"
        f"任务: 生成 {count} 个该博主风格下的新选题 (不要与 existing_topic_ideas 重复)。返回 JSON 数组:\n"
        '[{"direction":"","difficulty":1,"potential":1,"reference_title":"","why":""}]\n'
        "  - direction: 选题方向/一句话标题 (符合博主的 title_formulas)\n"
        "  - difficulty: 1-5, 越大越难做\n"
        "  - potential: 1-5, 越大越可能火\n"
        "  - reference_title: 仿博主风格写的示范标题\n"
        "  - why: 一句话说明为什么值得做 (结合博主价值立场)\n"
    )
    topics = distill._generate_json(prompt, expect="array")
    if not isinstance(topics, list):
        topics = []
    logger.info(f"suggested {len(topics)} topics for blogger {digest.get('blogger')}")
    return topics
