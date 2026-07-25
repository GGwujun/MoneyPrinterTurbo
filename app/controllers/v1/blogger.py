"""博主蒸馏 REST 控制器。

仿 controllers/v1/llm.py 的模式 (new_router + utils.get_response)。Phase 1 的
distill 是同步长任务 (爬虫 + 分析 + 多次 LLM 调用, 约数分钟), FastAPI 会把它
丢到线程池执行不会阻塞事件循环; WebUI 则直接通过 from app.services import
blogger 调用, 不走 HTTP。
"""
from fastapi import Request

from app.controllers.v1.base import new_router
from app.models.schema import (
    BaseResponse,
    BloggerBatchRequest,
    BloggerDistillRequest,
    BloggerTopicsRequest,
)
from app.services import blogger as blogger_service
from app.utils import utils

router = new_router()


@router.post(
    "/bloggers/distill",
    response_model=BaseResponse,
    summary="Distill a blogger into a reusable style profile",
)
def distill_blogger(request: Request, body: BloggerDistillRequest):
    profile = blogger_service.run_distillation(
        nickname=body.nickname,
        platform=body.platform,
        max_notes=body.max_notes,
        transcript=body.transcript,
    )
    return utils.get_response(200, profile)


@router.get(
    "/bloggers",
    response_model=BaseResponse,
    summary="List all distilled blogger profiles",
)
def list_bloggers(request: Request):
    return utils.get_response(200, blogger_service.profiles.list_profiles())


@router.get(
    "/bloggers/{profile_id}",
    response_model=BaseResponse,
    summary="Get a blogger profile by id",
)
def get_blogger(request: Request, profile_id: str):
    profile = blogger_service.profiles.get_profile(profile_id)
    if not profile:
        return utils.get_response(404, message="blogger profile not found")
    return utils.get_response(200, profile)


@router.delete(
    "/bloggers/{profile_id}",
    response_model=BaseResponse,
    summary="Delete a blogger profile",
)
def delete_blogger(request: Request, profile_id: str):
    ok = blogger_service.profiles.delete_profile(profile_id)
    if not ok:
        return utils.get_response(404, message="blogger profile not found")
    return utils.get_response(200, {"deleted": profile_id})


@router.post(
    "/bloggers/topics",
    response_model=BaseResponse,
    summary="Suggest new topics in a blogger's style",
)
def suggest_blogger_topics(request: Request, body: BloggerTopicsRequest):
    style = blogger_service.profiles.get_style(body.profile_id)
    if not style:
        return utils.get_response(404, message="blogger profile not found")
    topics = blogger_service.topics.suggest_topics(
        style, count=body.count, focus=body.focus
    )
    return utils.get_response(200, topics)


@router.post(
    "/bloggers/batches",
    response_model=BaseResponse,
    summary="Batch-create video tasks from topics in a blogger's style",
)
def create_blogger_batch(request: Request, body: BloggerBatchRequest):
    result = blogger_service.batch.create_batch(
        profile_id=body.profile_id,
        topics=body.topics,
        params_template=body.params,
        stop_at=body.stop_at,
    )
    return utils.get_response(200, result)
