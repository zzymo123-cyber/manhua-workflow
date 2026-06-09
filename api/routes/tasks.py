import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path, PureWindowsPath

from api import pipeline as pl, vidu, wetoken
from api.routes.settings import get_api_key
from api.storyboard_versions import (
    StoryboardVersionError,
    get_storyboard_status,
    get_storyboard_target,
    set_storyboard_submitted,
    storyboard_image_path,
    storyboard_image_relative_path,
    storyboard_output_id,
    sync_legacy_v1_from_output,
)
from api.video_params import VideoParamError, normalize_video_duration, normalize_video_ratio

router = APIRouter()


class BatchSubmitItem(BaseModel):
    type: str
    mode: str = "v1"
    name: Optional[str] = None
    scene_key: Optional[str] = None
    page: Optional[int] = None
    output_id: Optional[str] = None
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: Optional[str] = None


class BatchSubmitRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    items: list[BatchSubmitItem]


class SubmitRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    mode: str = "v1"
    project_name: str = ""
    project_path: str = ""
    name: Optional[str] = None
    scene_key: Optional[str] = None
    page: Optional[int] = None
    output_id: Optional[str] = None
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: Optional[str] = None


def _get_project_dir(project_name: str = "", project_path: str = "") -> Path:
    project_dir = pl.resolve_project_dir(project_name, project_path)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    return project_dir


def _require_api_key(value: str, label: str) -> str:
    if not value:
        raise HTTPException(status_code=400, detail=f"缺少 {label} API Key，请先在设置中配置")
    return value


def _require_prompt(prompt: str) -> str:
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="提示词不能为空")
    return prompt


def _resolve_image_paths(project_dir: Path, image_paths: list[str]) -> list[str]:
    base = project_dir.resolve()
    resolved = []
    for original in image_paths:
        normalized = original.replace("\\", "/")
        requested = Path(normalized)
        if requested.is_absolute() or PureWindowsPath(original).is_absolute():
            raise HTTPException(status_code=403, detail=f"不允许访问项目目录外的参考图: {original}")
        full_path = (base / requested).resolve()
        try:
            full_path.relative_to(base)
        except ValueError:
            raise HTTPException(status_code=403, detail=f"不允许访问项目目录外的参考图: {original}")
        resolved.append(str(full_path))

    missing = [original for original, resolved_path in zip(image_paths, resolved) if not Path(resolved_path).exists()]
    if missing:
        preview = "、".join(missing[:5])
        suffix = f" 等 {len(missing)} 个文件" if len(missing) > 5 else ""
        raise HTTPException(status_code=400, detail=f"缺少参考图: {preview}{suffix}")
    return resolved


def _require_asset(data: dict, category: str, name: str | None, label: str) -> dict:
    if not name:
        raise HTTPException(status_code=400, detail=f"缺少{label}名称")
    item = data.get("assets", {}).get(category, {}).get(name)
    if item is None:
        raise HTTPException(status_code=400, detail=f"未找到{label}: {name}")
    return item


def _require_storyboard(data: dict, scene_key: str | None) -> dict:
    if not scene_key:
        raise HTTPException(status_code=400, detail="缺少故事板场景 key")
    board = data.get("storyboards", {}).get(scene_key)
    if board is None:
        raise HTTPException(status_code=400, detail=f"未找到故事板: {scene_key}")
    return board


def _require_video_part(part: int | None) -> int:
    if part is None:
        raise HTTPException(status_code=400, detail="缺少视频分段 part")
    return part


def _require_existing_video_part(board: dict, part: int) -> dict:
    for item in board.get("video_parts", []):
        if item.get("part") == part:
            return item
    raise HTTPException(status_code=400, detail=f"未找到视频分段 part {part}")


def _require_completed_storyboard(board: dict):
    if board.get("board_status") != "completed":
        raise HTTPException(status_code=400, detail="故事板尚未完成，无法提交视频")


def _require_completed_storyboard_target(
    board: dict,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
):
    try:
        status = get_storyboard_status(board, mode, page, output_id)
    except StoryboardVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if status != "completed":
        raise HTTPException(status_code=400, detail="故事板尚未完成，无法提交视频")


def _storyboard_target_or_400(
    board: dict,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
) -> dict:
    try:
        return get_storyboard_target(board, mode, page, output_id)
    except StoryboardVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _clear_fields(item: dict, fields: tuple[str, ...]):
    for field in fields:
        item.pop(field, None)


def _relative_path(project_dir: Path, path: Path) -> str:
    return str(path.relative_to(project_dir)).replace("\\", "/")


def _default_reference_path(project_dir: Path, category: str, name: str) -> Path:
    return project_dir / category / name / f"{name}.png"


def _asset_reference_path(project_dir: Path, data: dict, category: str, name: str, label: str) -> tuple[str | None, str | None]:
    info = data.get("assets", {}).get(category, {}).get(name)
    if not info or info.get("status") != "completed":
        return None, f"{label}「{name}」未完成"

    file_category = "characters" if category == "characters" else "scenes_props"
    path = pl.get_primary_image_path(project_dir, file_category, name) or _default_reference_path(project_dir, file_category, name)
    if not path.exists():
        return None, f"缺少参考图：{_relative_path(project_dir, path)}"
    return str(path), None


def _storyboard_reference_paths(project_dir: Path, data: dict, board: dict) -> tuple[list[str], list[str]]:
    paths = []
    issues = []
    for char in board.get("characters_in_scene", []):
        path, issue = _asset_reference_path(project_dir, data, "characters", char, "角色")
        if issue:
            issues.append(issue)
        elif path:
            paths.append(path)

    scene_name = board.get("scene_location")
    if scene_name:
        category = "scenes" if scene_name in data.get("assets", {}).get("scenes", {}) else "props"
        path, issue = _asset_reference_path(project_dir, data, category, scene_name, "场景/道具")
        if issue:
            issues.append(issue)
        elif path:
            paths.append(path)

    return paths, issues


def _video_reference_paths(project_dir: Path, data: dict, scene_key: str, board: dict,
                           mode: str = "v1", page: int | None = None) -> tuple[list[str], list[str]]:
    paths, issues = _storyboard_reference_paths(project_dir, data, board)
    board_path = storyboard_image_path(project_dir, scene_key, mode, page)
    if not board_path.exists():
        issues.append(f"缺少参考图：{_relative_path(project_dir, board_path)}")
    else:
        paths.append(str(board_path))
    return paths, issues


def _reference_issue_detail(issues: list[str]) -> str:
    preview = "，".join(issues[:3])
    suffix = f" 等 {len(issues)} 项" if len(issues) > 3 else ""
    return f"前置参考未完成：{preview}{suffix}"


def _merge_image_paths(existing: list[str], required: list[str]) -> list[str]:
    merged = []
    seen = set()
    for path in existing + required:
        if path not in seen:
            merged.append(path)
            seen.add(path)
    return merged


@router.post("/submit")
async def submit_task(req: SubmitRequest):
    import logging
    logger = logging.getLogger("manhua.submit")
    project_ref = req.project_path or req.project_name
    logger.info("submit_task: type=%s project=%s name=%s scene_key=%s part=%s",
                req.type, project_ref, req.name, req.scene_key, req.part)
    project_dir = _get_project_dir(req.project_name, req.project_path)
    data = pl.read_pipeline(project_dir)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    # 前端传来的 image_paths 是相对于项目目录的；缺失时直接返回可恢复错误。
    abs_image_paths = _resolve_image_paths(project_dir, req.image_paths)

    resp_task_id = ""
    resp_status = "submitted"

    if req.type == "character":
        asset = _require_asset(data, "characters", req.name, "角色")
        prompt = _require_prompt(req.prompt)
        vidu_key = _require_api_key(vidu_key, "Vidu")
        try:
            result = vidu.submit_image_task(vidu_key, prompt, abs_image_paths, ratio="3:4")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset["status"] = "submitted"
        asset["task_id"] = result["task_id"]
        _clear_fields(asset, ("error",))
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "scene":
        asset = _require_asset(data, "scenes", req.name, "场景")
        prompt = _require_prompt(req.prompt)
        vidu_key = _require_api_key(vidu_key, "Vidu")
        try:
            result = vidu.submit_image_task(vidu_key, prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset["status"] = "submitted"
        asset["task_id"] = result["task_id"]
        _clear_fields(asset, ("error",))
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "prop":
        asset = _require_asset(data, "props", req.name, "道具")
        prompt = _require_prompt(req.prompt)
        vidu_key = _require_api_key(vidu_key, "Vidu")
        try:
            result = vidu.submit_image_task(vidu_key, prompt, abs_image_paths, ratio="1:1")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset["status"] = "submitted"
        asset["task_id"] = result["task_id"]
        _clear_fields(asset, ("error",))
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "storyboard":
        board = _require_storyboard(data, req.scene_key)
        _storyboard_target_or_400(board, req.mode, req.page, req.output_id)
        prompt = _require_prompt(req.prompt)
        vidu_key = _require_api_key(vidu_key, "Vidu")
        reference_paths, reference_issues = _storyboard_reference_paths(project_dir, data, board)
        if reference_issues:
            raise HTTPException(status_code=400, detail=_reference_issue_detail(reference_issues))
        image_paths = _merge_image_paths(abs_image_paths, reference_paths)
        try:
            result = vidu.submit_image_task(vidu_key, prompt, image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        set_storyboard_submitted(board, result["task_id"], req.mode, req.page, req.output_id)
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "video":
        board = _require_storyboard(data, req.scene_key)
        part = _require_video_part(req.part)
        _require_completed_storyboard_target(board, req.mode, req.page, req.output_id)
        board_target = _storyboard_target_or_400(board, req.mode, req.page, req.output_id)
        part_info = _require_existing_video_part(board_target, part)
        prompt = _require_prompt(req.prompt)
        wetoken_key = _require_api_key(wetoken_key, "Wetoken")
        duration_value = req.duration if req.duration is not None else board_target.get("video_duration", board.get("video_duration"))
        ratio_value = req.ratio if req.ratio is not None else board_target.get("video_ratio", board.get("video_ratio"))
        try:
            duration = normalize_video_duration(duration_value, default=10)
            ratio = normalize_video_ratio(ratio_value, default="16:9")
        except VideoParamError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        source_page = req.page or board_target.get("page", 1)
        reference_paths, reference_issues = _video_reference_paths(project_dir, data, req.scene_key, board, req.mode, source_page)
        if reference_issues:
            raise HTTPException(status_code=400, detail=_reference_issue_detail(reference_issues))
        image_paths = _merge_image_paths(abs_image_paths, reference_paths)
        try:
            task_id = wetoken.submit_video_task(
                wetoken_key, prompt, image_paths,
                duration=duration, ratio=ratio, project_dir=project_dir,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Wetoken API 错误: {e}")
        part_info["video_status"] = "submitted"
        part_info["video_task_id"] = task_id
        part_info["storyboard_mode"] = req.mode
        part_info["storyboard_output_id"] = storyboard_output_id(req.mode, req.page, req.output_id)
        part_info["storyboard_page"] = source_page
        part_info["source_image"] = storyboard_image_relative_path(req.scene_key or "", req.mode, source_page)
        _clear_fields(part_info, ("video_error", "video_download_error", "video_url", "local_path"))
        if req.mode == "v1":
            sync_legacy_v1_from_output(board)
        resp_task_id = task_id

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")

    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"task_id": resp_task_id, "status": resp_status}



@router.post("/batch-submit")
async def batch_submit_tasks(req: BatchSubmitRequest):
    """批量提交任务，逐个处理，返回每项结果"""
    _get_project_dir(req.project_name, req.project_path)
    results = []
    for item in req.items:
        try:
            single_req = SubmitRequest(
                type=item.type, mode=item.mode, project_name=req.project_name, project_path=req.project_path,
                name=item.name, scene_key=item.scene_key, page=item.page, output_id=item.output_id, part=item.part,
                prompt=item.prompt, image_paths=item.image_paths,
                duration=item.duration, ratio=item.ratio,
            )
            result = await submit_task(single_req)
            results.append({"name": item.name or item.scene_key or "", "ok": True, "task_id": result["task_id"]})
        except HTTPException as e:
            results.append({"name": item.name or item.scene_key or "", "ok": False, "error": e.detail})
        except Exception as e:
            results.append({"name": item.name or item.scene_key or "", "ok": False, "error": str(e)})
    return {"results": results}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, req: SubmitRequest):
    """重试失败任务：重新提交，返回新 task_id"""
    return await submit_task(req)
