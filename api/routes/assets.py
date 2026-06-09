from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pathlib import Path

from api import pipeline as pl

router = APIRouter()

_MISSING_IMAGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180" role="img" aria-label="文件缺失">
  <rect width="320" height="180" rx="8" fill="#f1f3f5"/>
  <path d="M116 111l28-32 20 22 12-14 28 24H116z" fill="#d1d5db"/>
  <circle cx="204" cy="65" r="13" fill="#d1d5db"/>
  <text x="160" y="142" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="13" fill="#6b7280">本地文件缺失</text>
</svg>"""


def _resolve_asset_path(project_dir: Path, relative_path: str) -> Path:
    base = project_dir.resolve()
    requested = Path(relative_path)
    if requested.is_absolute():
        raise HTTPException(status_code=403, detail="不允许访问项目目录外的文件")

    full_path = (base / requested).resolve()
    try:
        full_path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="不允许访问项目目录外的文件")
    return full_path


def _require_project_dir(project_path: str) -> Path:
    project_dir = Path(project_path).resolve()
    if not project_dir.is_dir() or not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    return project_dir


@router.get("/assets/{project_name}/{path:path}")
async def get_asset(project_name: str, path: str):
    """
    代理返回本地图片。
    path 相对于 ~/Desktop/vidu_studio/{project_name}/
    例：characters/婉瑜/婉瑜.png
    """
    project_dir = pl.get_project_root(project_name)
    file_path = _resolve_asset_path(project_dir, path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    return FileResponse(str(file_path))


@router.get("/asset-file")
async def get_asset_by_path(
    project_path: str = Query(...),
    file_path: str = Query(...),
    preview: bool = Query(False),
):
    """
    通过完整项目路径访问资产文件，适用于任意路径的项目。
    project_path: 项目目录绝对路径
    file_path:    相对于项目目录的文件路径，如 characters/婉瑜/婉瑜.png
    """
    project_dir = _require_project_dir(project_path)
    full_path = _resolve_asset_path(project_dir, file_path)
    if not full_path.exists():
        if preview:
            return Response(_MISSING_IMAGE_SVG, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail=f"文件不存在")
    return FileResponse(str(full_path))
