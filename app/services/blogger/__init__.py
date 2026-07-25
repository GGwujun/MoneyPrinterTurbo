"""博主蒸馏 (blogger-distiller) 集成模块。

把 blogger-distiller 的爬虫/分析能力 vendor 进 MoneyPrinterTurbo, 并用
结构化 LLM 调用重写其「蒸馏」环节, 产出可复用的博主创作公式 (BloggerStyle),
再注入到视频生成流水线的脚本阶段。

子模块:
  - vendor/         : 原样复制的 blogger-distiller scripts (爬虫 + 统计分析)
  - tikhub_client   : 薄封装, 用 config.tikhub 的 token 驱动 vendor 爬虫
  - distill         : 结构化 LLM 蒸馏, 产出完整 8 层 BloggerStyle JSON
  - profiles        : 博主档案 CRUD (storage/bloggers/{id}.json)
  - style_injection : 把 BloggerStyle 转成 generate_script 的 prompt 注入
"""
# 导入 vendor 子包以触发 sys.path 作用域 shim, 必须早于任何 vendored 脚本被导入。
from app.services.blogger import vendor  # noqa: F401
from app.services.blogger import (  # noqa: F401
    batch,
    distill,
    profiles,
    report,
    style_injection,
    tikhub_client,
    topics,
)


def run_distillation(nickname, platform="xhs", max_notes=30, transcript=False):
    """端到端: 采集 → 分析 → 蒸馏 → 落盘博主档案。返回完整 profile dict。

    这是 controller / WebUI 对话框调用的单一入口。
    """
    nickname = (nickname or "").strip()
    if not nickname:
        raise ValueError("nickname 不能为空")
    platform = (platform or "xhs").lower()
    if platform not in ("xhs", "douyin"):
        raise ValueError(f"unsupported platform: {platform}")

    # 1) 采集
    crawled = tikhub_client.crawl(
        nickname=nickname, platform=platform, max_notes=max_notes, transcript=transcript
    )
    # 2) 分析
    analysis = tikhub_client.analyze_details(crawled["details_path"])
    # 3) 蒸馏
    style = distill.distill_style(
        analysis=analysis,
        nickname=crawled["nickname"],
        platform=platform,
        details_path=crawled["details_path"],
    )
    # 4) 落盘
    source = {
        "platform": platform,
        "max_notes": max_notes,
        "sample_count": crawled["sample_count"],
        "work_id": crawled["work_id"],
        "profile": crawled["profile"],
    }
    profile = profiles.create_profile(
        nickname=crawled["nickname"], platform=platform, style=style, source=source
    )
    # 生成 HTML 蒸馏报告并记录路径, 供博主库详情页下载/打开。
    try:
        report_path = report.save_report(profile["id"], style)
        profile = profiles.update_profile(profile["id"], report_path=report_path) or profile
    except Exception as e:  # 报告生成失败不影响档案本身
        import logging
        logging.getLogger(__name__).warning(f"failed to render blogger html report: {e}")
    return profile
