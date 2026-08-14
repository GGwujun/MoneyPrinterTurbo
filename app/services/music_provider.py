"""视频配乐（video music）供应商注册表。

从 app/services/task.py 抽出。供应商差异集中在文件扩展名、领域异常和 WebUI
警告代码；任务编排、0 音量短路及失败降级全部复用 task.generate_final_videos
里的同一路径，避免后续新增供应商时维护多份相似流程。
"""
from app.models.schema import VideoParams
from app.services import elevenlabs_music, sonilo

# 视频配乐服务只需实现 ``is_enabled`` 和 ``generate_bgm``。
_VIDEO_MUSIC_PROVIDERS = {
    "sonilo": {
        "service": sonilo,
        "error_type": sonilo.SoniloError,
        "suffix": ".m4a",
        "warning_code": "sonilo_bgm_failed",
        "display_name": "Sonilo",
    },
    "elevenlabs": {
        "service": elevenlabs_music,
        "error_type": elevenlabs_music.ElevenLabsMusicError,
        "suffix": ".mp3",
        "warning_code": "elevenlabs_bgm_failed",
        "display_name": "ElevenLabs",
    },
}


def _get_video_music_prompt(params: VideoParams) -> str:
    """
    读取当前视频配乐供应商实际使用的提示词。

    新任务统一使用供应商无关字段；旧 Sonilo CLI 参数和历史任务仍可能只有
    ``sonilo_bgm_prompt``，因此仅在 Sonilo 通用字段为空时读取旧字段。
    """
    prompt = str(params.video_music_prompt or "").strip()
    if params.bgm_type == "sonilo" and not prompt:
        prompt = str(params.sonilo_bgm_prompt or "").strip()
    return prompt
