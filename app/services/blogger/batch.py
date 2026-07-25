"""批量视频生成 — 用一组选题 + 博主风格, 一次性入队多个视频任务。

复用 MPT 现有的 task 队列 (controllers.v1.video 的 task_manager 单例) 和
task.start 流水线, 不另造队列。每个任务都带上 blogger_style_id, 走博主风格注入。
"""
from typing import Any, Dict, List, Union

from loguru import logger

from app.controllers.manager.base_manager import TaskQueueFullError
from app.services.blogger import profiles
from app.utils import utils


def _topic_to_subject(topic: Union[str, Dict[str, Any]]) -> str:
    if isinstance(topic, dict):
        return str(
            topic.get("reference_title")
            or topic.get("direction")
            or topic.get("title")
            or ""
        ).strip()
    return str(topic or "").strip()


def create_batch(
    profile_id: str,
    topics: List[Union[str, Dict[str, Any]]],
    params_template,
    stop_at: str = "video",
) -> Dict[str, Any]:
    """对每个选题克隆一份 params, 套上博主风格, 入队一个视频任务。

    Args:
        profile_id: 博主档案 id (必须已蒸馏)
        topics: 选题列表, 每项可以是字符串或 {reference_title/direction/...} dict
        params_template: VideoParams 模板 (其它参数沿用, 仅覆盖 video_subject/blogger_style_id)
        stop_at: 流水线停止阶段, 默认 "video" (完整生成)

    Returns:
        {profile_id, created:[{task_id, subject}], skipped_full:int, skipped_empty:int}
    """
    # 懒导入避免 services -> controllers 的模块加载期循环依赖。
    from app.controllers.v1.video import task_manager
    from app.services import state as sm
    from app.services import task as tm

    if not profiles.get_style(profile_id):
        raise ValueError(f"blogger profile not found: {profile_id}")

    created: List[Dict[str, str]] = []
    skipped_full = 0
    skipped_empty = 0

    for topic in topics or []:
        subject = _topic_to_subject(topic)
        if not subject:
            skipped_empty += 1
            continue

        params = params_template.model_copy(deep=True)
        params.video_subject = subject
        # 批量任务必须重新生成脚本 (套用博主风格), 不能沿用模板里可能存在的旧脚本。
        params.video_script = ""
        params.blogger_style_id = profile_id

        task_id = utils.get_uuid()
        try:
            sm.state.update_task(task_id)
            task_manager.add_task(
                tm.start, task_id=task_id, params=params, stop_at=stop_at
            )
            created.append({"task_id": task_id, "subject": subject})
            logger.info(f"batch task enqueued: {task_id} subject={subject!r}")
        except TaskQueueFullError:
            skipped_full += 1
            logger.warning(
                f"batch task rejected (queue full): profile={profile_id} subject={subject!r}"
            )

    logger.info(
        f"batch created for profile {profile_id}: "
        f"enqueued={len(created)} skipped_full={skipped_full} skipped_empty={skipped_empty}"
    )
    return {
        "profile_id": profile_id,
        "created": created,
        "skipped_full": skipped_full,
        "skipped_empty": skipped_empty,
    }
