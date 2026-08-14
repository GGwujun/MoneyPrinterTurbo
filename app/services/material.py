import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()

# 素材下载并发执行器。search 阶段对 provider 有限流，保持串行；下载阶段
# (save_video) 是 IO 密集型且素材 CDN 一般不限流，因此用线程池并发以显著
# 缩短素材准备耗时。worker 数量可经 config.app.material_download_workers 配置。
# 参见 task.py 的 cross-post 线程池风格：模块级单例 + thread_name_prefix。
_download_executor_lock = threading.Lock()
_download_executor = None

# save_video 以 URL 的 md5 作为文件名，同一 URL 会写同一文件。跨任务共享
# material_directory 时，不同线程对同一热门素材并发下载会互相截断。这里用
# per-path 锁兜底，保证同一文件路径的写入串行；不同路径仍可并发。
_save_video_locks = {}
_save_video_locks_guard = threading.Lock()


def _get_download_executor() -> ThreadPoolExecutor:
    """惰性创建下载线程池，worker 数量从配置读取并做范围校验。"""
    global _download_executor
    if _download_executor is not None:
        return _download_executor
    with _download_executor_lock:
        if _download_executor is None:
            try:
                workers = int(config.app.get("material_download_workers", 4))
            except (TypeError, ValueError):
                workers = 4
            # 并发过高会同时拉起多个 ffmpeg 校验进程并放大内存占用
            # (save_video 把整个 mp4 读进内存)，限制在合理区间。
            workers = max(1, min(workers, 8))
            _download_executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="mpt-material-dl",
            )
        return _download_executor


def _get_save_video_lock(video_path: str) -> threading.Lock:
    with _save_video_locks_guard:
        lock = _save_video_locks.get(video_path)
        if lock is None:
            lock = threading.Lock()
            _save_video_locks[video_path] = lock
        return lock


def _download_material_worker(item, save_dir: str) -> str:
    """单个素材下载的线程入口，带异常隔离。per-path 写入锁在 save_video 内部。"""
    try:
        logger.info(f"downloading video: {item.url}")
        saved = save_video(video_url=item.url, save_dir=save_dir)
        if saved:
            logger.info(f"video saved: {saved}")
        return saved
    except Exception as e:
        logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
        return ""


def _download_items_concurrently(items: List[MaterialInfo], save_dir: str) -> List[str]:
    """并发下载一批候选素材，返回与传入 items 顺序一一对应的结果列表
    （成功为路径字符串，失败为空字符串）。结果顺序由提交顺序决定，不随完成
    先后变化——下游 sequential 拼接依赖稳定顺序。"""
    executor = _get_download_executor()
    futures = [
        executor.submit(_download_material_worker, item, save_dir) for item in items
    ]
    return [future.result() for future in futures]


def _download_worker_count() -> int:
    """返回下载线程池的 worker 数，用于决定分批大小。"""
    try:
        return _get_download_executor()._max_workers  # noqa: SLF001
    except Exception:
        return 4



def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(
        f"searching videos on pixabay: term={search_term!r}, "
        f"with proxies: {config.proxy}"
    )

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_coverr(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Coverr (https://coverr.co) - free HD/4K stock videos,
    subject to Coverr license terms (https://coverr.co/license).

    Coverr API notes (based on official docs at api.coverr.co/docs/):
      - 鉴权: Authorization: Bearer <api_key>
      - 搜索端点: GET /videos?query=...,响应结构 {"hits": [...], ...}
      - 加 ?urls=true 在搜索响应里直接返回 mp4 直链
      - URL 是 signed JWT(绑定 API key,无过期时间)
      - Coverr 库以 16:9 横屏为主,9:16 portrait 占比极低(约 1%)
        因此本函数不做 aspect_ratio 过滤,由下游 video.py 的
        resize + letterbox 逻辑统一处理
      - duration 字段同时存在 number 和 string 两种形态,本函数都接受

    本函数使用 urls.mp4_download 字段作为下载地址 —— 按 Coverr 官方文档
    (https://api.coverr.co/docs/videos/#download-a-video) 的说法,
    GET 这个 URL 本身就被 Coverr 当作一次合法的 download 事件计入统计,
    无需再调用 PATCH /videos/:id/stats/downloads。
    """
    api_key = get_api_key("coverr_api_keys")
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": search_term,
        "page_size": 20,
        "urls": "true",
        "sort": "popular",
    }
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items: List[MaterialInfo] = []

        if not isinstance(response, dict) or "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items

        for v in response["hits"]:
            # duration 在不同响应里可能是 number(11.625) 或 string("10.500000")
            try:
                duration = int(float(v.get("duration") or 0))
            except (TypeError, ValueError):
                continue
            if duration < minimum_duration:
                continue

            video_id = v.get("id")
            mp4_download_url = (v.get("urls") or {}).get("mp4_download")
            if not video_id or not mp4_download_url:
                continue

            item = MaterialInfo()
            item.provider = "coverr"
            item.url = mp4_download_url
            item.duration = duration
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # 同一 URL 必然映射到同一文件路径。并发下载时，多个线程同时 open(...,"wb")
    # 会互相截断导致文件损坏。这里用 per-path 锁串行化写入；不同路径之间仍并发。
    with _get_save_video_lock(video_path):
        # if video already exists, return the path
        if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            logger.info(f"video already exists: {video_path}")
            return video_path

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }

        # if video does not exist, download it
        with open(video_path, "wb") as f:
            f.write(
                requests.get(
                    video_url,
                    headers=headers,
                    proxies=config.proxy,
                    verify=_get_tls_verify(),
                    timeout=(60, 240),
                ).content
            )

        if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            clip = None
            try:
                clip = VideoFileClip(video_path)
                duration = clip.duration
                fps = clip.fps
                if duration > 0 and fps > 0:
                    return video_path
            except Exception as e:
                logger.warning(f"invalid video file: {video_path} => {str(e)}")
                try:
                    os.remove(video_path)
                except Exception as remove_error:
                    logger.warning(
                        f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                    )
            finally:
                if clip is not None:
                    try:
                        clip.close()
                    except Exception as close_error:
                        logger.warning(
                            f"failed to close video clip: {video_path}, error: {str(close_error)}"
                        )
    return ""


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    match_script_order: bool = False,
) -> List[str]:
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay
    elif source == "coverr":
        search_videos = search_videos_coverr

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            search_videos=search_videos,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    # 按线程池 worker 数分批并发下载。每批下完后累加时长，达到音频时长预算
    # 即停止提交后续批次，保留原"凑够即停"语义。批内并发结果按提交顺序回填，
    # 保证 random 模式 shuffle 后的顺序即为成片顺序。最后一批可能因并发多下
    # 若干素材——这些素材会进入本地缓存供后续复用，不算真正浪费。
    try:
        workers = _download_worker_count()
    except Exception:
        workers = 4
    batch_size = max(1, workers)

    total_duration = 0.0
    stop = False
    for start in range(0, len(valid_video_items), batch_size):
        if stop:
            break
        batch = valid_video_items[start : start + batch_size]
        saved_paths = _download_items_concurrently(batch, material_directory)
        for item, saved_video_path in zip(batch, saved_paths):
            if saved_video_path:
                video_paths.append(saved_video_path)
                total_duration += min(max_clip_duration, item.duration)
        if total_duration > audio_duration:
            logger.info(
                f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
            )
            stop = True
    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    search_videos,
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    按脚本文案顺序下载素材。

    默认下载逻辑会把所有关键词的候选素材合并成一个大列表；如果第一个
    关键词返回很多结果，最终下载时可能一直消耗这个关键词的素材，后续
    脚本主题就排不上时间线。这里按关键词分组后轮询下载：
    第 1 轮取每个关键词的第 1 个候选，第 2 轮取每个关键词的第 2 个候选。
    这样在不重写视频合成引擎的前提下，尽量保证素材顺序贴近文案顺序。
    """
    logger.info("downloading videos with script-order material matching")
    candidate_groups = []
    valid_video_urls = set()
    found_duration = 0.0

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        term_items = []
        for item in video_items:
            if item.url in valid_video_urls:
                continue
            term_items.append(item)
            valid_video_urls.add(item.url)
            found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths = []
    total_duration = 0.0
    candidate_index = 0
    # script-order 模式对"逐个累加、达预算即停"的语义高度敏感：并发会把整轮
    # 候选都下完才检查时长，导致多下载。该路径追求顺序准确性而非吞吐，因此
    # 保持逐个串行下载；普通模式才走并发批量下载。per-path 锁仍生效，确保
    # save_video 可被任一线程安全调用。
    while candidate_groups and total_duration <= audio_duration:
        has_candidate = False
        for search_term, term_items in candidate_groups:
            if candidate_index >= len(term_items):
                continue

            has_candidate = True
            item = term_items[candidate_index]
            try:
                logger.info(
                    f"downloading ordered video for '{search_term}': {item.url}"
                )
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    total_duration += min(max_clip_duration, item.duration)
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    f"failed to download ordered video: {utils.to_json(item)} => {str(e)}"
                )

        if not has_candidate:
            break
        candidate_index += 1

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
