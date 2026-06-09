import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

from api import pipeline as pl
from api import parser
from api.routes.settings import get_api_key

router = APIRouter()
logger = logging.getLogger(__name__)

_REQUIRED_ENV = ["VIDU_API_KEY", "WETOKEN_API_KEY", "IDEALAB_API_KEY"]


class ImportRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""  # 优先使用，绝对路径


class ParseRequest(BaseModel):
    input_dir: str   # 剧本标准输入目录的绝对路径
    project_name: str


def _save_recent(name: str, path: str) -> None:
    """将项目记录到 settings.json 的 recent_projects（最多保留10条）"""
    from api.routes.settings import read_settings, write_settings
    try:
        settings = read_settings()
        recent = settings.get("recent_projects", [])
        if not isinstance(recent, list):
            recent = []
        # 去重：同路径的条目先移除
        recent = [r for r in recent if isinstance(r, dict) and r.get("path") != path]
        recent.insert(0, {"name": name, "path": path})
        settings["recent_projects"] = recent[:10]
        write_settings(settings)
    except Exception as exc:
        logger.warning("Failed to save recent project %s: %s", path, exc)


def _require_project_dir(project_name: str = "", project_path: str = "") -> Path:
    project_dir = pl.resolve_project_dir(project_name, project_path)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    return project_dir


@router.post("/import")
async def import_project(req: ImportRequest):
    """
    检查 pipeline.json 是否存在。
    已存在: 返回 {_exists: True, ...pipeline内容}
    不存在: 返回 404
    """
    project_dir = pl.resolve_project_dir(req.project_name, req.project_path)
    pipeline_path = project_dir / "pipeline.json"
    if not pipeline_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到 pipeline.json：{project_dir}")
    data = pl.read_pipeline(project_dir)
    data["_exists"] = True
    _save_recent(data.get("project", project_dir.name), str(project_dir))
    return data


@router.post("/parse")
async def parse_project(req: ParseRequest):
    """
    从剧本标准输入目录解析生成 pipeline.json，保存在同一目录下。
    返回解析结果供前端预览。
    """
    project_name = req.project_name.strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    input_dir = Path(req.input_dir).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在：{req.input_dir}")

    # 校验最小文件集
    missing_files = []
    for f in ["character_visuals.md", "scene_props_visuals.md"]:
        if not (input_dir / f).exists():
            missing_files.append(f)
    if not (input_dir / "script").is_dir():
        missing_files.append("script/")
    if missing_files:
        raise HTTPException(status_code=400, detail=f"目录缺少必要文件：{', '.join(missing_files)}")

    try:
        data = parser.parse_input_dir(input_dir, project_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败：{e}")

    # 保存 pipeline.json 到输入目录
    pl.write_pipeline(input_dir, data)

    # 记录最近项目
    _save_recent(project_name, str(input_dir))

    return {
        "ok": True,
        "project_name": project_name,
        "input_dir": str(input_dir),
        "stats": {
            "characters": len(data["assets"]["characters"]),
            "scenes": len(data["assets"]["scenes"]),
            "props": len(data["assets"]["props"]),
            "storyboards": len(data["storyboards"]),
        },
        "pipeline": data,
    }


@router.get("/list-recent")
async def list_recent():
    """
    读取 settings.json 里的 recent_projects 列表，
    验证每个目录的 pipeline.json 是否仍存在，返回有效项目列表。
    """
    from api.routes.settings import read_settings
    settings = read_settings()
    recent = settings.get("recent_projects", [])
    valid = []
    for entry in recent:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        path = Path(entry["path"])
        if (path / "pipeline.json").exists():
            valid.append(entry)
    return {"projects": valid}


@router.get("/status")
async def get_status(project_name: str = "", project_path: str = ""):
    project_dir = _require_project_dir(project_name, project_path)
    data = pl.read_pipeline(project_dir)
    missing = [k for k in _REQUIRED_ENV if not get_api_key(k)]
    if missing:
        data["_warnings"] = [f"缺少 API Key: {', '.join(missing)}"]
    return data


# ── 提示词模板 API ──


@router.get("/prompt-templates")
async def get_prompt_templates(project_name: str = "", project_path: str = "", defaults: bool = False):
    """读取项目提示词模板。defaults=true 时返回内置默认值"""
    if defaults:
        return pl.get_prompt_template_defaults()
    project_dir = _require_project_dir(project_name, project_path)
    return pl.read_prompt_templates(project_dir)


class UpdateTemplatesRequest(BaseModel):
    character: str | None = None
    scene: str | None = None
    prop: str | None = None
    storyboard: str | None = None
    video: str | None = None


@router.put("/prompt-templates")
async def update_prompt_templates(req: UpdateTemplatesRequest, project_name: str = "", project_path: str = ""):
    """更新项目提示词模板（部分更新）"""
    project_dir = _require_project_dir(project_name, project_path)
    current = pl.read_prompt_templates(project_dir)
    for key, value in req.model_dump().items():
        if value is not None:
            current[key] = value
    pl.write_prompt_templates(project_dir, current)
    return {"ok": True}
