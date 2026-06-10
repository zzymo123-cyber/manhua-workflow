import json
import os
import re
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
        from api.routes.prompts import (
            CHARACTER_SYSTEM,
            SCENE_SYSTEM,
            PROP_SYSTEM,
            STORYBOARD_SYSTEM,
            STORYBOARD_V2_SYSTEM,
            VIDEO_SYSTEM,
            VIDEO_V2_SYSTEM,
        )
        _PROMPT_TEMPLATE_DEFAULTS = {
            "character": CHARACTER_SYSTEM,
            "scene": SCENE_SYSTEM,
            "prop": PROP_SYSTEM,
            "storyboard_v1": STORYBOARD_SYSTEM,
            "storyboard_v2": STORYBOARD_V2_SYSTEM,
            "video_v1": VIDEO_SYSTEM,
            "video_v2": VIDEO_V2_SYSTEM,
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
        _ensure_versioned_storyboard_boards(data)
        _ensure_single_storyboard_route(data)
        _ensure_storyboard_asset_refs(data)
        return data

    storyboards = data.get("storyboards", {})
    if not storyboards:
        _ensure_storyboard_asset_refs(data)
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

    _ensure_versioned_storyboard_boards(data)
    _ensure_single_storyboard_route(data)
    _ensure_storyboard_asset_refs(data)
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


def _ensure_versioned_storyboard_boards(data: dict) -> None:
    """补齐 storyboards[ver][scene].boards[]，兼容旧的场景级版本化项目。"""
    storyboards = data.get("storyboards", {})
    if not isinstance(storyboards, dict) or not storyboards:
        return

    first_val = next(iter(storyboards.values()))
    is_old_format = isinstance(first_val, dict) and (
        "episode" in first_val or "board_versions" in first_val or "script_title" in first_val
    )
    if is_old_format:
        return

    from api import parser

    for board_version, scenes in storyboards.items():
        if not isinstance(scenes, dict):
            continue
        for scene_key, scene in scenes.items():
            if not isinstance(scene, dict):
                continue
            boards = scene.get("boards")
            if isinstance(boards, list):
                for board in boards:
                    _clear_seed_storyboard_prompt(board)
                    _normalize_storyboard_status(board)
                _sync_scene_from_first_board(scene)
                continue

            if board_version == "v2":
                planned = parser._make_v2_boards(scene_key, scene)
                layout = "director_sheet_15s"
            else:
                planned = parser._make_v1_boards(scene_key, scene, board_version)
                layout = "nine_grid"

            if not planned:
                continue

            total_pages = len(planned)
            for board in planned:
                board["total_pages"] = total_pages

            first = planned[0]
            if scene.get("draft_prompt"):
                first["draft_prompt"] = scene["draft_prompt"]
            if scene.get("status") and (scene.get("status") != "needed" or scene.get("draft_prompt")):
                first["status"] = scene["status"]
            if first.get("draft_prompt") and first.get("status") == "needed":
                first["status"] = "drafted"
            if scene.get("board_task_id"):
                first["board_task_id"] = scene["board_task_id"]
            if scene.get("video_parts"):
                first["video_parts"] = _migrate_video_parts(scene.get("video_parts", []))
            if scene.get("result_url"):
                first["result_url"] = scene["result_url"]

            scene["source_scene_key"] = scene.get("source_scene_key", scene_key)
            scene["layout"] = scene.get("layout", layout)
            scene["boards"] = planned
            _sync_scene_from_first_board(scene)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _infer_props_for_board(data: dict, scene: dict, board: dict) -> list[str]:
    text = "\n".join(str(v) for v in (
        board.get("covered_text", ""),
        board.get("prompt_seed", ""),
        board.get("draft_prompt", ""),
        json.dumps(board.get("plan", {}), ensure_ascii=False),
    ) if v)
    generic_tokens = {"邮件", "照片", "小乐", "婉瑜", "江宁", "女士", "先生"}
    props = []
    for name in ((data.get("assets") or {}).get("props") or {}):
        clean_name = name or ""
        tokens = [t for t in re.split(r"[（()）+、/·\\s]+", clean_name) if len(t) >= 2]
        bigrams = [clean_name[i:i + 2] for i in range(max(0, len(clean_name) - 1))]
        keyword_hit = any(t not in generic_tokens and t in text for t in tokens + bigrams)
        if name and (name in text or any(t in text for t in tokens) or keyword_hit):
            props.append(name)
    return props


def _ensure_storyboard_asset_refs(data: dict) -> None:
    storyboards = data.get("storyboards")
    if not isinstance(storyboards, dict):
        return
    for scenes in storyboards.values():
        if not isinstance(scenes, dict):
            continue
        for scene in scenes.values():
            if not isinstance(scene, dict):
                continue
            boards = scene.get("boards") if isinstance(scene.get("boards"), list) else [scene]
            for board in boards:
                if not isinstance(board, dict):
                    continue
                refs = board.get("asset_refs") if isinstance(board.get("asset_refs"), dict) else {}
                characters = _as_list(board.get("characters") or refs.get("characters") or scene.get("characters_in_scene"))
                scene_name = board.get("scene_location") or refs.get("scene") or scene.get("scene_location") or ""
                props = _as_list(board.get("props") or refs.get("props")) or _infer_props_for_board(data, scene, board)
                board["characters"] = characters
                board["scene_location"] = scene_name
                board["props"] = props
                board["asset_refs"] = {"characters": characters, "scene": scene_name, "props": props}


def _route_score(scenes: dict) -> int:
    score = 0
    for scene in scenes.values():
        if not isinstance(scene, dict):
            continue
        boards = scene.get("boards") if isinstance(scene.get("boards"), list) else [scene]
        for board in boards:
            if not isinstance(board, dict):
                continue
            if board.get("status") in ("drafted", "submitted", "completed", "failed"):
                score += 1
            if board.get("draft_prompt") or board.get("board_task_id") or board.get("result_url") or board.get("video_parts"):
                score += 1
    return score


def _ensure_single_storyboard_route(data: dict) -> None:
    storyboards = data.get("storyboards")
    if not isinstance(storyboards, dict) or not storyboards:
        data.setdefault("storyboard_route", None)
        return
    explicit_route = data.get("storyboard_route")
    if explicit_route in storyboards:
        if len(storyboards) > 1:
            archived = {version: scenes for version, scenes in storyboards.items() if version != explicit_route}
            if archived:
                data.setdefault("archived_storyboard_routes", []).append({
                    "reason": "single_route_migration",
                    "routes": archived,
                })
            data["storyboards"] = {explicit_route: storyboards[explicit_route]}
        return
    if len(storyboards) == 1:
        data["storyboard_route"] = next(iter(storyboards))
        return

    scores = {version: _route_score(scenes) for version, scenes in storyboards.items() if isinstance(scenes, dict)}
    chosen = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else None
    data.setdefault("archived_storyboard_routes", [])
    if chosen:
        archived = {version: scenes for version, scenes in storyboards.items() if version != chosen}
        if archived:
            data["archived_storyboard_routes"].append({
                "reason": "single_route_migration",
                "routes": archived,
            })
        data["storyboard_route"] = chosen
        data["storyboards"] = {chosen: storyboards[chosen]}
    else:
        data["archived_storyboard_routes"].append({
            "reason": "unselected_default_route_migration",
            "routes": storyboards,
        })
        data["storyboard_route"] = None
        data["storyboards"] = {}


def _is_seed_storyboard_prompt(prompt: str) -> bool:
    if not prompt:
        return False
    return (
        prompt.startswith("分镜板ID：")
        and "本页剧情：" in prompt
        and ("版本：v2 专业影视分镜板" in prompt or "版本：v1 九宫格故事板" in prompt)
    )


def _clear_seed_storyboard_prompt(board: dict) -> None:
    prompt = board.get("draft_prompt", "")
    status = board.get("status", "needed")
    if status not in ("needed", "drafted") or not _is_seed_storyboard_prompt(prompt):
        return
    board.setdefault("prompt_seed", prompt)
    board["draft_prompt"] = ""
    board.setdefault("plan", {})
    board["status"] = "planned"


def _normalize_storyboard_status(board: dict) -> None:
    board.setdefault("draft_prompt", "")
    if "prompt_seed" not in board and board.get("draft_prompt"):
        board["prompt_seed"] = board.get("draft_prompt", "")
    board.setdefault("plan", {})
    if (
        board.get("status") == "needed"
        and board.get("prompt_seed")
        and not board.get("draft_prompt")
        and not board.get("board_task_id")
        and not board.get("result_url")
    ):
        board["status"] = "planned"


def _sync_scene_from_first_board(scene: dict) -> None:
    boards = scene.get("boards")
    if not isinstance(boards, list) or not boards:
        return
    first = boards[0]
    scene["draft_prompt"] = first.get("draft_prompt", "")
    scene["status"] = first.get("status", "needed")
    scene["board_task_id"] = first.get("board_task_id")
    scene["video_parts"] = first.get("video_parts", [])
