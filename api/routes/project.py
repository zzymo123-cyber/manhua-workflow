import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import subprocess

from api import pipeline as pl
from api import parser
from api.routes.settings import get_api_key

router = APIRouter()

_REQUIRED_ENV = ["VIDU_API_KEY", "WETOKEN_API_KEY", "IDEALAB_API_KEY"]


class ImportRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""  # 优先使用，绝对路径


class ParseRequest(BaseModel):
    input_dir: str   # 剧本标准输入目录的绝对路径
    project_name: str
    dry_run: bool = False


class OpenDocumentRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    file_path: str


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


def _resolve_project_file(project_dir: Path, file_path: str) -> Path:
    root = project_dir.resolve()
    target = (root / file_path).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="文件路径必须在项目目录内")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在：{file_path}")
    return target


def _project_documents(project_dir: Path) -> list[dict]:
    allowed = {".md", ".txt", ".docx", ".pdf"}
    ignored_dirs = {"characters", "scenes_props", "storyboards", "videos", "__pycache__", ".git"}
    docs = [{
        "name": "项目根目录",
        "path": ".",
        "kind": "folder",
        "size": 0,
        "updated_at": datetime.datetime.fromtimestamp(project_dir.stat().st_mtime).isoformat(),
    }]
    asset_dirs = [
        ("角色图片目录", "characters"),
        ("场景/道具图片目录", "scenes_props"),
        ("故事板图片目录", "storyboards"),
        ("视频目录", "videos"),
    ]
    for label, rel_path in asset_dirs:
        path = project_dir / rel_path
        if path.exists() and path.is_dir():
            docs.append({
                "name": label,
                "path": rel_path,
                "kind": "folder",
                "size": 0,
                "updated_at": datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            })
    for path in project_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        rel = path.relative_to(project_dir)
        if any(part in ignored_dirs for part in rel.parts):
            continue
        docs.append({
            "name": path.name,
            "path": str(rel),
            "kind": "document",
            "size": path.stat().st_size,
            "updated_at": datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        })
    return sorted(docs, key=lambda d: (0 if d["kind"] == "folder" else 1, Path(d["path"]).parent.as_posix(), d["name"]))


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
    # 至少要有一个 script_vN 或 script 目录；视觉文档是可选的。
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

    if not req.dry_run:
        pl.write_pipeline(input_dir, data)
        _save_recent(req.project_name, str(input_dir))

    # 统计各版本场景数；新导入默认不创建故事板生产线。
    version_stats = {
        ver: len(scenes)
        for ver, scenes in data.get("storyboards", {}).items()
    }
    board_page_stats = {
        ver: sum(len(scene.get("boards", [scene])) for scene in scenes.values() if isinstance(scene, dict))
        for ver, scenes in data.get("storyboards", {}).items()
    }

    return {
        "ok": True,
        "dry_run": req.dry_run,
        "project_name": req.project_name,
        "input_dir": str(input_dir),
        "stats": {
            "characters": len(data["assets"]["characters"]),
            "scenes": len(data["assets"]["scenes"]),
            "props": len(data["assets"]["props"]),
            "source_scenes": len(data.get("source_scenes", {})),
            "storyboard_versions": version_stats,
            "storyboard_pages": board_page_stats,
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
    missing = [k for k in _REQUIRED_ENV if not get_api_key(k)]
    if missing:
        data["_warnings"] = [f"缺少 API Key: {', '.join(missing)}"]
    return data


@router.get("/documents")
async def list_documents(project_name: str = "", project_path: str = ""):
    project_dir = _resolve_project_dir(project_path, project_name)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    return {"documents": _project_documents(project_dir)}


@router.post("/open-document")
async def open_document(req: OpenDocumentRequest):
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    target = _resolve_project_file(project_dir, req.file_path)
    try:
        subprocess.Popen(["open", str(target)])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开文件失败：{e}")
    return {"ok": True}


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
