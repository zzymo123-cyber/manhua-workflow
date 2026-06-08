import asyncio
import os
import datetime
from pathlib import Path

from api import pipeline as pl
from api import vidu, wetoken
from api.routes.settings import get_api_key

_poll_task: asyncio.Task | None = None
_running = False


async def start():
    """App 启动时调用，开始后台轮询"""
    global _poll_task, _running
    _running = True
    _poll_task = asyncio.create_task(_poll_loop())


async def stop():
    global _running, _poll_task
    _running = False
    if _poll_task:
        _poll_task.cancel()


async def _poll_loop():
    while _running:
        try:
            await _scan_all_projects()
        except Exception:
            pass  # 轮询不崩 App
        await asyncio.sleep(10)


async def _scan_all_projects():
    """扫描所有已知项目（vidu_studio 目录 + settings 里的 recent_projects）"""
    from api.routes.settings import read_settings
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    project_dirs = set()

    # 默认目录
    root = Path.home() / "Desktop" / "vidu_studio"
    if root.exists():
        for d in root.iterdir():
            if (d / "pipeline.json").exists():
                project_dirs.add(d)

    # settings 里的 recent_projects
    try:
        settings = read_settings()
        for entry in settings.get("recent_projects", []):
            p = Path(entry.get("path", ""))
            if (p / "pipeline.json").exists():
                project_dirs.add(p)
    except Exception:
        pass

    for project_dir in project_dirs:
        await _process_submitted_tasks(project_dir, vidu_key, wetoken_key)


async def _process_submitted_tasks(project_dir: Path, vidu_key: str, wetoken_key: str):
    """处理一个项目里所有 submitted 状态的任务"""
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return

    changed = False

    # 角色（Vidu 图片任务）
    for name, info in data.get("assets", {}).get("characters", {}).items():
        if info.get("status") == "submitted" and info.get("task_id"):
            result = vidu.poll_task(vidu_key, info["task_id"])
            if result["status"] == "success":
                _download_and_update_asset(
                    project_dir, "characters", name, info["task_id"], result["image_url"]
                )
                info["status"] = "completed"
                changed = True
            elif result["status"] == "failed":
                info["status"] = "failed"
                info["error"] = result["error"]
                changed = True

    # 场景（scenes_props 目录下）
    for name, info in data.get("assets", {}).get("scenes", {}).items():
        if info.get("status") == "submitted" and info.get("task_id"):
            result = vidu.poll_task(vidu_key, info["task_id"])
            if result["status"] == "success":
                _download_and_update_asset(project_dir, "scenes_props", name, info["task_id"], result["image_url"])
                info["status"] = "completed"
                changed = True
            elif result["status"] == "failed":
                info["status"] = "failed"
                info["error"] = result["error"]
                changed = True

    # 道具
    for name, info in data.get("assets", {}).get("props", {}).items():
        if info.get("status") == "submitted" and info.get("task_id"):
            result = vidu.poll_task(vidu_key, info["task_id"])
            if result["status"] == "success":
                _download_and_update_asset(project_dir, "scenes_props", name, info["task_id"], result["image_url"])
                info["status"] = "completed"
                changed = True
            elif result["status"] == "failed":
                info["status"] = "failed"
                changed = True

    # 故事板（Vidu 图片任务）
    for scene_key, board in data.get("storyboards", {}).items():
        if board.get("board_status") == "submitted" and board.get("board_task_id"):
            result = vidu.poll_task(vidu_key, board["board_task_id"])
            if result["status"] == "success":
                _download_and_update_storyboard(project_dir, scene_key, board, result["image_url"])
                board["board_status"] = "completed"
                changed = True
            elif result["status"] == "failed":
                board["board_status"] = "failed"
                board["board_error"] = result["error"]
                changed = True

    # 视频分段（Wetoken 任务）
    for scene_key, board in data.get("storyboards", {}).items():
        for part_info in board.get("video_parts", []):
            if part_info.get("video_status") == "submitted" and part_info.get("video_task_id"):
                result = wetoken.poll_task(wetoken_key, part_info["video_task_id"])
                if result["status"] == "completed":
                    part_info["video_status"] = "completed"
                    part_info["video_url"] = result["video_url"]
                    # 下载视频到本地（Wetoken URL 24h 过期）
                    if result["video_url"]:
                        video_dir = project_dir / "videos" / scene_key
                        video_dir.mkdir(parents=True, exist_ok=True)
                        part_num = part_info.get("part", 0)
                        local_path = video_dir / f"part{part_num}.mp4"
                        if not local_path.exists():
                            try:
                                wetoken.download_video(result["video_url"], local_path)
                            except Exception:
                                pass
                        if local_path.exists():
                            part_info["local_path"] = str(local_path.relative_to(project_dir))
                    changed = True
                elif result["status"] == "failed":
                    part_info["video_status"] = "failed"
                    part_info["video_error"] = result["error"]
                    changed = True

    if changed:
        data["updated_at"] = datetime.datetime.now().isoformat()
        pl.write_pipeline(project_dir, data)


def _download_and_update_asset(project_dir: Path, category: str, name: str, task_id: str, image_url: str):
    """下载图片并更新 meta.json 的 primary_image"""
    asset_dir = project_dir / category / name
    filename = f"{name}.png"
    dest = asset_dir / filename
    if not dest.exists():
        vidu.download_image(image_url, dest)
    meta = pl.get_meta(project_dir, category, name) or {
        "name": name, "category": category,
        "primary_image": filename, "versions": [], "created_at": datetime.datetime.now().isoformat()
    }
    if not meta.get("primary_image"):
        meta["primary_image"] = filename
    meta["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_meta(project_dir, category, name, meta)


def _download_and_update_storyboard(project_dir: Path, scene_key: str, board: dict, image_url: str):
    """下载故事板图片"""
    board_dir = project_dir / "storyboards" / scene_key
    filename = f"{scene_key}.png"
    dest = board_dir / filename
    if not dest.exists():
        vidu.download_image(image_url, dest)
