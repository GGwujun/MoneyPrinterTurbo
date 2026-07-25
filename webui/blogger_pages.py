"""博主创作平台的三个 Tab 页面: 博主库 / 选题策划 / 发布台。

放在独立文件以控制 webui/Main.py 的体积。渲染函数接收 tr (i18n) 作为参数,
避免与 Main.py 形成循环导入。后端直接调 app.services.blogger。
"""
import os

import streamlit as st
from loguru import logger

from app.config import config
from app.models.schema import VideoParams
from app.services import blogger as blogger_service
from app.services import llm, state as sm
from app.utils import utils

_PLATFORM_LABEL = {"xhs": "小红书", "douyin": "抖音"}


def _plat(p):
    return _PLATFORM_LABEL.get(p, p or "")


# ---------------------------------------------------------------------------
# Tab 1: 博主库
# ---------------------------------------------------------------------------
def render_blogger_library_tab(tr):
    st.header(tr("博主库"))
    st.caption(tr("蒸馏过的博主创作公式都在这里。可查看、重新蒸馏、下载 HTML 报告或删除。"))

    if st.button(tr("蒸馏新博主"), type="primary", key="lib_open_distill_dialog"):
        st.session_state["blogger_dialog_open"] = True
        st.rerun(scope="app")

    profiles = blogger_service.profiles.list_profiles()
    if not profiles:
        st.info(tr("还没有博主。点击上方「蒸馏新博主」开始。"))
        return

    for p in profiles:
        with st.container(border=True):
            top = st.columns([5, 1])
            top[0].markdown(
                f"**{p.get('nickname')}** · {_plat(p.get('platform'))} · "
                f"{tr('样本')} {p.get('sample_count')} · "
                f"{tr('标题公式')} {p.get('title_formula_count')}"
            )
            if p.get("title_formula_preview"):
                top[0].caption(tr("标题公式参考：") + p["title_formula_preview"])
            if top[1].button(tr("删除"), key=f"lib_del_{p['id']}"):
                blogger_service.profiles.delete_profile(p["id"])
                st.rerun(scope="app")

            full = blogger_service.profiles.get_profile(p["id"])
            if not full:
                continue
            style = full.get("style") or {}
            content = style.get("content") or {}
            cognition = style.get("cognition") or {}

            with st.expander(tr("查看创作公式")):
                beliefs = cognition.get("core_beliefs") or []
                if beliefs:
                    st.markdown(f"**{tr('核心信念')}**")
                    for b in beliefs[:6]:
                        st.markdown(f"- {b.get('belief','')}" + (
                            f"  \n  <span style='color:#888'>{b.get('application','')}</span>"
                            if b.get("application") else ""))
                tf = content.get("title_formulas") or []
                if tf:
                    st.markdown(f"**{tr('标题公式')}**")
                    st.table([{"公式": t.get("name"), "模板": t.get("template"),
                               "范例": t.get("example_title")} for t in tf[:5]])
                openings = content.get("opening_templates") or []
                if openings:
                    st.markdown(f"**{tr('开头模板')}**")
                    for o in openings[:3]:
                        st.markdown(f"- **{o.get('type','')}**: {o.get('example','')}")
                topics = style.get("topic_ideas") or []
                if topics:
                    st.markdown(f"**{tr('选题灵感')}** ({len(topics)})")
                    for t in topics[:8]:
                        st.markdown(f"- {t.get('direction','')}")

            # HTML 报告下载
            report_path = full.get("report_path")
            if report_path and os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                st.download_button(
                    tr("下载 HTML 蒸馏报告"),
                    data=html_content,
                    file_name=f"{p.get('nickname','blogger')}_蒸馏报告.html",
                    mime="text/html",
                    key=f"lib_dl_{p['id']}",
                )


# ---------------------------------------------------------------------------
# Tab 2: 选题策划
# ---------------------------------------------------------------------------
def render_topic_planner_tab(tr):
    st.header(tr("选题策划"))
    st.caption(tr("选定一个博主风格，AI 按 TA 的基因生成一批新选题；点选题即可套用风格生成视频。"))

    profiles = blogger_service.profiles.list_profiles()
    if not profiles:
        st.info(tr("先去「博主蒸馏」蒸馏一个博主。"))
        return

    options = {p["id"]: f"{p['nickname']} · {_plat(p.get('platform'))}" for p in profiles}
    sel_id = st.selectbox(tr("选择博主风格"), options=list(options.keys()),
                          format_func=lambda i: options[i], key="topic_planner_profile")
    profile = blogger_service.profiles.get_profile(sel_id)
    if not profile:
        return
    style = profile.get("style") or {}

    col1, col2, col3 = st.columns([2, 1, 1])
    focus = col1.text_input(tr("聚焦方向（可选）"), placeholder=tr("如：AI 工具 / 职场 / 美食"),
                            key="topic_focus")
    count = col2.slider(tr("选题数"), 5, 20, 10, key="topic_count")

    if st.button(tr("生成选题"), type="primary", key="gen_topics"):
        try:
            with st.spinner(tr("AI 生成选题中…")):
                ideas = blogger_service.topics.suggest_topics(style, count=count, focus=focus)
            st.session_state["topic_ideas"] = ideas
        except Exception as e:
            logger.exception("topic suggestion failed")
            st.error(tr(f"生成失败：{e}"))
            # 回退到已蒸馏的选题
            st.session_state["topic_ideas"] = style.get("topic_ideas") or []

    ideas = st.session_state.get("topic_ideas") or style.get("topic_ideas") or []
    if not ideas:
        st.caption(tr("点击「生成选题」开始。"))
        return

    st.subheader(tr(f"共 {len(ideas)} 个选题"))
    for idx, idea in enumerate(ideas):
        if not isinstance(idea, dict):
            idea = {"direction": str(idea)}
        with st.container(border=True):
            c = st.columns([6, 1])
            c[0].markdown(
                f"**{idea.get('direction','')}**  "
                f"`{tr('难度')} {idea.get('difficulty','?')}` "
                f"`{tr('潜力')} {idea.get('potential','?')}`"
            )
            ref = idea.get("reference_title") or idea.get("direction", "")
            why = idea.get("why", "")
            if ref:
                c[0].caption(tr("示范标题：") + ref)
            if why:
                c[0].caption(why)
            if c[1].button(tr("用此选题"), key=f"use_topic_{idx}", use_container_width=True):
                st.session_state["video_subject"] = ref or idea.get("direction", "")
                st.session_state["blogger_style_id_select"] = sel_id
                st.session_state["platform_view"] = "视频生成"
                st.success(tr("已填入视频主题并切换到「视频生成」，点击生成即可套用该博主风格。"))
                st.rerun(scope="app")


# ---------------------------------------------------------------------------
# Tab 3: 发布台
# ---------------------------------------------------------------------------
def render_publish_console_tab(tr):
    st.header(tr("发布台"))
    st.caption(tr("用一组选题 + 博主风格批量生成视频；完成的视频可下载并生成发布文案。"))

    profiles = blogger_service.profiles.list_profiles()
    if not profiles:
        st.info(tr("先去「博主蒸馏」蒸馏一个博主。"))
        return

    options = {p["id"]: f"{p['nickname']} · {_plat(p.get('platform'))}" for p in profiles}
    sel_id = st.selectbox(tr("选择博主风格"), options=list(options.keys()),
                          format_func=lambda i: options[i], key="publish_profile")

    topics_text = st.text_area(
        tr("选题（每行一个）"), height=120,
        placeholder=tr("每行一个选题标题，将套用该博主风格批量生成"),
        key="publish_topics",
    )

    if st.button(tr("批量生成视频"), type="primary", key="publish_batch"):
        topics = [t.strip() for t in (topics_text or "").splitlines() if t.strip()]
        if not topics:
            st.warning(tr("请先填写至少一个选题。"))
        else:
            try:
                template = VideoParams(video_subject="")
                result = blogger_service.batch.create_batch(sel_id, topics, template)
                st.success(
                    tr(f"已入队 {len(result['created'])} 个任务")
                    + (tr(f"，队列满跳过 {result['skipped_full']}") if result["skipped_full"] else "")
                )
                st.caption(tr("在顶部「任务管理器」查看生成进度。"))
            except Exception as e:
                logger.exception("batch create failed")
                st.error(tr(f"批量生成失败：{e}"))

    # 已完成的本博主视频
    st.divider()
    st.subheader(tr("该博主已完成的视频"))
    completed = _list_completed_for_profile(sel_id)
    if not completed:
        st.caption(tr("还没有完成的视频。"))
        return
    for task in completed[:20]:
        with st.container(border=True):
            subj = (task.get("params") or {}).get("video_subject", "")
            st.markdown(f"**{subj}**")
            videos = task.get("videos") or []
            for v in videos:
                url = v.get("url") if isinstance(v, dict) else None
                if url:
                    st.video(url)
                    st.caption(url)
            if st.button(tr("生成发布文案"), key=f"caption_{task.get('task_id')}"):
                _generate_and_show_caption(task, tr)


def _list_completed_for_profile(profile_id):
    try:
        data = sm.state.get_all_tasks(page=1, page_size=200)
    except Exception:
        return []
    tasks = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(tasks, list):
        return []
    out = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        params = t.get("params") or {}
        if params.get("blogger_style_id") != profile_id:
            continue
        if t.get("state") != 1:  # COMPLETE
            continue
        out.append(t)
    out.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return out


def _generate_and_show_caption(task, tr):
    task_id = task.get("task_id")
    script = ""
    try:
        script_path = os.path.join(utils.task_dir(task_id), "script.json")
        if os.path.exists(script_path):
            import json
            with open(script_path, "r", encoding="utf-8") as f:
                script = (json.load(f) or {}).get("video_script", "")
    except Exception:
        script = ""
    subject = (task.get("params") or {}).get("video_subject", "")
    try:
        meta = llm.generate_social_metadata(video_subject=subject, video_script=script)
        st.markdown(f"**{tr('标题')}**: {meta.get('title','')}")
        st.markdown(f"**{tr('文案')}**: {meta.get('caption','')}")
        tags = " ".join(meta.get("hashtags", []))
        if tags:
            st.markdown(f"**{tr('标签')}**: {tags}")
            st.caption(tr("已复制标签到剪贴板（手动复制下方文本）"))
        st.text_area(tr("完整发布文案"), value=f"{meta.get('title','')}\n\n{meta.get('caption','')}\n\n{tags}",
                     height=160, key=f"caption_text_{task_id}")
    except Exception as e:
        st.error(tr(f"生成文案失败：{e}"))
