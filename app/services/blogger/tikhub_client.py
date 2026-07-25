"""TikHub 爬虫薄封装。

把 vendored 的 crawl_xhs / crawl_douyin / analyze 串成一条干净的调用链, 并用
config.tikhub 的 token 驱动它们 (D3: 显式传入 token, 不污染进程环境变量,
也不写 ~/.xiaohongshu/tikhub_config.json)。

中间产物落在 storage/bloggers/_work/{work_id}/ 下; 最终蒸馏用的 details
统一写成 details.json, 与平台无关, 方便后续 analyze / distill。
"""
import json
import os
from typing import Any, Dict, Optional

from loguru import logger

from app.config import config
from app.services.blogger.vendor import analyze, crawl_douyin, crawl_xhs
from app.utils import utils


class TikHubConfigError(RuntimeError):
    """TikHub 未配置或配置无效 (缺 token 等)。"""


def _resolve_token() -> str:
    token = str(config.tikhub.get("tikhub_api_key", "") or "").strip()
    if not token:
        raise TikHubConfigError(
            "tikhub_api_key 未配置。请在 config.toml 的 [tikhub] 段填写你的 TikHub API Token "
            "(注册地址: https://user.tikhub.io), 并在控制台勾选全部 xiaohongshu / douyin 端点权限。"
        )
    return token


def _work_dir(work_id: str) -> str:
    return utils.storage_dir(f"bloggers/_work/{work_id}", create=True)


def crawl(
    nickname: str,
    platform: str = "xhs",
    max_notes: int = 30,
    work_id: Optional[str] = None,
    transcript: bool = False,
) -> Dict[str, Any]:
    """采集一个博主的全量笔记/视频。

    Args:
        nickname: 博主搜索关键词 (昵称)
        platform: "xhs" (小红书) 或 "douyin" (抖音)
        max_notes: 采集条数
        work_id: 工作目录 id; 不传则自动生成
        transcript: 是否提取视频口播 (Phase 1 默认 False, 需 Whisper)

    Returns:
        {work_id, work_dir, details_path, nickname, profile, sample_count}
    """
    token = _resolve_token()
    platform = (platform or "").lower()
    work_id = work_id or utils.get_uuid(remove_hyphen=True)
    work_dir = _work_dir(work_id)
    max_notes = max(1, int(max_notes or 30))

    logger.info(
        f"crawl blogger: nickname={nickname}, platform={platform}, max_notes={max_notes}"
    )

    if platform == "xhs":
        result = crawl_xhs.crawl_blogger(
            keyword=nickname,
            output_dir=work_dir,
            token=token,
            max_notes=max_notes,
            transcript=transcript,
        )
    elif platform == "douyin":
        result = crawl_douyin.crawl_douyin(
            keyword=nickname,
            output_dir=work_dir,
            token=token,
            max_videos=max_notes,
            transcript=transcript,
        )
    else:
        raise ValueError(f"unsupported platform: {platform!r} (expected 'xhs' or 'douyin')")

    details = result.get("details") or []
    # 把 details 统一写成平台无关的固定路径, 供后续 analyze/distill 复用,
    # 不依赖 vendored 的 {safe_name}_{notes|videos}_details.json 命名约定。
    details_path = os.path.join(work_dir, "details.json")
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2)

    resolved_nickname = result.get("nickname") or nickname
    profile = result.get("profile") or {}

    logger.info(
        f"crawl done: nickname={resolved_nickname}, sample_count={len(details)}, "
        f"work_dir={work_dir}"
    )
    return {
        "work_id": work_id,
        "work_dir": work_dir,
        "details_path": details_path,
        "nickname": resolved_nickname,
        "profile": profile,
        "sample_count": len(details),
    }


def analyze_details(details_path: str) -> Dict[str, Any]:
    """对采集到的 details 做确定性统计分析, 返回 analysis dict。

    结构见 vendored analyze.analyze_notes: notes/stats/category_stats/
    tag_freq/top10/opinion_candidates/writing_structure/value_words 等。
    """
    if not os.path.exists(details_path):
        raise FileNotFoundError(f"details file not found: {details_path}")
    analysis = analyze.analyze_notes(details_path)
    logger.info(
        f"analyze done: notes={analysis.get('stats', {}).get('total')}, "
        f"top10={len(analysis.get('top10') or [])}, "
        f"tags={len(analysis.get('tag_freq') or [])}"
    )
    return analysis
