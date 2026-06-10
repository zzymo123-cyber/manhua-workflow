import datetime
import shutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from api import pipeline as pl, vidu, wetoken
from api.routes.prompts import video_prompt_with_output_guard
from api.routes.settings import get_api_key

router = APIRouter()


class BatchSubmitItem(BaseModel):
    type: str
    name: Optional[str] = None
    scene_key: Optional[str] = None
    board_id: Optional[str] = None
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: Optional[str] = None
    board_version: str = "v1"


class BatchSubmitRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    items: list[BatchSubmitItem]


class SubmitRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    project_name: str = ""
    project_path: str = ""
    name: Optional[str] = None
    scene_key: Optional[str] = None
    board_id: Optional[str] = None
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: Optional[str] = None
    board_version: str = "v1"


def _get_project_dir(project_name: str, project_path: str = "") -> Path:
    if project_path:
        project_dir = Path(project_path)
    else:
        project_dir = pl.get_project_root(project_name)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail="项目不存在")
    return project_dir


def _get_scene(data: dict, board_version: str, scene_key: str) -> dict | None:
    return data.get("storyboards", {}).get(board_version, {}).get(scene_key)


def _get_board(data: dict, board_version: str, scene_key: str, board_id: str | None = None) -> dict | None:
    scene = _get_scene(data, board_version, scene_key)
    if not scene:
        return None
    boards = scene.get("boards")
    if isinstance(boards, list) and boards:
        if board_id:
            return next((b for b in boards if b.get("board_id") == board_id), None)
        return boards[0]
    return scene


def _sync_scene_from_first_board(scene: dict) -> None:
    boards = scene.get("boards")
    if not isinstance(boards, list) or not boards:
        return
    first = boards[0]
    scene["draft_prompt"] = first.get("draft_prompt", "")
    scene["status"] = first.get("status", "needed")
    scene["board_task_id"] = first.get("board_task_id")
    scene["video_parts"] = first.get("video_parts", [])


def _video_ratio_for_version(board_version: str) -> str:
    return "9:16" if board_version == "v2" else "16:9"


def _ensure_storyboard_can_submit(board: dict | None, prompt: str) -> None:
    if board is None:
        raise HTTPException(status_code=404, detail="故事板场景不存在")
    if not prompt:
        raise HTTPException(status_code=400, detail="故事板缺少最终提示词")
    if board.get("status") != "drafted":
        raise HTTPException(status_code=409, detail="故事板尚未生成最终提示词，不能提交板图")


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _asset_refs_for_board(scene: dict | None, board: dict | None) -> dict:
    scene = scene or {}
    board = board or {}
    refs = board.get("asset_refs") if isinstance(board.get("asset_refs"), dict) else {}
    return {
        "characters": _as_list(board.get("characters") or refs.get("characters") or scene.get("characters_in_scene")),
        "scene": board.get("scene_location") or refs.get("scene") or scene.get("scene_location") or "",
        "props": _as_list(board.get("props") or refs.get("props")),
    }


def _asset_ref_paths(project_dir: Path, refs: dict) -> list[str]:
    paths = []
    for char in refs.get("characters") or []:
        paths.append(str(project_dir / "characters" / char / f"{char}.png"))
    scene_name = refs.get("scene")
    if scene_name:
        paths.append(str(project_dir / "scenes_props" / scene_name / f"{scene_name}.png"))
    for prop in refs.get("props") or []:
        paths.append(str(project_dir / "scenes_props" / prop / f"{prop}.png"))
    return paths


def _resolve_existing_image_paths(project_dir: Path, image_paths: list[str]) -> list[str]:
    resolved = [
        str(project_dir / p) if not Path(p).is_absolute() else p
        for p in image_paths
    ]
    return [p for p in resolved if Path(p).exists()]


def _video_reference_paths(
    project_dir: Path,
    data: dict,
    board_version: str,
    scene_key: str | None,
    board_id: str | None,
    image_paths: list[str],
) -> list[str]:
    paths = _resolve_existing_image_paths(project_dir, image_paths)
    scene = _get_scene(data, board_version, scene_key or "")
    board = _get_board(data, board_version, scene_key or "", board_id)
    paths.extend(_asset_ref_paths(project_dir, _asset_refs_for_board(scene, board)))
    if board:
        result_url = board.get("result_url") or board.get("local_path")
        if result_url:
            paths.append(str(project_dir / result_url))

    deduped = []
    seen = set()
    for path in paths:
        if path not in seen and Path(path).exists():
            deduped.append(path)
            seen.add(path)
    return deduped


def _mark_submitted(item: dict, task_id: str, now: str, task_field: str = "task_id",
                    status_field: str = "status") -> None:
    item[status_field] = "submitted"
    item[task_field] = task_id
    item["submitted_at"] = now
    item["last_checked_at"] = None
    item["status_message"] = "已提交，等待生成结果"
    item.pop("error", None)


def _archive_project_file(project_dir: Path, rel_path: str | None, now: str) -> str | None:
    if not rel_path:
        return None
    project_root = project_dir.resolve()
    candidate = Path(rel_path)
    source = candidate if candidate.is_absolute() else project_dir / candidate
    try:
        resolved_source = source.resolve()
        relative_source = resolved_source.relative_to(project_root)
    except (OSError, ValueError):
        return None
    if not resolved_source.is_file():
        return None

    stamp = now.replace(":", "").replace(".", "_")
    dest = project_dir / "_archived_resubmissions" / stamp / relative_source
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}_{stamp}{dest.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(resolved_source), str(dest))
    return str(dest.relative_to(project_dir))


def _remember_archived_result(item: dict, archived_path: str | None, now: str, field: str) -> None:
    if not archived_path:
        return
    item.setdefault("archived_results", []).append({
        "path": archived_path,
        "field": field,
        "archived_at": now,
        "reason": "resubmit",
    })


def _prepare_image_resubmit_after_success(project_dir: Path, item: dict, now: str) -> None:
    archived = _archive_project_file(project_dir, item.get("result_url") or item.get("local_path"), now)
    _remember_archived_result(item, archived, now, "result_url")
    item["result_url"] = None
    item.pop("local_path", None)
    item.pop("completed_at", None)


def _prepare_video_resubmit_after_success(project_dir: Path, item: dict, now: str) -> None:
    archived = _archive_project_file(project_dir, item.get("local_path"), now)
    _remember_archived_result(item, archived, now, "local_path")
    item["video_url"] = None
    item["local_path"] = None
    item.pop("completed_at", None)


def _video_generation_prompt(prompt: str) -> str:
    return video_prompt_with_output_guard(prompt)


def _scene_generation_prompt(prompt: str) -> str:
    guard = """

STRICT EMPTY LOCATION REQUIREMENT:
Generate an environment reference board only. The image must contain zero people.
No humans, no characters, no faces, no bodies, no hands, no backs, no silhouettes, no human-shaped figures, no person in mirrors/windows/reflections/photos/screens/posters.
If the source description mentions a person, child, woman, man, clothing, body movement, or action, treat it only as off-screen story context and do not depict it.
Show architecture, furniture, props, materials, lighting, camera angles, and spatial layout only.

硬性限制：纯场景空镜参考图，禁止出现任何人物、角色、脸、身体、手、背影、剪影、镜中人物、照片里的人或人形轮廓。"""
    if "STRICT EMPTY LOCATION REQUIREMENT" in prompt or "纯场景空镜参考图" in prompt:
        return prompt
    return prompt.rstrip() + guard


@router.post("/submit")
async def submit_task(req: SubmitRequest):
    project_dir = _get_project_dir(req.project_name, req.project_path)
    data = pl.read_pipeline(project_dir)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    abs_image_paths = _resolve_existing_image_paths(project_dir, req.image_paths)

    resp_task_id = ""
    resp_status = "submitted"
    now = datetime.datetime.now().isoformat()

    if req.type == "character":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="3:4")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset = data["assets"]["characters"][req.name]
        _prepare_image_resubmit_after_success(project_dir, asset, now)
        _mark_submitted(asset, result["task_id"], now)
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "scene":
        prompt = _scene_generation_prompt(req.prompt)
        try:
            result = vidu.submit_image_task(vidu_key, prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset = data["assets"]["scenes"][req.name]
        _prepare_image_resubmit_after_success(project_dir, asset, now)
        asset["draft_prompt"] = prompt
        _mark_submitted(asset, result["task_id"], now)
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "prop":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="1:1")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset = data["assets"]["props"][req.name]
        _prepare_image_resubmit_after_success(project_dir, asset, now)
        _mark_submitted(asset, result["task_id"], now)
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "storyboard":
        scene = _get_scene(data, req.board_version, req.scene_key)
        board = _get_board(data, req.board_version, req.scene_key, req.board_id)
        if scene is None:
            raise HTTPException(status_code=404, detail=f"故事板场景不存在")
        _ensure_storyboard_can_submit(board, req.prompt)
        abs_image_paths.extend(_resolve_existing_image_paths(
            project_dir,
            _asset_ref_paths(project_dir, _asset_refs_for_board(scene, board)),
        ))
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        _prepare_image_resubmit_after_success(project_dir, board, now)
        _mark_submitted(board, result["task_id"], now, task_field="board_task_id")
        _sync_scene_from_first_board(scene)
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "video":
        duration = req.duration or 10
        prompt = _video_generation_prompt(req.prompt)
        ratio = req.ratio or _video_ratio_for_version(req.board_version)
        abs_image_paths = _video_reference_paths(
            project_dir, data, req.board_version, req.scene_key, req.board_id, req.image_paths
        )
        try:
            task_id = wetoken.submit_video_task(
                wetoken_key, prompt, abs_image_paths,
                duration=duration, ratio=ratio, project_dir=project_dir,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Wetoken API 错误: {e}")
        scene = _get_scene(data, req.board_version, req.scene_key)
        board = _get_board(data, req.board_version, req.scene_key, req.board_id)
        if scene is None or board is None:
            raise HTTPException(status_code=404, detail=f"故事板场景不存在")
        video_parts = board.setdefault("video_parts", [])
        target_vp = next((vp for vp in video_parts if vp["part"] == req.part), None)
        if not target_vp:
            target_vp = {
                "part": req.part,
                "draft_prompt": prompt,
                "prompt": prompt,
                "duration": duration,
                "ratio": ratio,
                "video_status": "submitted",
                "video_task_id": task_id,
                "submitted_at": now,
                "last_checked_at": None,
                "status_message": "已提交，等待生成结果",
                "video_url": None,
                "local_path": None,
            }
            video_parts.append(target_vp)
        else:
            _prepare_video_resubmit_after_success(project_dir, target_vp, now)
            _mark_submitted(target_vp, task_id, now, task_field="video_task_id", status_field="video_status")
            target_vp["draft_prompt"] = prompt
            target_vp["prompt"] = prompt
            target_vp["ratio"] = ratio
        _sync_scene_from_first_board(scene)
        resp_task_id = task_id

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")

    data["updated_at"] = now
    pl.write_pipeline(project_dir, data)
    return {"task_id": resp_task_id, "status": resp_status}


@router.post("/batch-submit")
async def batch_submit_tasks(req: BatchSubmitRequest):
    import asyncio

    project_dir = _get_project_dir(req.project_name, req.project_path)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    sem = asyncio.Semaphore(3)

    async def _submit_one(item: BatchSubmitItem):
        async with sem:
            return await _submit_single(item, project_dir, vidu_key, wetoken_key)

    results = await asyncio.gather(*[_submit_one(item) for item in req.items])

    data = pl.read_pipeline(project_dir)
    now = datetime.datetime.now().isoformat()
    for r in results:
        if not r.get("ok"):
            continue
        if r["type"] == "character":
            asset = data.get("assets", {}).get("characters", {}).get(r["name"])
            if asset:
                _prepare_image_resubmit_after_success(project_dir, asset, now)
                _mark_submitted(asset, r["task_id"], now)
        elif r["type"] == "scene":
            asset = data.get("assets", {}).get("scenes", {}).get(r["name"])
            if asset:
                _prepare_image_resubmit_after_success(project_dir, asset, now)
                if r.get("prompt"):
                    asset["draft_prompt"] = r["prompt"]
                _mark_submitted(asset, r["task_id"], now)
        elif r["type"] == "prop":
            asset = data.get("assets", {}).get("props", {}).get(r["name"])
            if asset:
                _prepare_image_resubmit_after_success(project_dir, asset, now)
                _mark_submitted(asset, r["task_id"], now)
        elif r["type"] == "storyboard":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            board = _get_board(data, r["board_version"], r["scene_key"], r.get("board_id"))
            if scene is not None and board is not None:
                _prepare_image_resubmit_after_success(project_dir, board, now)
                _mark_submitted(board, r["task_id"], now, task_field="board_task_id")
                _sync_scene_from_first_board(scene)
        elif r["type"] == "video":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            board = _get_board(data, r["board_version"], r["scene_key"], r.get("board_id"))
            if scene is not None and board is not None:
                video_parts = board.setdefault("video_parts", [])
                target_vp = next((vp for vp in video_parts if vp["part"] == r["part"]), None)
                if not target_vp:
                    target_vp = {
                        "part": r["part"],
                        "draft_prompt": r.get("prompt", ""),
                        "prompt": r.get("prompt", ""),
                        "duration": r["duration"],
                        "ratio": r.get("ratio"),
                        "video_status": "submitted",
                        "video_task_id": r["task_id"],
                        "submitted_at": now,
                        "last_checked_at": None,
                        "status_message": "已提交，等待生成结果",
                        "video_url": None,
                        "local_path": None,
                    }
                    video_parts.append(target_vp)
                else:
                    _prepare_video_resubmit_after_success(project_dir, target_vp, now)
                    _mark_submitted(target_vp, r["task_id"], now, task_field="video_task_id", status_field="video_status")
                    if r.get("prompt"):
                        target_vp["draft_prompt"] = r["prompt"]
                        target_vp["prompt"] = r["prompt"]
                    target_vp["ratio"] = r.get("ratio")
                _sync_scene_from_first_board(scene)

    data["updated_at"] = now
    pl.write_pipeline(project_dir, data)

    response_results = []
    for r in results:
        name = r.get("name") or r.get("scene_key") or ""
        if r.get("ok"):
            response_results.append({"name": name, "ok": True, "task_id": r["task_id"]})
        else:
            response_results.append({"name": name, "ok": False, "error": r.get("error", "")})
    return {"results": response_results}


async def _submit_single(item: BatchSubmitItem, project_dir: Path, vidu_key: str, wetoken_key: str) -> dict:
    abs_image_paths = _resolve_existing_image_paths(project_dir, item.image_paths)

    try:
        if item.type == "character":
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="3:4")
            return {"type": "character", "name": item.name, "task_id": result["task_id"], "ok": True}

        elif item.type == "scene":
            prompt = _scene_generation_prompt(item.prompt)
            result = await vidu.submit_image_task_async(
                vidu_key, prompt, abs_image_paths, ratio="16:9"
            )
            return {"type": "scene", "name": item.name, "task_id": result["task_id"], "prompt": prompt, "ok": True}

        elif item.type == "prop":
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="1:1")
            return {"type": "prop", "name": item.name, "task_id": result["task_id"], "ok": True}

        elif item.type == "storyboard":
            data = pl.read_pipeline(project_dir)
            scene = _get_scene(data, item.board_version, item.scene_key)
            board = _get_board(data, item.board_version, item.scene_key, item.board_id)
            if board is None:
                return {"type": "storyboard", "scene_key": item.scene_key, "name": item.scene_key,
                        "board_version": item.board_version, "board_id": item.board_id,
                        "ok": False, "error": "故事板场景不存在"}
            if not item.prompt:
                return {"type": "storyboard", "scene_key": item.scene_key, "name": item.scene_key,
                        "board_version": item.board_version, "board_id": item.board_id,
                        "ok": False, "error": "故事板缺少最终提示词"}
            if board.get("status") != "drafted":
                return {"type": "storyboard", "scene_key": item.scene_key, "name": item.scene_key,
                        "board_version": item.board_version, "board_id": item.board_id,
                        "ok": False, "error": "故事板尚未生成最终提示词，不能提交板图"}
            abs_image_paths.extend(_resolve_existing_image_paths(
                project_dir,
                _asset_ref_paths(project_dir, _asset_refs_for_board(scene, board)),
            ))
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="16:9")
            return {"type": "storyboard", "scene_key": item.scene_key, "name": item.scene_key,
                    "board_version": item.board_version, "board_id": item.board_id,
                    "task_id": result["task_id"], "ok": True}

        elif item.type == "video":
            duration = item.duration or 10
            prompt = _video_generation_prompt(item.prompt)
            data = pl.read_pipeline(project_dir)
            ratio = item.ratio or _video_ratio_for_version(item.board_version)
            abs_image_paths = _video_reference_paths(
                project_dir, data, item.board_version, item.scene_key, item.board_id, item.image_paths
            )
            task_id = await wetoken.submit_video_task_async(
                wetoken_key, prompt, abs_image_paths,
                duration=duration, ratio=ratio, project_dir=project_dir,
            )
            return {"type": "video", "scene_key": item.scene_key, "name": item.scene_key,
                    "part": item.part, "board_version": item.board_version, "board_id": item.board_id,
                    "task_id": task_id, "duration": duration, "ratio": ratio, "prompt": prompt, "ok": True}

        else:
            return {"type": item.type, "name": item.name or "", "ok": False, "error": f"未知类型: {item.type}"}
    except Exception as e:
        return {"type": item.type, "name": item.name or item.scene_key or "", "ok": False, "error": str(e)}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, req: SubmitRequest):
    return await submit_task(req)
