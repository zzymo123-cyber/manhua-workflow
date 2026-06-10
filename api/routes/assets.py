from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pathlib import Path

from api import pipeline as pl

router = APIRouter()


@router.get("/assets/{project_name}/{path:path}")
async def get_asset(project_name: str, path: str):
    """
    代理返回本地图片。
    path 相对于 ~/Desktop/vidu_studio/{project_name}/
    例：characters/婉瑜/婉瑜.png
    """
    project_dir = pl.get_project_root(project_name)
    file_path = project_dir / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    return FileResponse(str(file_path), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/asset-file")
async def get_asset_by_path(
    project_path: str = Query(...),
    file_path: str = Query(...)
):
    """
    通过完整项目路径访问资产文件，适用于任意路径的项目。
    project_path: 项目目录绝对路径
    file_path:    相对于项目目录的文件路径，如 characters/婉瑜/婉瑜.png
    """
    full_path = Path(project_path) / file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在")
    return FileResponse(str(full_path), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
