import asyncio
import datetime
import logging
from pathlib import Path

from api import pipeline as pl
from api import vidu, wetoken
from api.routes.settings import get_api_key

logger = logging.getLogger(__name__)

_POLL_SUBMIT_TIMEOUT_MINUTES = 30

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
    await vidu.close_async_client()
    await wetoken.close_async_client()


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


# ── 通用轮询处理 ──


async def _poll_vidu_item(item: dict, vidu_key: str, now: datetime.datetime,
                           updated_at: str | None, task_id_field: str = "task_id") -> dict | None:
    """轮询一个 Vidu submitted 任务，返回结果 dict 或 None（未变化）。
    task_id_field: 资产用 "task_id"，故事板版本用 "board_task_id"。"""
    if item.get("status") != "submitted" or not item.get(task_id_field):
        return None
    if _is_timeout(updated_at, now):
        item["status"] = "failed"
        item["error"] = "超时"
        return {"status": "failed"}
    result = await vidu.poll_task_async(vidu_key, item[task_id_field])
    if result["status"] == "success":
        item["status"] = "completed"
        return {"status": "success", "image_url": result["image_url"]}
    elif result["status"] == "failed":
        item["status"] = "failed"
        item["error"] = result["error"]
        return {"status": "failed"}
    return None  # pending


async def _poll_wetoken_item(item: dict, wetoken_key: str, now: datetime.datetime,
                              updated_at: str | None, project_dir: Path, scene_key: str) -> dict | None:
    """轮询一个 Wetoken submitted 视频任务，返回结果 dict 或 None。"""
    if item.get("video_status") != "submitted" or not item.get("video_task_id"):
        return None
    if _is_timeout(updated_at, now):
        item["video_status"] = "failed"
        item["error"] = "超时"
        return {"status": "failed"}
    result = await wetoken.poll_task_async(wetoken_key, item["video_task_id"])
    if result["status"] == "completed":
        item["video_status"] = "completed"
        item["video_url"] = result["video_url"]
        if result["video_url"]:
            video_dir = project_dir / "videos" / scene_key
            video_dir.mkdir(parents=True, exist_ok=True)
            part_num = item.get("part", 0)
            local_path = video_dir / f"part{part_num}.mp4"
            if not local_path.exists():
                try:
                    await wetoken.download_video_async(result["video_url"], local_path)
                except Exception:
                    pass
            if local_path.exists():
                item["local_path"] = str(local_path.relative_to(project_dir))
        return {"status": "completed"}
    elif result["status"] == "failed":
        item["video_status"] = "failed"
        item["error"] = result["error"]
        return {"status": "failed"}
    return None


# ── 主处理函数 ──


async def _process_submitted_tasks(project_dir: Path, vidu_key: str, wetoken_key: str):
    """处理一个项目里所有 submitted 状态的任务"""
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return

    changed = False
    now = datetime.datetime.now()
    updated_at = data.get("updated_at")

    # 资产（角色/场景/道具）— 扁平字段
    asset_categories = [
        ("characters", "characters"),
        ("scenes", "scenes_props"),
        ("props", "scenes_props"),
    ]
    for cat_key, dir_name in asset_categories:
        for name, asset in data.get("assets", {}).get(cat_key, {}).items():
            result = await _poll_vidu_item(asset, vidu_key, now, updated_at)
            if result:
                if result["status"] == "success":
                    await _download_and_update_asset_async(
                        project_dir, dir_name, name, result["image_url"]
                    )
                    asset["result_url"] = str(Path(dir_name) / name / f"{name}.png")
                changed = True

    # 故事板版本 + 视频分段 — board_versions 模型
    for scene_key, board in data.get("storyboards", {}).items():
        for bv in board.get("board_versions", []):
            # 故事板图片（board_task_id 字段名）
            result = await _poll_vidu_item(bv, vidu_key, now, updated_at, task_id_field="board_task_id")
            if result:
                if result["status"] == "success":
                    await _download_and_update_storyboard_async(
                        project_dir, scene_key, result["image_url"]
                    )
                changed = True

            # 视频分段
            for vp in bv.get("video_parts", []):
                result = await _poll_wetoken_item(
                    vp, wetoken_key, now, updated_at, project_dir, scene_key
                )
                if result:
                    changed = True

    if changed:
        data["updated_at"] = now.isoformat()
        pl.write_pipeline(project_dir, data)


def _is_timeout(updated_at: str | None, now: datetime.datetime) -> bool:
    """检查 submitted 状态是否超时"""
    if not updated_at:
        return False
    try:
        updated_time = datetime.datetime.fromisoformat(updated_at)
        if (now - updated_time).total_seconds() > _POLL_SUBMIT_TIMEOUT_MINUTES * 60:
            return True
    except Exception:
        pass
    return False


async def _download_and_update_asset_async(project_dir: Path, category: str, name: str, image_url: str):
    """下载图片并更新 meta.json"""
    asset_dir = project_dir / category / name
    filename = f"{name}.png"
    dest = asset_dir / filename
    if not dest.exists():
        try:
            await vidu.download_image_async(image_url, dest)
        except Exception:
            pass
    meta = pl.get_meta(project_dir, category, name) or {
        "name": name, "category": category,
        "primary_image": filename, "versions": [], "created_at": datetime.datetime.now().isoformat()
    }
    if not meta.get("primary_image"):
        meta["primary_image"] = filename
    meta["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_meta(project_dir, category, name, meta)


async def _download_and_update_storyboard_async(project_dir: Path, scene_key: str, image_url: str):
    """下载故事板图片"""
    board_dir = project_dir / "storyboards" / scene_key
    filename = f"{scene_key}.png"
    dest = board_dir / filename
    if not dest.exists():
        try:
            await vidu.download_image_async(image_url, dest)
        except Exception:
            pass
