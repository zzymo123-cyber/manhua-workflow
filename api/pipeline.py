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
        data = json.load(f)
    return migrate_pipeline(data)


def write_pipeline(project_dir: Path, data: dict) -> None:
    """原子写入：先写 .tmp 再 rename"""
    path = _pipeline_path(project_dir)
    tmp = path.with_suffix(".tmp")
    clean = {k: v for k, v in data.items() if k != "_migrated"}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_selected_image_path(project_dir: Path, category: str, name: str, data: dict) -> Path | None:
    asset = data.get("assets", {}).get(category, {}).get(name, {})
    if asset.get("status") == "completed" and asset.get("result_url"):
        return project_dir / asset["result_url"]
    return None


def _meta_dir(project_dir: Path, category: str, name: str) -> Path:
    return project_dir / category / name


def get_meta(project_dir: Path, category: str, name: str) -> dict | None:
    meta_path = _meta_dir(project_dir, category, name) / "meta.json"
    if not meta_path.exists():
        return None
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def write_meta(project_dir: Path, category: str, name: str, data: dict) -> None:
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
    meta = get_meta(project_dir, category, name)
    if not meta or not meta.get("primary_image"):
        return None
    return _meta_dir(project_dir, category, name) / meta["primary_image"]


def get_prompt_optimized(project_dir: Path, category: str, name: str) -> str | None:
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
    global _PROMPT_TEMPLATE_DEFAULTS
    if _PROMPT_TEMPLATE_DEFAULTS is None:
        from api.routes.prompts import CHARACTER_SYSTEM, SCENE_SYSTEM, PROP_SYSTEM, STORYBOARD_SYSTEM, VIDEO_SYSTEM
        _PROMPT_TEMPLATE_DEFAULTS = {
            "character": CHARACTER_SYSTEM,
            "scene": SCENE_SYSTEM,
            "prop": PROP_SYSTEM,
            "storyboard_v1": STORYBOARD_SYSTEM,
            "video_v1": VIDEO_SYSTEM,
        }
    return _PROMPT_TEMPLATE_DEFAULTS


def read_prompt_templates(project_dir: Path) -> dict:
    path = project_dir / "prompt_templates.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return _get_prompt_template_defaults()


def write_prompt_templates(project_dir: Path, data: dict) -> None:
    path = project_dir / "prompt_templates.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_prompt_template_defaults() -> dict:
    return _get_prompt_template_defaults()


# ── 数据迁移（旧格式 → 新格式）──


def migrate_pipeline(data: dict) -> dict:
    """迁移旧 pipeline 数据到新格式：storyboards[ver_key][scene_key]"""
    if data.get("_migrated"):
        return data

    storyboards = data.get("storyboards", {})
    if not storyboards:
        data["_migrated"] = True
        return data

    # 判断是否为旧格式：旧格式的 value 是 dict（场景对象），新格式的 value 是 dict of dict（版本→场景集合）
    # 取第一个值判断：若第一个值包含 episode/script_title/board_versions 之类的场景字段，则是旧格式
    first_val = next(iter(storyboards.values()))
    is_old_format = isinstance(first_val, dict) and (
        "episode" in first_val or "board_versions" in first_val or "script_title" in first_val
    )

    if is_old_format:
        # 旧格式：{scene_key: board_obj} → 新格式：{"v1": {scene_key: scene_obj}}
        new_storyboards = {"v1": {}}
        for scene_key, board in storyboards.items():
            if not isinstance(board, dict):  # 跳过旧格式里的非场景字段（如 selected_board_version: null）
                continue
            new_storyboards["v1"][scene_key] = _migrate_old_board(board)
        data["storyboards"] = new_storyboards

    data["_migrated"] = True
    return data


def _migrate_old_board(board: dict) -> dict:
    """将旧的 board_versions 格式或扁平格式迁移为新的扁平场景格式"""
    # 已是新格式（有 draft_prompt 在顶层，无 board_versions）
    if "board_versions" not in board:
        # 兼容旧字段名 board_status → status
        if "board_status" in board and "status" not in board:
            board["status"] = board.pop("board_status")
        board.setdefault("draft_prompt", "")
        board.setdefault("status", "needed")
        board.setdefault("board_task_id", None)
        board.setdefault("video_parts", [])
        return board

    # 有 board_versions：取第一个版本的数据作为迁移结果
    bv = (board.get("board_versions") or [{}])[0]
    result = {k: v for k, v in board.items() if k not in (
        "board_versions", "selected_board_version", "dependency_stale", "stale_reasons"
    )}
    result["draft_prompt"] = bv.get("draft_prompt", "")
    result["status"] = bv.get("status", "needed")
    result["board_task_id"] = bv.get("board_task_id", None)
    result["video_parts"] = _migrate_video_parts(bv.get("video_parts", []))
    return result


def _migrate_video_parts(video_parts: list) -> list:
    migrated = []
    for vp in video_parts:
        clean = {k: v for k, v in vp.items() if k not in (
            "video_versions", "selected_video_version",
            "dependency_stale", "stale_reasons",
        )}
        migrated.append(clean)
    return migrated
