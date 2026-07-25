"""把蒸馏出的 BloggerStyle 注入到视频脚本生成阶段 (D5)。

MPT 的 llm.generate_script 接受两个注入点:
  - custom_system_prompt : 整体替换默认 system prompt (build_system_prompt)
  - video_script_prompt  : 作为「Additional User Requirements」追加 (build_script_hint)

策略: 用 build_system_prompt 整体替换 system prompt (内含默认脚本硬约束 + 博主风格),
同时把 build_script_hint 追加到用户原有的 video_script_prompt 之后做强化。
两个函数对缺失字段都做了安全兜底 (蒸馏某层失败时仍可用)。
"""
from typing import Any, Dict, List

# 默认脚本硬约束, 沿用 llm.DEFAULT_SCRIPT_SYSTEM_PROMPT 的核心规则, 保证风格化
# 之后脚本仍是干净的口播文本而不是带 markdown 的笔记。
_BASE_CONSTRAINTS = """
## Constrains (脚本格式硬约束, 不可违反):
1. 返回的是视频口播脚本 (voiceover), 按指定段落数返回。
2. 不要任何 markdown、标题、emoji 装饰; 不要 "欢迎收看"、"旁白："、"主持人：" 之类标记。
3. 直奔主题, 开头就要抓人。
4. 用与视频主题相同的语言。
5. 要明显体现下方博主风格 (开头模板、语言DNA、情感节奏、CTA), 但绝不照抄博主原句。
""".strip()


def _s(obj: Any) -> str:
    return str(obj).strip() if obj else ""


def _join(items: List[Any], sep: str = "、", limit: int = 8) -> str:
    cleaned = [_s(i) for i in (items or []) if _s(i)]
    return sep.join(cleaned[:limit])


def _fmt_title_formulas(content: Dict[str, Any]) -> str:
    rows = content.get("title_formulas") or []
    if not rows:
        return ""
    lines = []
    for r in rows[:5]:
        name = _s(r.get("name"))
        tmpl = _s(r.get("template"))
        ex = _s(r.get("example_title"))
        if not (name or tmpl):
            continue
        lines.append(f"  - {name}: 模板「{tmpl}」" + (f" (例: {ex})" if ex else ""))
    return "\n".join(lines)


def _fmt_openings(content: Dict[str, Any]) -> str:
    rows = content.get("opening_templates") or []
    if not rows:
        return ""
    lines = []
    for r in rows[:3]:
        t = _s(r.get("type"))
        ex = _s(r.get("example"))
        if not t:
            continue
        lines.append(f"  - {t}" + (f": {ex}" if ex else ""))
    return "\n".join(lines)


def build_system_prompt(style: Dict[str, Any]) -> str:
    """整体替换默认 system prompt: 基础脚本约束 + 博主风格。"""
    meta = style.get("meta") or {}
    nickname = _s(meta.get("nickname")) or "该博主"
    platform_label = {"xhs": "小红书", "douyin": "抖音"}.get(_s(meta.get("platform")), "")
    sample = _s(meta.get("sample_count")) or ""

    cognition = style.get("cognition") or {}
    value_stance = cognition.get("value_stance") or {}
    beliefs = [b.get("belief") for b in (cognition.get("core_beliefs") or []) if b.get("belief")]
    content = style.get("content") or {}
    emotion = content.get("emotion_rhythm") or {}
    lang = content.get("language_dna") or {}
    cta = content.get("cta") or {}

    title_block = _fmt_title_formulas(content)
    opening_block = _fmt_openings(content)
    skeleton = _s(content.get("body_formula") and content["body_formula"].get("skeleton"))
    para_plan = content.get("body_formula") and content["body_formula"].get("paragraph_plan")
    para_plan_str = ""
    if isinstance(para_plan, list) and para_plan:
        para_plan_str = " | ".join(
            f"{_s(p.get('role'))}({_s(p.get('pct'))})" for p in para_plan if isinstance(p, dict)
        )

    parts = [
        f"# Role: 视频脚本生成器 (复刻{platform_label}博主「{nickname}」的风格)",
        "",
        "## Goals:",
        f"根据给定的视频主题, 用「{nickname}」的内容风格, 生成一段可直接朗读的视频口播脚本。",
        "",
        f"## 博主风格依据 (基于 {sample} 条真实笔记蒸馏):",
        f"- 人设底色: {_s(value_stance.get('one_line_summary')) or '(未知)'}"
        + (f"; 语调基调: {_s(value_stance.get('tone'))}" if value_stance.get("tone") else ""),
    ]
    if beliefs:
        parts.append(f"- 核心信念/观点: {_join(beliefs, sep=';', limit=4)}")
    if title_block:
        parts.append("- 钩子/标题公式:\n" + title_block)
    if opening_block:
        parts.append("- 开头模板:\n" + opening_block)
    if skeleton:
        parts.append(f"- 正文骨架: {skeleton}")
    if para_plan_str:
        parts.append(f"- 段落配比: {para_plan_str}")
    if emotion.get("arc"):
        parts.append(f"- 情感节奏: {_s(emotion.get('arc'))}")
    if emotion.get("retention_hooks"):
        parts.append(f"- 留存钩子: {_join(emotion.get('retention_hooks'), limit=4)}")
    if lang:
        lang_bits = []
        if lang.get("sentence_rhythm"):
            lang_bits.append(f"句式节奏 {_s(lang.get('sentence_rhythm'))}")
        if lang.get("frequent_phrases"):
            lang_bits.append(f"常用语 {_join(lang.get('frequent_phrases'))}")
        if lang.get("power_phrases"):
            lang_bits.append(f"力量短语 {_join(lang.get('power_phrases'))}")
        if lang.get("pronouns"):
            lang_bits.append(f"人称 {_s(lang.get('pronouns'))}")
        if lang_bits:
            parts.append("- 语言DNA: " + "; ".join(lang_bits))
    if cta.get("dominant_types"):
        parts.append(
            f"- CTA: {_join(cta.get('dominant_types'))}"
            + (f", 放在 {_s(cta.get('placement'))}" if cta.get("placement") else "")
        )

    parts.append("")
    parts.append(_BASE_CONSTRAINTS)
    return "\n".join(parts)


def build_script_hint(style: Dict[str, Any]) -> str:
    """追加到 video_script_prompt 的紧凑风格强化 (一行摘要级)。"""
    meta = style.get("meta") or {}
    nickname = _s(meta.get("nickname")) or "该博主"
    content = style.get("content") or {}
    cognition = style.get("cognition") or {}
    lang = content.get("language_dna") or {}
    cta = content.get("cta") or {}

    openings = content.get("opening_templates") or []
    opening_hint = _s(openings[0].get("type")) if openings else ""
    skeleton = _s(content.get("body_formula") and content["body_formula"].get("skeleton"))
    tone = _s((cognition.get("value_stance") or {}).get("tone"))

    bits = [f"复刻博主「{nickname}」的风格"]
    if tone:
        bits.append(f"语调 {tone}")
    if opening_hint:
        bits.append(f"用「{opening_hint}」式开头")
    if skeleton:
        bits.append(f"正文遵循「{skeleton}」")
    if lang.get("frequent_phrases"):
        bits.append(f"多用 {_join(lang.get('frequent_phrases'), limit=5)}")
    if cta.get("dominant_types"):
        bits.append(f"结尾 {_join(cta.get('dominant_types'), limit=2)}")
    if not bits[1:]:
        return bits[0]
    return bits[0] + ": " + ", ".join(bits[1:]) + "。"
