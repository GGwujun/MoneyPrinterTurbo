"""把蒸馏出的 BloggerStyle JSON 渲染成单文件 HTML 报告。

blogger-distiller 原本的 HTML 报告是 AI Agent 读 AI蒸馏任务.md 现场生成的
(严格设计规格)。集成进 MPT 后没有 Agent, 这里改成从已经蒸馏好的结构化
BloggerStyle JSON 确定性渲染 —— 可靠、零 LLM 成本、随时可重新生成。
"""
import html
from typing import Any, Dict, List

from app.utils import utils


def _esc(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _join(items: List[Any], sep: str = "、") -> str:
    return _esc(sep.join(str(i) for i in (items or []) if i))


def _section(title: str, body_html: str) -> str:
    return f'<section><h2>{_esc(title)}</h2>{body_html}</section>'


def _table(headers: List[str], rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return '<p class="muted">（无数据）</p>'
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{_esc(r.get(h, ''))}</td>" for h in headers) + "</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _kv(pairs) -> str:
    items = "".join(
        f"<div class='kv'><span class='k'>{_esc(k)}</span><span class='v'>{_esc(v)}</span></div>"
        for k, v in pairs
        if v not in (None, "", [], {})
    )
    return f"<div class='kvgrid'>{items}</div>" or '<p class="muted">（无数据）</p>'


def render_html_report(style: Dict[str, Any]) -> str:
    meta = style.get("meta") or {}
    cognition = style.get("cognition") or {}
    strategy = style.get("strategy") or {}
    content = style.get("content") or {}
    nickname = meta.get("nickname", "博主")
    platform = {"xhs": "小红书", "douyin": "抖音"}.get(meta.get("platform"), meta.get("platform", ""))

    parts: List[str] = []

    # 摘要
    vs = cognition.get("value_stance") or {}
    parts.append(
        _section(
            "一眼看清",
            _kv(
                [
                    ("博主", nickname),
                    ("平台", platform),
                    ("样本数", meta.get("sample_count")),
                    ("内容底色", vs.get("one_line_summary")),
                    ("语调基调", vs.get("tone")),
                ]
            ),
        )
    )

    # 认知层
    cog_body = ""
    beliefs = cognition.get("core_beliefs") or []
    if beliefs:
        cog_body += "<h3>核心信念</h3>" + _table(
            ["信念", "应用场景", "局限", "出处"],
            [
                {
                    "信念": b.get("belief"),
                    "应用场景": b.get("application"),
                    "局限": b.get("limitation"),
                    "出处": b.get("evidence_title"),
                }
                for b in beliefs
            ],
        )
    tensions = cognition.get("opinion_tensions") or []
    if tensions:
        cog_body += "<h3>观点张力</h3>" + _table(
            ["张力", "观点A", "观点B", "创作建议"], tensions
        )
    frameworks = cognition.get("thinking_patterns") or []
    if frameworks:
        cog_body += "<h3>思维框架</h3>" + _table(
            ["框架", "描述", "证据"], frameworks
        )
    if not cog_body:
        cog_body = '<p class="muted">（无数据）</p>'
    parts.append(_section("认知层 — TA 怎么想", cog_body))

    # 策略层
    strat_body = ""
    series = strategy.get("series_planning") or []
    if series:
        strat_body += "<h3>系列规划</h3>" + _table(
            ["系列", "条数", "均赞", "节奏", "状态"],
            [
                {
                    "系列": s.get("series"),
                    "条数": s.get("count"),
                    "均赞": s.get("avg_likes"),
                    "节奏": s.get("cadence"),
                    "状态": s.get("status"),
                }
                for s in series
            ],
        )
    ht = strategy.get("hot_topic_strategy") or {}
    if ht:
        strat_body += "<h3>蹭热点策略</h3>" + _kv(
            [("估计占比", ht.get("estimated_ratio")), ("时效要求", ht.get("timing")), ("建议", ht.get("advice"))]
        )
    rules = strategy.get("operating_rules") or []
    if rules:
        strat_body += "<h3>运营准则 If-Then</h3>" + _table(
            ["条件→行动", "证据", "解读"], rules
        )
    if not strat_body:
        strat_body = '<p class="muted">（无数据）</p>'
    parts.append(_section("策略层 — TA 怎么运营", strat_body))

    # 内容层
    content_body = ""
    tf = content.get("title_formulas") or []
    if tf:
        content_body += "<h3>标题公式 TOP5</h3>" + _table(
            ["公式", "使用率", "模板", "范例", "改编建议"],
            [
                {
                    "公式": t.get("name"),
                    "使用率": t.get("usage_rate"),
                    "模板": t.get("template"),
                    "范例": t.get("example_title"),
                    "改编建议": t.get("adaptation"),
                }
                for t in tf
            ],
        )
    openings = content.get("opening_templates") or []
    if openings:
        content_body += "<h3>开头模板 TOP3</h3>" + _table(
            ["类型", "使用率", "结构", "范例", "仿写模板"], openings
        )
    bf = content.get("body_formula") or {}
    if bf:
        content_body += "<h3>正文公式</h3>" + _kv(
            [("骨架", bf.get("skeleton")), ("仿写模板", bf.get("rewrite_template"))]
        )
    lang = content.get("language_dna") or {}
    if lang:
        content_body += "<h3>语言 DNA</h3>" + _kv(
            [
                ("句式节奏", lang.get("sentence_rhythm")),
                ("高频用语", _join(lang.get("frequent_phrases"))),
                ("力量短语", _join(lang.get("power_phrases"))),
                ("人称策略", lang.get("pronouns")),
            ]
        )
    cta = content.get("cta") or {}
    if cta:
        content_body += "<h3>CTA 策略</h3>" + _kv(
            [
                ("主要类型", _join(cta.get("dominant_types"))),
                ("放置位置", cta.get("placement")),
                ("建议", cta.get("advice")),
            ]
        )
    if not content_body:
        content_body = '<p class="muted">（无数据）</p>'
    parts.append(_section("内容层 — TA 怎么写", content_body))

    # 创作禁区
    forbidden = style.get("forbidden") or []
    if forbidden:
        parts.append(
            _section(
                "创作禁区 — TA 绝不会做",
                _table(["模式", "示例", "证据"], forbidden),
            )
        )

    # 选题灵感池
    topics = style.get("topic_ideas") or []
    if topics:
        parts.append(
            _section(
                "选题灵感池",
                _table(["选题方向", "难度", "潜力", "参考标题", "为什么值得做"], topics),
            )
        )

    # 局限性
    limits = style.get("limitations") or []
    if limits:
        items = "".join(f"<li>{_esc(l)}</li>" for l in limits)
        parts.append(_section("局限性说明", f"<ul>{items}</ul>"))

    body = "".join(parts)
    title = f"{nickname} 创作公式蒸馏报告"
    return _HTML_TEMPLATE.replace("__TITLE__", _esc(title)).replace("__BODY__", body)


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#faf7f2;--card:#fff;--ink:#1a1211;--brick:#8a3926;--muted:#7a6e65;--line:#e3ddd2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Noto Serif SC","Songti SC",serif;line-height:1.7;padding:24px;max-width:920px;margin:0 auto}
h1{font-size:1.6rem;border-bottom:3px solid var(--brick);padding-bottom:8px;margin:0 0 8px}
h2{font-size:1.2rem;color:var(--brick);border-left:4px solid var(--brick);padding-left:10px;margin:28px 0 12px}
h3{font-size:1rem;margin:18px 0 8px;color:#3a2a20}
section{background:var(--card);border:1px solid var(--line);padding:16px 20px;margin:14px 0}
table{width:100%;border-collapse:collapse;font-size:.9rem;margin:8px 0}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f3ede2;font-weight:600}
.muted{color:var(--muted)}
.kvgrid{display:grid;grid-template-columns:1fr 1fr;gap:6px 18px}
.kv{display:flex;gap:8px}.kv .k{color:var(--muted);min-width:84px;font-size:.85rem}
.kv .v{flex:1;word-break:break-word}
ul{margin:6px 0;padding-left:22px}
@media(max-width:600px){.kvgrid{grid-template-columns:1fr}}
</style></head>
<body><h1>__TITLE__</h1>
__BODY__
</body></html>
"""


def save_report(profile_id: str, style: Dict[str, Any]) -> str:
    """渲染并保存 HTML 报告到 storage/bloggers/{id}.html, 返回路径。"""
    bloggers_dir = utils.storage_dir("bloggers", create=True)
    path = f"{bloggers_dir}/{profile_id}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html_report(style))
    return path
