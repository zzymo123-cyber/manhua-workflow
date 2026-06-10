import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import os

from api import pipeline as pl
from api import parser

router = APIRouter()

_REQUIRED_ENV = ["VIDU_API_KEY", "WETOKEN_API_KEY", "IDEALAB_API_KEY"]


class ImportRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""  # 优先使用，绝对路径


class ParseRequest(BaseModel):
    input_dir: str   # 剧本标准输入目录的绝对路径
    project_name: str


def _resolve_project_dir(project_path: str, project_name: str) -> Path:
    if project_path:
        return Path(project_path)
    return pl.get_project_root(project_name)


def _save_recent(name: str, path: str) -> None:
    from api.routes.settings import read_settings, write_settings
    settings = read_settings()
    recent = settings.get("recent_projects", [])
    recent = [r for r in recent if r.get("path") != path]
    recent.insert(0, {"name": name, "path": path})
    settings["recent_projects"] = recent[:10]
    write_settings(settings)


@router.post("/import")
async def import_project(req: ImportRequest):
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    pipeline_path = project_dir / "pipeline.json"
    if not pipeline_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到 pipeline.json：{project_dir}")
    data = pl.read_pipeline(project_dir)
    # 若发生了格式迁移，写回磁盘（持久化新格式，避免重复迁移）
    if data.get("_migrated"):
        pl.write_pipeline(project_dir, data)
    data["_exists"] = True
    _save_recent(data.get("project", project_dir.name), str(project_dir))
    return data


@router.post("/parse")
async def parse_project(req: ParseRequest):
    """
    从剧本标准输入目录解析生成 pipeline.json。
    支持 script_v1/, script_v2/, ... 多版本目录，兼容旧 script/ 目录。
    """
    input_dir = Path(req.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在：{req.input_dir}")

    missing_files = []
    for f in ["character_visuals.md", "scene_props_visuals.md"]:
        if not (input_dir / f).exists():
            missing_files.append(f)
    # 至少要有一个 script_vN 或 script 目录
    has_script = any(
        d.is_dir() and (d.name == "script" or (d.name.startswith("script_v") and d.name[8:].isdigit()))
        for d in input_dir.iterdir()
    ) if input_dir.exists() else False
    if not has_script:
        missing_files.append("script_v1/ (或 script/)")
    if missing_files:
        raise HTTPException(status_code=400, detail=f"目录缺少必要文件：{', '.join(missing_files)}")

    try:
        data = parser.parse_input_dir(input_dir, req.project_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败：{e}")

    pl.write_pipeline(input_dir, data)
    _save_recent(req.project_name, str(input_dir))

    # 统计各版本场景数
    version_stats = {
        ver: len(scenes)
        for ver, scenes in data["storyboards"].items()
    }

    return {
        "ok": True,
        "project_name": req.project_name,
        "input_dir": str(input_dir),
        "stats": {
            "characters": len(data["assets"]["characters"]),
            "scenes": len(data["assets"]["scenes"]),
            "props": len(data["assets"]["props"]),
            "storyboard_versions": version_stats,
        },
        "pipeline": data,
    }


@router.get("/list-recent")
async def list_recent():
    from api.routes.settings import read_settings
    settings = read_settings()
    recent = settings.get("recent_projects", [])
    valid = []
    for entry in recent:
        path = Path(entry["path"])
        if (path / "pipeline.json").exists():
            valid.append(entry)
    return {"projects": valid}


@router.get("/status")
async def get_status(project_name: str = "", project_path: str = ""):
    project_dir = _resolve_project_dir(project_path, project_name)
    pipeline_path = project_dir / "pipeline.json"
    if not pipeline_path.exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    data = pl.read_pipeline(project_dir)
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        data["_warnings"] = [f"缺少环境变量: {', '.join(missing)}"]
    return data


# ── 提示词模板 API ──
# 模板结构：character, scene, prop 各一套；storyboard_v1/storyboard_v2/... 和 video_v1/video_v2/... 按版本独立


@router.get("/prompt-templates")
async def get_prompt_templates(project_name: str = "", project_path: str = "", defaults: bool = False):
    project_dir = _resolve_project_dir(project_path, project_name)
    if defaults:
        return pl.get_prompt_template_defaults()
    return pl.read_prompt_templates(project_dir)


class UpdateTemplatesRequest(BaseModel):
    updates: dict  # {key: content_str}，key 如 "character"/"storyboard_v1"/"video_v2"
    project_path: str = ""
    project_name: str = ""


@router.put("/prompt-templates")
async def update_prompt_templates(req: UpdateTemplatesRequest):
    """更新项目提示词模板（部分更新）"""
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    current = pl.read_prompt_templates(project_dir)
    for key, value in req.updates.items():
        if value is not None:
            current[key] = value
    pl.write_prompt_templates(project_dir, current)
    return {"ok": True}


def _mark_downstream_stale(data: dict, category: str, name: str):
    """资产版本切换后，标记引用它的故事板为过期（仅用于前端提示，不阻塞操作）"""
    pass  # 新结构中不再需要 dependency_stale 机制
