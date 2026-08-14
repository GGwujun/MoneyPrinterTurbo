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

_PLATFORM_KEYS = {"xhs": "Xiaohongshu", "douyin": "Douyin"}


def _plat(p, tr):
    """返回平台的本地化名称；tr 由调用方传入。"""
    key = _PLATFORM_KEYS.get(p)
    return tr(key) if key else (p or "")


# 顶部平台导航的稳定内部值（不随语言变化），与 Main.py 保持一致。
PLATFORM_VIEW_VIDEO_GEN = "video_gen"


# ---------------------------------------------------------------------------
# Tab 1: 博主库
# ---------------------------------------------------------------------------
def render_blogger_library_tab(tr):
    st.header(tr("Blogger Library"))
    st.caption(tr("Blogger Library Intro"))

    if st.button(tr("Distill New Blogger"), type="primary", key="lib_open_distill_dialog",
                 icon=":material/auto_awesome:"):
        st.session_state["blogger_dialog_open"] = True
        st.rerun(scope="app")

    profiles = blogger_service.profiles.list_profiles()
    if not profiles:
        st.info(tr("No Bloggers Hint"))
        return

    for p in profiles:
        with st.container(border=True):
            top = st.columns([5, 1])
            top[0].markdown(
                f"**{p.get('nickname')}** · {_plat(p.get('platform'), tr)} · "
                f"{tr('Samples')} {p.get('sample_count')} · "
                f"{tr('Title Formulas')} {p.get('title_formula_count')}"
            )
            if p.get("title_formula_preview"):
                top[0].caption(tr("Title Formula Reference") + p["title_formula_preview"])
            if top[1].button(tr("Delete"), key=f"lib_del_{p['id']}",
                             icon=":material/delete:"):
                blogger_service.profiles.delete_profile(p["id"])
                st.rerun(scope="app")

            full = blogger_service.profiles.get_profile(p["id"])
            if not full:
                continue
            style = full.get("style") or {}
            content = style.get("content") or {}
            cognition = style.get("cognition") or {}

            with st.expander(tr("View Creative Formula")):
                beliefs = cognition.get("core_beliefs") or []
                if beliefs:
                    st.markdown(f"**{tr('Core Beliefs')}**")
                    for b in beliefs[:6]:
                        st.markdown(f"- {b.get('belief','')}" + (
                            f"  \n  <span style='color:#888'>{b.get('application','')}</span>"
                            if b.get("application") else ""))
                tf = content.get("title_formulas") or []
                if tf:
                    st.markdown(f"**{tr('Title Formulas')}**")
                    st.table([{tr("Formula"): t.get("name"), tr("Template"): t.get("template"),
                               tr("Example"): t.get("example_title")} for t in tf[:5]])
                openings = content.get("opening_templates") or []
                if openings:
                    st.markdown(f"**{tr('Opening Templates')}**")
                    for o in openings[:3]:
                        st.markdown(f"- **{o.get('type','')}**: {o.get('example','')}")
                topics = style.get("topic_ideas") or []
                if topics:
                    st.markdown(f"**{tr('Topic Inspirations')}** ({len(topics)})")
                    for t in topics[:8]:
                        st.markdown(f"- {t.get('direction','')}")

            # HTML 报告下载
            report_path = full.get("report_path")
            if report_path and os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                st.download_button(
                    tr("Download HTML Report"),
                    data=html_content,
                    file_name=f"{p.get('nickname','blogger')}_distill_report.html",
                    mime="text/html",
                    key=f"lib_dl_{p['id']}",
                )


# ---------------------------------------------------------------------------
# Tab 2: 选题策划
# ---------------------------------------------------------------------------
def render_topic_planner_tab(tr):
    st.header(tr("Topic Planning"))
    st.caption(tr("Topic Planning Intro"))

    profiles = blogger_service.profiles.list_profiles()
    if not profiles:
        st.info(tr("No Distilled Bloggers"))
        return

    options = {p["id"]: f"{p['nickname']} · {_plat(p.get('platform'), tr)}" for p in profiles}
    sel_id = st.selectbox(tr("Select Blogger Style"), options=list(options.keys()),
                          format_func=lambda i: options[i], key="topic_planner_profile")
    profile = blogger_service.profiles.get_profile(sel_id)
    if not profile:
        return
    style = profile.get("style") or {}

    col1, col2, col3 = st.columns([2, 1, 1])
    focus = col1.text_input(tr("Focus Direction"), placeholder=tr("Focus Direction Placeholder"),
                            key="topic_focus")
    count = col2.slider(tr("Topic Count"), 5, 20, 10, key="topic_count")

    if st.button(tr("Generate Topics"), type="primary", key="gen_topics",
                 icon=":material/lightbulb:"):
        try:
            with st.spinner(tr("Generating Topics")):
                ideas = blogger_service.topics.suggest_topics(style, count=count, focus=focus)
            st.session_state["topic_ideas"] = ideas
        except Exception as e:
            logger.exception("topic suggestion failed")
            st.error(tr("Generate Topics Failed").format(error=e))
            # 回退到已蒸馏的选题
            st.session_state["topic_ideas"] = style.get("topic_ideas") or []

    ideas = st.session_state.get("topic_ideas") or style.get("topic_ideas") or []
    if not ideas:
        st.caption(tr("Click Generate Topics Hint"))
        return

    st.subheader(tr("Topics Count").format(count=len(ideas)))
    for idx, idea in enumerate(ideas):
        if not isinstance(idea, dict):
            idea = {"direction": str(idea)}
        with st.container(border=True):
            c = st.columns([6, 1])
            c[0].markdown(
                f"**{idea.get('direction','')}**  "
                f"`{tr('Difficulty')} {idea.get('difficulty','?')}` "
                f"`{tr('Potential')} {idea.get('potential','?')}`"
            )
            ref = idea.get("reference_title") or idea.get("direction", "")
            why = idea.get("why", "")
            if ref:
                c[0].caption(tr("Example Title") + ref)
            if why:
                c[0].caption(why)
            if c[1].button(tr("Use This Topic"), key=f"use_topic_{idx}",
                           use_container_width=True, icon=":material/arrow_forward:"):
                st.session_state["video_subject"] = ref or idea.get("direction", "")
                st.session_state["blogger_style_id_select"] = sel_id
                st.session_state["platform_view"] = PLATFORM_VIEW_VIDEO_GEN
                st.success(tr("Topic Applied Hint"))
                st.rerun(scope="app")


# ---------------------------------------------------------------------------
# Tab 3: 发布台
# ---------------------------------------------------------------------------
def render_publish_console_tab(tr):
    st.header(tr("Publish Desk"))
    st.caption(tr("Publish Desk Intro"))

    profiles = blogger_service.profiles.list_profiles()
    if not profiles:
        st.info(tr("No Distilled Bloggers"))
        return

    options = {p["id"]: f"{p['nickname']} · {_plat(p.get('platform'), tr)}" for p in profiles}
    sel_id = st.selectbox(tr("Select Blogger Style"), options=list(options.keys()),
                          format_func=lambda i: options[i], key="publish_profile")

    topics_text = st.text_area(
        tr("Topics Per Line"), height=120,
        placeholder=tr("Topics Per Line Placeholder"),
        key="publish_topics",
    )

    if st.button(tr("Batch Generate Videos"), type="primary", key="publish_batch",
                 icon=":material/queue:"):
        topics = [t.strip() for t in (topics_text or "").splitlines() if t.strip()]
        if not topics:
            st.warning(tr("Fill At Least One Topic"))
        else:
            try:
                template = VideoParams(video_subject="")
                result = blogger_service.batch.create_batch(sel_id, topics, template)
                st.success(
                    tr("Batch Enqueued").format(created=len(result['created']))
                    + (tr("Batch Queue Full Skipped").format(skipped=result['skipped_full'])
                       if result["skipped_full"] else "")
                )
                st.caption(tr("Check Task Manager Hint"))
            except Exception as e:
                logger.exception("batch create failed")
                st.error(tr("Batch Generate Failed").format(error=e))

    # 已完成的本博主视频
    st.divider()
    st.subheader(tr("Completed Videos For Blogger"))
    completed = _list_completed_for_profile(sel_id)
    if not completed:
        st.caption(tr("No Completed Videos"))
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
            if st.button(tr("Generate Caption"), key=f"caption_{task.get('task_id')}",
                         icon=":material/edit_note:"):
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
        st.markdown(f"**{tr('Title')}**: {meta.get('title','')}")
        st.markdown(f"**{tr('Caption')}**: {meta.get('caption','')}")
        tags = " ".join(meta.get("hashtags", []))
        if tags:
            st.markdown(f"**{tr('Tags')}**: {tags}")
            st.caption(tr("Tags Copied Hint"))
        st.text_area(tr("Full Caption"), value=f"{meta.get('title','')}\n\n{meta.get('caption','')}\n\n{tags}",
                     height=160, key=f"caption_text_{task_id}")
    except Exception as e:
        st.error(tr("Generate Caption Failed").format(error=e))
