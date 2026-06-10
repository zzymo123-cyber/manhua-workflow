import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from api import pipeline as pl, vidu, wetoken
from api.routes.settings import get_api_key

router = APIRouter()


class BatchSubmitItem(BaseModel):
    type: str
    name: Optional[str] = None
    scene_key: Optional[str] = None
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: str = "16:9"
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
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: str = "16:9"
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


@router.post("/submit")
async def submit_task(req: SubmitRequest):
    project_dir = _get_project_dir(req.project_name, req.project_path)
    data = pl.read_pipeline(project_dir)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    abs_image_paths = [
        str(project_dir / p) if not Path(p).is_absolute() else p
        for p in req.image_paths
    ]
    abs_image_paths = [p for p in abs_image_paths if Path(p).exists()]

    resp_task_id = ""
    resp_status = "submitted"

    if req.type == "character":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="3:4")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset = data["assets"]["characters"][req.name]
        asset["status"] = "submitted"
        asset["task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "scene":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset = data["assets"]["scenes"][req.name]
        asset["status"] = "submitted"
        asset["task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "prop":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="1:1")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        asset = data["assets"]["props"][req.name]
        asset["status"] = "submitted"
        asset["task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "storyboard":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        scene = _get_scene(data, req.board_version, req.scene_key)
        if scene is None:
            raise HTTPException(status_code=404, detail=f"故事板场景不存在")
        scene["status"] = "submitted"
        scene["board_task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "video":
        duration = req.duration or 10
        task_id = wetoken.submit_video_task(
            wetoken_key, req.prompt, abs_image_paths,
            duration=duration, ratio=req.ratio, project_dir=project_dir,
        )
        scene = _get_scene(data, req.board_version, req.scene_key)
        if scene is None:
            raise HTTPException(status_code=404, detail=f"故事板场景不存在")
        video_parts = scene.setdefault("video_parts", [])
        target_vp = next((vp for vp in video_parts if vp["part"] == req.part), None)
        if not target_vp:
            target_vp = {
                "part": req.part,
                "draft_prompt": req.prompt,
                "prompt": req.prompt,
                "duration": duration,
                "video_status": "submitted",
                "video_task_id": task_id,
                "video_url": None,
                "local_path": None,
            }
            video_parts.append(target_vp)
        else:
            target_vp["video_status"] = "submitted"
            target_vp["video_task_id"] = task_id
        resp_task_id = task_id

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")

    data["updated_at"] = datetime.datetime.now().isoformat()
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
    for r in results:
        if not r.get("ok"):
            continue
        if r["type"] == "character":
            asset = data.get("assets", {}).get("characters", {}).get(r["name"])
            if asset:
                asset["status"] = "submitted"
                asset["task_id"] = r["task_id"]
        elif r["type"] == "scene":
            asset = data.get("assets", {}).get("scenes", {}).get(r["name"])
            if asset:
                asset["status"] = "submitted"
                asset["task_id"] = r["task_id"]
        elif r["type"] == "prop":
            asset = data.get("assets", {}).get("props", {}).get(r["name"])
            if asset:
                asset["status"] = "submitted"
                asset["task_id"] = r["task_id"]
        elif r["type"] == "storyboard":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            if scene is not None:
                scene["status"] = "submitted"
                scene["board_task_id"] = r["task_id"]
        elif r["type"] == "video":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            if scene is not None:
                video_parts = scene.setdefault("video_parts", [])
                target_vp = next((vp for vp in video_parts if vp["part"] == r["part"]), None)
                if not target_vp:
                    target_vp = {
                        "part": r["part"],
                        "draft_prompt": "",
                        "prompt": "",
                        "duration": r["duration"],
                        "video_status": "submitted",
                        "video_task_id": r["task_id"],
                        "video_url": None,
                        "local_path": None,
                    }
                    video_parts.append(target_vp)
                else:
                    target_vp["video_status"] = "submitted"
                    target_vp["video_task_id"] = r["task_id"]

    data["updated_at"] = datetime.datetime.now().isoformat()
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
    abs_image_paths = [
        str(project_dir / p) if not Path(p).is_absolute() else p
        for p in item.image_paths
    ]
    abs_image_paths = [p for p in abs_image_paths if Path(p).exists()]

    try:
        if item.type == "character":
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="3:4")
            return {"type": "character", "name": item.name, "task_id": result["task_id"], "ok": True}

        elif item.type == "scene":
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="16:9")
            return {"type": "scene", "name": item.name, "task_id": result["task_id"], "ok": True}

        elif item.type == "prop":
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="1:1")
            return {"type": "prop", "name": item.name, "task_id": result["task_id"], "ok": True}

        elif item.type == "storyboard":
            result = await vidu.submit_image_task_async(vidu_key, item.prompt, abs_image_paths, ratio="16:9")
            return {"type": "storyboard", "scene_key": item.scene_key, "name": item.scene_key,
                    "board_version": item.board_version,
                    "task_id": result["task_id"], "ok": True}

        elif item.type == "video":
            duration = item.duration or 10
            task_id = await wetoken.submit_video_task_async(
                wetoken_key, item.prompt, abs_image_paths,
                duration=duration, ratio=item.ratio, project_dir=project_dir,
            )
            return {"type": "video", "scene_key": item.scene_key, "name": item.scene_key,
                    "part": item.part, "board_version": item.board_version,
                    "task_id": task_id, "duration": duration, "ok": True}

        else:
            return {"type": item.type, "name": item.name or "", "ok": False, "error": f"未知类型: {item.type}"}
    except Exception as e:
        return {"type": item.type, "name": item.name or item.scene_key or "", "ok": False, "error": str(e)}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, req: SubmitRequest):
    return await submit_task(req)
