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
    submitted_at = item.get("submitted_at") or updated_at
    if not item.get("submitted_at") and submitted_at:
        item["submitted_at"] = submitted_at
    item["last_checked_at"] = now.isoformat()
    if _is_timeout(submitted_at, now):
        item["status"] = "failed"
        item["error"] = "超时"
        item["status_message"] = "生成超时，建议重试"
        return {"status": "failed"}
    try:
        result = await vidu.poll_task_async(vidu_key, item[task_id_field])
    except Exception as e:
        item["status_message"] = f"查询失败，稍后自动重试: {e}"
        return {"status": "pending"}
    if result["status"] == "success":
        item["status_message"] = "生成完成，正在下载本地文件"
        return {"status": "success", "image_url": result["image_url"]}
    elif result["status"] == "failed":
        item["status"] = "failed"
        item["error"] = result["error"]
        item["status_message"] = f"生成失败: {result['error']}"
        return {"status": "failed"}
    item["status_message"] = "服务端处理中，等待生成结果"
    return {"status": "pending"}


async def _poll_wetoken_item(item: dict, wetoken_key: str, now: datetime.datetime,
                              updated_at: str | None, project_dir: Path, scene_key: str,
                              board_version: str | None = None, board_id: str | None = None) -> dict | None:
    """轮询一个 Wetoken submitted 视频任务，返回结果 dict 或 None。"""
    if item.get("video_status") != "submitted" or not item.get("video_task_id"):
        return None
    submitted_at = item.get("submitted_at") or updated_at
    if not item.get("submitted_at") and submitted_at:
        item["submitted_at"] = submitted_at
    item["last_checked_at"] = now.isoformat()
    if _is_timeout(submitted_at, now):
        item["video_status"] = "failed"
        item["error"] = "超时"
        item["status_message"] = "生成超时，建议重试"
        return {"status": "failed"}
    try:
        result = await wetoken.poll_task_async(wetoken_key, item["video_task_id"])
    except Exception as e:
        item["status_message"] = f"查询失败，稍后自动重试: {e}"
        return {"status": "pending"}
    if result["status"] == "completed":
        item["video_status"] = "completed"
        item["video_url"] = result["video_url"]
        item["completed_at"] = now.isoformat()
        item["status_message"] = "生成完成"
        if result["video_url"]:
            if board_version and board_id:
                video_dir = project_dir / "videos" / board_version / scene_key / board_id
            elif board_version:
                video_dir = project_dir / "videos" / board_version / scene_key
            else:
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
        item["status_message"] = f"生成失败: {result['error']}"
        return {"status": "failed"}
    item["status_message"] = "服务端处理中，等待生成结果"
    return {"status": "pending"}


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
            if _restore_missing_completed_file(asset, project_dir, dir_name, name, now):
                changed = True
            result = await _poll_vidu_item(asset, vidu_key, now, updated_at)
            if result:
                    if result["status"] == "success":
                        local_path = str(Path(dir_name) / name / f"{name}.png")
                        ok = await _download_and_update_asset_async(
                            project_dir, dir_name, name, result["image_url"]
                        )
                        _mark_download_result(asset, ok, local_path, now)
                    changed = True

    storyboards = data.get("storyboards", {})
    if _uses_versioned_storyboards(storyboards):
        for board_version, scenes in storyboards.items():
            if not isinstance(scenes, dict):
                continue
            for scene_key, scene in scenes.items():
                if not isinstance(scene, dict):
                    continue
                boards = scene.get("boards")
                if isinstance(boards, list) and boards:
                    for board in boards:
                        board_id = board.get("board_id") or scene_key
                        result = await _poll_vidu_item(board, vidu_key, now, updated_at, task_id_field="board_task_id")
                        if result:
                            if result["status"] == "success":
                                local_path = str(Path("storyboards") / board_version / scene_key / f"{board_id}.png")
                                ok = await _download_and_update_storyboard_async(
                                    project_dir, scene_key, result["image_url"], board_version, board_id
                                )
                                _mark_download_result(board, ok, local_path, now)
                            _sync_scene_from_first_board(scene)
                            changed = True

                        for vp in board.get("video_parts", []):
                            result = await _poll_wetoken_item(
                                vp, wetoken_key, now, updated_at, project_dir, scene_key, board_version, board_id
                            )
                            if result:
                                _sync_scene_from_first_board(scene)
                                changed = True
                    continue

                result = await _poll_vidu_item(scene, vidu_key, now, updated_at, task_id_field="board_task_id")
                if result:
                    if result["status"] == "success":
                        local_path = str(Path("storyboards") / board_version / scene_key / f"{scene_key}.png")
                        ok = await _download_and_update_storyboard_async(
                            project_dir, scene_key, result["image_url"], board_version
                        )
                        _mark_download_result(scene, ok, local_path, now)
                    changed = True

                for vp in scene.get("video_parts", []):
                    result = await _poll_wetoken_item(
                        vp, wetoken_key, now, updated_at, project_dir, scene_key, board_version
                    )
                    if result:
                        changed = True
    else:
        # 旧结构兼容：storyboards[scene_key].board_versions[]
        for scene_key, board in storyboards.items():
            if not isinstance(board, dict):
                continue
            for bv in board.get("board_versions", []):
                result = await _poll_vidu_item(bv, vidu_key, now, updated_at, task_id_field="board_task_id")
                if result:
                    if result["status"] == "success":
                        local_path = str(Path("storyboards") / scene_key / f"{scene_key}.png")
                        ok = await _download_and_update_storyboard_async(
                            project_dir, scene_key, result["image_url"]
                        )
                        _mark_download_result(bv, ok, local_path, now)
                    changed = True

                for vp in bv.get("video_parts", []):
                    result = await _poll_wetoken_item(
                        vp, wetoken_key, now, updated_at, project_dir, scene_key
                    )
                    if result:
                        changed = True

    if changed:
        data["updated_at"] = now.isoformat()
        pl.write_pipeline(project_dir, data)


def _uses_versioned_storyboards(storyboards: dict) -> bool:
    for value in storyboards.values():
        if isinstance(value, dict) and any(k in value for k in ("episode", "board_versions", "script_title")):
            return False
    return bool(storyboards)


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


def _expected_asset_file_exists(project_dir: Path, category: str, name: str) -> bool:
    return (project_dir / category / name / f"{name}.png").exists()


def _restore_missing_completed_file(item: dict, project_dir: Path, category: str, name: str,
                                    now: datetime.datetime) -> bool:
    if item.get("status") != "completed" or _expected_asset_file_exists(project_dir, category, name):
        return False
    if not item.get("task_id"):
        item["status"] = "failed"
        item["error"] = "本地图片文件缺失"
        item["status_message"] = "生成记录完成，但本地图片文件不存在"
        return True
    item["status"] = "submitted"
    item["submitted_at"] = now.isoformat()
    item["status_message"] = "本地图片缺失，正在重新拉取生成结果"
    item.pop("error", None)
    return True


def _mark_download_result(item: dict, ok: bool, local_path: str, now: datetime.datetime) -> None:
    if ok:
        item["status"] = "completed"
        item["result_url"] = local_path
        item["completed_at"] = now.isoformat()
        item["status_message"] = "生成完成"
        item.pop("error", None)
        return
    item["status"] = "submitted"
    item["status_message"] = "生成完成，下载本地文件失败，稍后自动重试"
    item["error"] = "本地图片下载失败"


async def _download_and_update_asset_async(project_dir: Path, category: str, name: str, image_url: str) -> bool:
    """下载图片并更新 meta.json"""
    asset_dir = project_dir / category / name
    filename = f"{name}.png"
    dest = asset_dir / filename
    if not dest.exists():
        try:
            await vidu.download_image_async(image_url, dest)
        except Exception:
            return False
    if not dest.exists():
        return False
    meta = pl.get_meta(project_dir, category, name) or {
        "name": name, "category": category,
        "primary_image": filename, "versions": [], "created_at": datetime.datetime.now().isoformat()
    }
    if not meta.get("primary_image"):
        meta["primary_image"] = filename
    meta["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_meta(project_dir, category, name, meta)
    return True


async def _download_and_update_storyboard_async(project_dir: Path, scene_key: str, image_url: str,
                                                board_version: str | None = None,
                                                board_id: str | None = None) -> bool:
    """下载故事板图片"""
    board_dir = project_dir / "storyboards" / board_version / scene_key if board_version else project_dir / "storyboards" / scene_key
    filename = f"{board_id or scene_key}.png"
    dest = board_dir / filename
    if not dest.exists():
        try:
            await vidu.download_image_async(image_url, dest)
        except Exception:
            return False
    return dest.exists()


def _sync_scene_from_first_board(scene: dict) -> None:
    boards = scene.get("boards")
    if not isinstance(boards, list) or not boards:
        return
    first = boards[0]
    scene["draft_prompt"] = first.get("draft_prompt", "")
    scene["status"] = first.get("status", "needed")
    scene["board_task_id"] = first.get("board_task_id")
    scene["video_parts"] = first.get("video_parts", [])
