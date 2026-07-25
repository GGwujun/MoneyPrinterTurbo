"""博主风格档案的 CRUD 存储。

档案是 CRUD 实体 (不像 task 那样有运行时进度状态), 因此存成普通 JSON 文件,
不复用 app/services/state.py (那是 task 形状的、按 task_id + 硬编码字段)。

存储位置: storage/bloggers/{profile_id}.json  (见 app.utils.utils.storage_dir)
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.utils import utils


def _bloggers_dir() -> str:
    return utils.storage_dir("bloggers", create=True)


def _profile_path(profile_id: str) -> str:
    return os.path.join(_bloggers_dir(), f"{profile_id}.json")


def _safe_load(profile_id: str) -> Optional[Dict[str, Any]]:
    path = _profile_path(profile_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"failed to read blogger profile {profile_id}: {e}")
        return None


def _summary(profile: Dict[str, Any]) -> Dict[str, Any]:
    """列表/下拉用的精简视图, 不把整个 style 都返回。"""
    style = profile.get("style") or {}
    content = style.get("content") or {}
    title_formulas = content.get("title_formulas") or []
    # 取第一条标题公式名称做一行摘要
    first_formula = title_formulas[0].get("name") if title_formulas else ""
    return {
        "id": profile.get("id"),
        "nickname": profile.get("nickname"),
        "platform": profile.get("platform"),
        "created_at": profile.get("created_at"),
        "sample_count": (profile.get("source") or {}).get("sample_count"),
        "title_formula_count": len(title_formulas),
        "title_formula_preview": first_formula,
    }


def create_profile(
    nickname: str,
    platform: str,
    style: Dict[str, Any],
    source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """新建并落盘一个博主档案, 返回完整档案 dict。"""
    profile_id = utils.get_uuid(remove_hyphen=True)
    profile = {
        "id": profile_id,
        "nickname": nickname,
        "platform": platform,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": source or {},
        "style": style,
    }
    path = _profile_path(profile_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    logger.info(f"created blogger profile: {nickname} ({platform}) -> {profile_id}")
    return profile


def get_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    return _safe_load(profile_id)


def list_profiles() -> List[Dict[str, Any]]:
    """返回所有档案的精简摘要, 按创建时间倒序。"""
    bloggers_dir = _bloggers_dir()
    if not os.path.isdir(bloggers_dir):
        return []
    summaries: List[Dict[str, Any]] = []
    for name in os.listdir(bloggers_dir):
        if not name.endswith(".json"):
            continue
        profile = _safe_load(name[:-5])
        if profile:
            summaries.append(_summary(profile))
    summaries.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return summaries


def delete_profile(profile_id: str) -> bool:
    path = _profile_path(profile_id)
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
        logger.info(f"deleted blogger profile: {profile_id}")
        return True
    except OSError as e:
        logger.warning(f"failed to delete blogger profile {profile_id}: {e}")
        return False


def update_profile(profile_id: str, **fields) -> Optional[Dict[str, Any]]:
    """增量更新档案字段 (如写入 report_path), 返回更新后的档案或 None。"""
    profile = _safe_load(profile_id)
    if not profile:
        return None
    profile.update(fields)
    path = _profile_path(profile_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"failed to update blogger profile {profile_id}: {e}")
        return None
    return profile


def get_style(profile_id: str) -> Optional[Dict[str, Any]]:
    """task.py 注入风格时用的便捷取值; 档案不存在返回 None。"""
    profile = get_profile(profile_id)
    if not profile:
        return None
    return profile.get("style")
