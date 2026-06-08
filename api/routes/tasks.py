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


class BatchSubmitRequest(BaseModel):
    project_name: str
    items: list[BatchSubmitItem]


class SubmitRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    project_name: str
    name: Optional[str] = None
    scene_key: Optional[str] = None
    part: Optional[int] = None
    prompt: str
    image_paths: list[str] = []
    duration: Optional[int] = None
    ratio: str = "16:9"


def _get_project_dir(project_name: str) -> Path:
    project_dir = pl.get_project_root(project_name)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目 {project_name} 不存在")
    return project_dir


@router.post("/submit")
async def submit_task(req: SubmitRequest):
    import logging
    logger = logging.getLogger("manhua.submit")
    logger.info("submit_task: type=%s project=%s name=%s scene_key=%s part=%s",
                req.type, req.project_name, req.name, req.scene_key, req.part)
    project_dir = _get_project_dir(req.project_name)
    data = pl.read_pipeline(project_dir)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    # 将相对路径解析为绝对路径（前端传来的 image_paths 是相对于项目目录的）
    abs_image_paths = [
        str(project_dir / p) if not Path(p).is_absolute() else p
        for p in req.image_paths
    ]
    # 过滤掉不存在的文件，避免 _img_to_data_uri 报 FileNotFoundError
    abs_image_paths = [p for p in abs_image_paths if Path(p).exists()]

    resp_task_id = ""
    resp_status = "submitted"

    if req.type == "character":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="3:4")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        data["assets"]["characters"][req.name]["status"] = "submitted"
        data["assets"]["characters"][req.name]["task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "scene":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        data["assets"]["scenes"][req.name]["status"] = "submitted"
        data["assets"]["scenes"][req.name]["task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "prop":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="1:1")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        data["assets"]["props"][req.name]["status"] = "submitted"
        data["assets"]["props"][req.name]["task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "storyboard":
        try:
            result = vidu.submit_image_task(vidu_key, req.prompt, abs_image_paths, ratio="16:9")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Vidu API 错误: {e}")
        data["storyboards"][req.scene_key]["board_status"] = "submitted"
        data["storyboards"][req.scene_key]["board_task_id"] = result["task_id"]
        resp_task_id, resp_status = result["task_id"], "submitted"

    elif req.type == "video":
        duration = req.duration or 10
        task_id = wetoken.submit_video_task(
            wetoken_key, req.prompt, abs_image_paths,
            duration=duration, ratio=req.ratio, project_dir=project_dir,
        )
        video_parts = data["storyboards"][req.scene_key].setdefault("video_parts", [])
        for p in video_parts:
            if p["part"] == req.part:
                p["video_status"] = "submitted"
                p["video_task_id"] = task_id
                break
        else:
            video_parts.append({"part": req.part, "video_status": "submitted", "video_task_id": task_id, "video_url": None})
        resp_task_id = task_id

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")

    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"task_id": resp_task_id, "status": resp_status}



@router.post("/batch-submit")
async def batch_submit_tasks(req: BatchSubmitRequest):
    """批量提交任务，逐个处理，返回每项结果"""
    results = []
    for item in req.items:
        try:
            single_req = SubmitRequest(
                type=item.type, project_name=req.project_name,
                name=item.name, scene_key=item.scene_key, part=item.part,
                prompt=item.prompt, image_paths=item.image_paths,
                duration=item.duration, ratio=item.ratio,
            )
            result = await submit_task(single_req)
            results.append({"name": item.name or item.scene_key or "", "ok": True, "task_id": result["task_id"]})
        except Exception as e:
            results.append({"name": item.name or item.scene_key or "", "ok": False, "error": str(e)})
    return {"results": results}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, req: SubmitRequest):
    """重试失败任务：重新提交，返回新 task_id"""
    return await submit_task(req)
