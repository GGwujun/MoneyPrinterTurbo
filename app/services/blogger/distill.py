"""结构化 LLM 蒸馏 — 把博主数据分析成完整 8 层「创作公式」(BloggerStyle)。

blogger-distiller 原本靠 AI Agent 读 AI蒸馏任务.md 现场生成 markdown; 这里把
那 70% 重写成**确定性的多次聚焦 LLM 调用**, 每次返回严格 JSON, 用 llm.generate_terms
已验证的解析模式 (strip code fence → json.loads → 正则兜底 → 重试)。

为什么拆多次而不是一次: 8 层深嵌套 JSON 极易被 LLM 截断/写坏, 一次失败全盘皆输
且无法部分重试。拆成多次后每段 schema 紧凑、可独立重试, 认知层失败不丢内容层。

确定性统计 (vendored deep_analyze 的 extract_title_patterns / extract_cta_patterns /
analyze_content_structure / detect_posting_frequency / find_growth_pattern) 作为
约束提示喂给每次调用, 让 LLM 结论有数据锚点, 而不是凭空生成。
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.services import llm
from app.services.blogger.vendor import deep_analyze as da

_MAX_RETRIES = 4

ROLE = "你是资深的短视频/图文内容策略师, 擅长从博主的真实笔记数据里蒸馏出可复用的创作公式。"
JSON_RULE = (
    "严格要求:\n"
    "1. 只返回一个合法的、minified 的 JSON 对象, 不要 markdown, 不要代码围栏, 不要任何解释文字。\n"
    "2. 所有结论必须基于上方数据, 不得编造博主没发过的内容; 关键结论尽量带上出处 (引用某条标题或数据)。\n"
    "3. 没有数据支撑的字段就留空数组或空字符串, 不要硬凑。\n"
)


# ---------------------------------------------------------------------------
# 工具: LLM → JSON
# ---------------------------------------------------------------------------

def _parse_json(response: str, expect: str) -> Any:
    text = llm._strip_code_fence(response or "")
    try:
        data = json.loads(text)
    except Exception:
        # 兜底: 抽取第一个 {...} 或 [...]
        pattern = r"\{.*\}" if expect == "object" else r"\[.*\]"
        match = re.search(r"" + pattern, response or "", re.DOTALL)
        if not match:
            raise ValueError("no JSON object/array found in response")
        data = json.loads(match.group())
    return data


def _generate_json(prompt: str, expect: str = "object") -> Any:
    last_error = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        response = llm._generate_response(prompt)
        if not response or response.startswith("Error:"):
            last_error = (response or "empty response").removeprefix("Error:").strip()
            logger.warning(f"distill llm call failed (attempt {attempt}): {last_error}")
            continue
        try:
            return _parse_json(response, expect)
        except Exception as e:
            last_error = str(e)
            logger.warning(f"distill json parse failed (attempt {attempt}): {e}")
    raise RuntimeError(f"distill: LLM did not return valid JSON after {_MAX_RETRIES} retries: {last_error}")


# ---------------------------------------------------------------------------
# 数据上下文: analysis.json + details.json → 喂给 LLM 的紧凑上下文
# ---------------------------------------------------------------------------

def _load_details_descs(details_path: str) -> Tuple[List[str], List[str]]:
    """从 details.json 取全部 (titles, descs), 供确定性 pattern 提取。"""
    titles: List[str] = []
    descs: List[str] = []
    if not details_path or not os.path.exists(details_path):
        return titles, descs
    try:
        with open(details_path, "r", encoding="utf-8") as f:
            details = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"failed to load details for distill context: {e}")
        return titles, descs
    for item in details:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        # 小红书/抖音归一化后正文在 desc 字段
        desc = item.get("desc") or ""
        if title:
            titles.append(title)
        if desc:
            descs.append(desc)
    return titles, descs


def _build_context(
    analysis: Dict[str, Any],
    details_path: str,
    nickname: str,
    platform: str,
) -> Dict[str, Any]:
    notes = analysis.get("notes", []) or []
    top10 = analysis.get("top10", []) or []
    stats = analysis.get("stats", {}) or {}

    # 优先用 details.json 全量标题/正文做确定性提取 (质量更高); 没有则退回 notes+top10。
    titles, descs = _load_details_descs(details_path)
    if not titles:
        titles = [n.get("title", "") for n in notes if n.get("title")]
    if not descs:
        descs = [t.get("desc", "") for t in top10 if t.get("desc")]

    title_patterns = da.extract_title_patterns(titles) if titles else {}
    cta_patterns = da.extract_cta_patterns(descs) if descs else {}
    content_struct = da.analyze_content_structure(descs) if descs else {}
    emoji = da.extract_emoji_patterns(descs) if descs else {}
    posting = da.detect_posting_frequency(notes) if notes else {}
    growth = da.find_growth_pattern(notes) if notes else {}

    return {
        "blogger": nickname,
        "platform": platform,
        "sample_count": stats.get("total") or len(notes),
        "stats": {
            "total": stats.get("total"),
            "video_count": stats.get("video_count"),
            "normal_count": stats.get("normal_count"),
            "avg_likes": stats.get("avg_likes"),
            "avg_collects": stats.get("avg_collects"),
            "avg_comments": stats.get("avg_comments"),
        },
        "category_stats": analysis.get("category_stats", {}),
        "tag_freq": (analysis.get("tag_freq") or [])[:20],
        "value_words": (analysis.get("value_words") or [])[:15],
        "opinion_candidates": [
            o.get("sentence") for o in (analysis.get("opinion_candidates") or []) if o.get("sentence")
        ][:20],
        "writing_structure": analysis.get("writing_structure", {}),
        "deterministic_patterns": {
            "title_patterns": title_patterns,
            "cta_patterns": cta_patterns,
            "content_structure": content_struct,
            "emoji": emoji,
            "posting_frequency": posting,
            "growth": growth,
        },
        "top10": [
            {
                "title": t.get("title", ""),
                "desc": (t.get("desc") or "")[:600],
                "likes": t.get("likes"),
                "collects": t.get("collects"),
                "tags": (t.get("tags") or [])[:8],
                "top_comments": [
                    c.get("content")
                    for c in (t.get("comment_list") or [])[:3]
                    if c.get("content")
                ],
            }
            for t in top10
            if t.get("title")
        ],
    }


def _ctx_json(ctx: Dict[str, Any], keys: Optional[List[str]] = None) -> str:
    """把 context 序列化成紧凑 JSON; 可只取部分 key 控制提示词体积。"""
    payload = {k: ctx.get(k) for k in keys} if keys else ctx
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 6 次聚焦蒸馏调用 → 完整 8 层 BloggerStyle
# ---------------------------------------------------------------------------

def _distill_cognition(ctx: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (
        f"{ROLE}\n\n"
        f"以下是博主「{ctx['blogger']}」({ctx['platform']}) 的真实数据:\n"
        f"{_ctx_json(ctx, ['blogger','platform','sample_count','stats','opinion_candidates','value_words','top10'])}\n\n"
        f"{JSON_RULE}\n"
        "任务: 蒸馏【认知层】。返回 JSON:\n"
        "{\n"
        '  "core_beliefs": [{"belief":"","evidence_title":"","application":"","limitation":""}],  // 5-8条核心信念\n'
        '  "opinion_tensions": [{"tension":"","view_a":"","view_b":"","creative_advice":""}],     // 观点张力(矛盾对), 至少1对\n'
        '  "thinking_patterns": [{"framework":"","description":"","evidence_title":""}],            // 思维/认知框架\n'
        '  "value_stance": {"top_value_words":[],"one_line_summary":"","tone":""},                  // 价值立场\n'
        '  "reader_relationship": {"type":"","addressing":"","interaction_style":"","assumed_role":""}\n'
        "}\n"
    )
    return _generate_json(prompt, "object")


def _distill_strategy(ctx: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (
        f"{ROLE}\n\n"
        f"博主「{ctx['blogger']}」的数据:\n"
        f"{_ctx_json(ctx, ['blogger','platform','sample_count','stats','category_stats','tag_freq','deterministic_patterns'])}\n\n"
        f"{JSON_RULE}\n"
        "任务: 蒸馏【策略层】。返回 JSON:\n"
        "{\n"
        '  "series_planning": [{"series":"","count":0,"avg_likes":0,"cadence":"","status":""}],\n'
        '  "hot_topic_strategy": {"estimated_ratio":"","timing":"","advice":""},\n'
        '  "operating_rules": [{"if_then":"","evidence_title":"","interpretation":""}]  // 3-5条 If-Then 运营准则\n'
        "}\n"
    )
    return _generate_json(prompt, "object")


def _distill_content_structure(ctx: Dict[str, Any]) -> Dict[str, Any]:
    dp = ctx.get("deterministic_patterns", {})
    prompt = (
        f"{ROLE}\n\n"
        f"博主「{ctx['blogger']}」的数据 (重点是标题与正文):\n"
        f"{_ctx_json(ctx, ['blogger','platform','top10'])}\n"
        f"确定性统计: {json.dumps({'title_patterns': dp.get('title_patterns'), 'content_structure': dp.get('content_structure')}, ensure_ascii=False)}\n\n"
        f"{JSON_RULE}\n"
        "任务: 蒸馏【内容层 - 结构部分】。返回 JSON:\n"
        "{\n"
        '  "title_formulas": [{"name":"","usage_rate":"","template":"","example_title":"","adaptation":""}],  // TOP5 标题公式\n'
        '  "opening_templates": [{"type":"","usage_rate":"","structure":"","example":"","rewrite_template":""}], // TOP3 开头模板\n'
        '  "body_formula": {"skeleton":"","paragraph_plan":[{"role":"","pct":"","purpose":""}],"rewrite_template":""}\n'
        "}\n"
    )
    return _generate_json(prompt, "object")


def _distill_content_style(ctx: Dict[str, Any]) -> Dict[str, Any]:
    dp = ctx.get("deterministic_patterns", {})
    prompt = (
        f"{ROLE}\n\n"
        f"博主「{ctx['blogger']}」的数据:\n"
        f"{_ctx_json(ctx, ['blogger','platform','top10','value_words'])}\n"
        f"确定性统计: {json.dumps({'cta_patterns': dp.get('cta_patterns'),'emoji': dp.get('emoji'),'posting_frequency': dp.get('posting_frequency')}, ensure_ascii=False)}\n\n"
        f"{JSON_RULE}\n"
        "任务: 蒸馏【内容层 - 风格与节奏部分】。返回 JSON:\n"
        "{\n"
        '  "emotion_rhythm": {"arc":"","peak_methods":[{"method":"","example":""}],"retention_hooks":[]},\n'
        '  "language_dna": {"frequent_phrases":[],"power_phrases":[],"sentence_rhythm":"","pronouns":""},\n'
        '  "cta": {"dominant_types":[],"placement":"","advice":""},\n'
        '  "visual_rules": {"emoji_usage":"","layout":"","image_vs_video":""},\n'
        '  "tag_strategy": {"fixed_tags":[],"domain_tags":[],"hot_tag_rule":""},\n'
        '  "posting_rhythm": {"frequency":"","active_window":"","burst_strategy":""}\n'
        "}\n"
    )
    return _generate_json(prompt, "object")


def _distill_forbidden_and_contrasts(ctx: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (
        f"{ROLE}\n\n"
        f"博主「{ctx['blogger']}」的数据:\n"
        f"{_ctx_json(ctx, ['blogger','platform','sample_count','top10','tag_freq','writing_structure'])}\n\n"
        f"{JSON_RULE}\n"
        "任务: 蒸馏【创作禁区 + 对比示例】。返回 JSON:\n"
        "{\n"
        '  "forbidden": [{"pattern":"","example":"","evidence":""}],  // 3-5条 TA 绝不会做的事\n'
        '  "contrasts": [{"topic":"","ordinary_style":{"title":"","opening":"","body":""},"blogger_style":{"title":"","opening":"","body":""},"key_difference":""}]  // 3组对比\n'
        "}\n"
    )
    return _generate_json(prompt, "object")


def _distill_topics_and_checklist(ctx: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (
        f"{ROLE}\n\n"
        f"博主「{ctx['blogger']}」的数据:\n"
        f"{_ctx_json(ctx, ['blogger','platform','sample_count','category_stats','tag_freq','top10'])}\n\n"
        f"{JSON_RULE}\n"
        "任务: 蒸馏【选题灵感池 + 局限性 + 自检清单】。返回 JSON:\n"
        "{\n"
        '  "topic_ideas": [{"direction":"","difficulty":1,"potential":1,"reference_title":"","why":""}],  // TOP10 选题, difficulty/potential 用1-5\n'
        '  "limitations": [""],  // ≥5条本次蒸馏的局限性\n'
        '  "self_check": [{"item":"","pass_criteria":"","fail_signal":""}]  // 8-10项自检清单\n'
        "}\n"
    )
    return _generate_json(prompt, "object")


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

_STYLE_SHAPE = {
    "cognition": dict,
    "strategy": dict,
    "content": dict,
    "forbidden": list,
    "contrasts": list,
    "topic_ideas": list,
    "limitations": list,
    "self_check": list,
}


def validate_style(style: Dict[str, Any]) -> Dict[str, Any]:
    """加固: 确保 8 层顶层键存在且类型正确, 防止 LLM 偶发返回畸形结构时
    下游 (style_injection / report / 博主库展示) 崩溃。非合规字段强制回退空值。"""
    style = dict(style) if isinstance(style, dict) else {}
    for key, typ in _STYLE_SHAPE.items():
        value = style.get(key)
        if not isinstance(value, typ):
            style[key] = typ()
    if not isinstance(style.get("meta"), dict):
        style["meta"] = {}
    return style


def distill_style(
    analysis: Dict[str, Any],
    nickname: str,
    platform: str = "xhs",
    details_path: Optional[str] = None,
) -> Dict[str, Any]:
    """把 analysis + details 蒸馏成完整 8 层 BloggerStyle。

    Returns:
        {"cognition":{...}, "strategy":{...}, "content":{...},
         "forbidden":[...], "contrasts":[...], "topics":[...],
         "limitations":[...], "self_check":[...],
         "meta": {"nickname","platform","sample_count"}}
    """
    ctx = _build_context(analysis, details_path or "", nickname, platform)
    logger.info(
        f"distill start: blogger={nickname}, platform={platform}, "
        f"sample_count={ctx['sample_count']}, top10={len(ctx['top10'])}"
    )

    steps = [
        ("cognition", _distill_cognition),
        ("strategy", _distill_strategy),
        ("content_structure", _distill_content_structure),
        ("content_style", _distill_content_style),
        ("forbidden_and_contrasts", _distill_forbidden_and_contrasts),
        ("topics_and_checklist", _distill_topics_and_checklist),
    ]

    result: Dict[str, Any] = {}
    for key, fn in steps:
        logger.info(f"distill step: {key}")
        try:
            result[key] = fn(ctx)
        except Exception as e:
            # 单步失败不致命: 记录错误, 该层留空, 其余层继续。这是「拆多次」的核心收益。
            logger.exception(f"distill step '{key}' failed, leaving empty: {e}")
            result[key] = {"_error": str(e)}

    # 把 content 拍平成 SKILL.md 的内容层结构, 方便 style_injection / 博主库展示
    content = {}
    content.update(result.get("content_structure", {}) or {})
    content.update(result.get("content_style", {}) or {})
    if "_error" in (result.get("content_structure") or {}):
        content.setdefault("_errors", []).append(result["content_structure"]["_error"])
    if "_error" in (result.get("content_style") or {}):
        content.setdefault("_errors", []).append(result["content_style"]["_error"])

    fac = result.get("forbidden_and_contrasts", {}) or {}
    tac = result.get("topics_and_checklist", {}) or {}

    style = {
        "cognition": result.get("cognition", {}),
        "strategy": result.get("strategy", {}),
        "content": content,
        "forbidden": fac.get("forbidden", []),
        "contrasts": fac.get("contrasts", []),
        "topic_ideas": tac.get("topic_ideas", []),
        "limitations": tac.get("limitations", []),
        "self_check": tac.get("self_check", []),
        "meta": {
            "nickname": nickname,
            "platform": platform,
            "sample_count": ctx["sample_count"],
        },
    }
    style = validate_style(style)
    logger.success(
        f"distill done: blogger={nickname}, "
        f"core_beliefs={len(style['cognition'].get('core_beliefs') or [])}, "
        f"title_formulas={len(style['content'].get('title_formulas') or [])}, "
        f"topics={len(style['topic_ideas'])}"
    )
    return style
