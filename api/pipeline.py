import json
import os
from pathlib import Path

VIDU_STUDIO_ROOT = Path.home() / "Desktop" / "vidu_studio"


def get_project_root(project_name: str) -> Path:
    p = Path(project_name)
    if p.is_absolute():
        return p
    return VIDU_STUDIO_ROOT / project_name


def _pipeline_path(project_dir: Path) -> Path:
    return project_dir / "pipeline.json"


def read_pipeline(project_dir: Path) -> dict:
    path = _pipeline_path(project_dir)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_pipeline(project_dir: Path, data: dict) -> None:
    """原子写入：先写 .tmp 再 rename"""
    path = _pipeline_path(project_dir)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _meta_dir(project_dir: Path, category: str, name: str) -> Path:
    return project_dir / category / name


def get_meta(project_dir: Path, category: str, name: str) -> dict | None:
    meta_path = _meta_dir(project_dir, category, name) / "meta.json"
    if not meta_path.exists():
        return None
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def write_meta(project_dir: Path, category: str, name: str, data: dict) -> None:
    """原子写入 meta.json"""
    meta_dir = _meta_dir(project_dir, category, name)
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = meta_dir / "meta.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_asset_image_path(project_dir: Path, category: str, name: str, filename: str) -> Path:
    return _meta_dir(project_dir, category, name) / filename


def get_primary_image_path(project_dir: Path, category: str, name: str) -> Path | None:
    """从 meta.json 读 primary_image，返回绝对路径"""
    meta = get_meta(project_dir, category, name)
    if not meta or not meta.get("primary_image"):
        return None
    return _meta_dir(project_dir, category, name) / meta["primary_image"]


def get_prompt_optimized(project_dir: Path, category: str, name: str) -> str | None:
    """从 primary_image 对应 version 读 prompt.optimized"""
    meta = get_meta(project_dir, category, name)
    if not meta:
        return None
    primary = meta.get("primary_image")
    for v in meta.get("versions", []):
        if v.get("filename") == primary:
            return v.get("prompt", {}).get("optimized")
    return None


# ── 提示词模板 ──

_PROMPT_TEMPLATE_DEFAULTS = None  # lazy-loaded


def _get_prompt_template_defaults() -> dict:
    """延迟加载默认值（避免循环 import）"""
    global _PROMPT_TEMPLATE_DEFAULTS
    if _PROMPT_TEMPLATE_DEFAULTS is None:
        from api.routes.prompts import CHARACTER_SYSTEM, SCENE_SYSTEM, PROP_SYSTEM, STORYBOARD_SYSTEM, VIDEO_SYSTEM
        _PROMPT_TEMPLATE_DEFAULTS = {
            "character": CHARACTER_SYSTEM,
            "scene": SCENE_SYSTEM,
            "prop": PROP_SYSTEM,
            "storyboard": STORYBOARD_SYSTEM,
            "video": VIDEO_SYSTEM,
        }
    return _PROMPT_TEMPLATE_DEFAULTS


def read_prompt_templates(project_dir: Path) -> dict:
    """读取 prompt_templates.json，不存在则返回默认值"""
    path = project_dir / "prompt_templates.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return _get_prompt_template_defaults()


def write_prompt_templates(project_dir: Path, data: dict) -> None:
    """原子写入 prompt_templates.json"""
    path = project_dir / "prompt_templates.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_prompt_template_defaults() -> dict:
    """返回内置默认模板（不读文件），供 Reset to Default 使用"""
    return _get_prompt_template_defaults()
