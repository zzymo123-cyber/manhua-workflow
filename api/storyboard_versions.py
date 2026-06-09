from pathlib import Path

SUPPORTED_STORYBOARD_MODES = {"v1", "v2", "v3", "v4"}
_OUTPUT_FIELDS = (
    "draft_prompt",
    "board_status",
    "board_task_id",
    "board_error",
    "video_parts",
    "video_duration",
    "video_ratio",
    "shot_plan",
)


class StoryboardVersionError(ValueError):
    """Raised when a storyboard mode/page request cannot be mapped safely."""


def normalize_storyboard_mode(mode: str | None) -> str:
    mode = str(mode or "v1").strip().lower()
    if mode not in SUPPORTED_STORYBOARD_MODES:
        raise StoryboardVersionError("故事板模式必须是 v1、v2、v3 或 v4")
    return mode


def _normalize_page(page: int | None) -> int:
    if page is None:
        return 1
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise StoryboardVersionError("故事板页码必须是正整数")
    return page


def ensure_board_versions(board: dict) -> dict:
    versions = board.setdefault("board_versions", {})
    v1 = versions.setdefault("v1", {})
    _ensure_v1_output(board, v1)
    v2 = versions.setdefault("v2", {"pages": []})
    _ensure_v2_outputs(board, v2)
    versions.setdefault("v3", {"outputs": []}).setdefault("outputs", [])
    versions.setdefault("v4", {"outputs": []}).setdefault("outputs", [])
    return versions


def _ensure_v1_output(board: dict, version: dict) -> dict:
    outputs = version.setdefault("outputs", [])
    if outputs:
        output = outputs[0]
    else:
        output = {
            "id": "v1_main",
            "label": "v1 主图",
            "page": 1,
            "draft_prompt": version.get("draft_prompt", board.get("draft_prompt", "")),
            "board_status": version.get("board_status", board.get("board_status", "needed")),
            "board_task_id": version.get("board_task_id", board.get("board_task_id", "")),
            "board_error": version.get("board_error", board.get("board_error", "")),
            "video_parts": version.get("video_parts", board.get("video_parts", [])),
            "shot_plan": version.get("shot_plan", board.get("shot_plan", {})),
        }
        outputs.append(output)
    output.setdefault("id", "v1_main")
    output.setdefault("label", "v1 主图")
    output.setdefault("page", 1)
    output.setdefault("draft_prompt", version.get("draft_prompt", board.get("draft_prompt", "")))
    output.setdefault("board_status", version.get("board_status", board.get("board_status", "needed")))
    output.setdefault("video_parts", version.get("video_parts", board.get("video_parts", [])))
    output.setdefault("shot_plan", version.get("shot_plan", board.get("shot_plan", {})))
    _mirror_output_to_version(version, output)
    return output


def _ensure_v2_outputs(board: dict, version: dict) -> list[dict]:
    pages = version.setdefault("pages", [])
    outputs = version.get("outputs")
    if outputs is None:
        outputs = pages
        version["outputs"] = outputs
    if not outputs and pages:
        outputs.extend(pages)
    if not pages and outputs:
        version["pages"] = outputs
        pages = outputs
    if not outputs:
        outputs.append({
            "id": "v2_p1",
            "label": "v2 P1",
            "page": 1,
            "draft_prompt": "",
            "board_status": board.get("board_status", "needed"),
            "shot_plan": board.get("shot_plan", {}),
            "video_parts": [],
        })
        version["pages"] = outputs
    for output in outputs:
        page = output.get("page") or 1
        output["page"] = page
        output.setdefault("id", f"v2_p{page}")
        output.setdefault("label", f"v2 P{page}")
        output.setdefault("draft_prompt", "")
        output.setdefault("board_status", "needed")
        output.setdefault("video_parts", [])
        output.setdefault("shot_plan", board.get("shot_plan", {}))
    outputs.sort(key=lambda item: item.get("page", 0))
    return outputs


def _mirror_output_to_version(version: dict, output: dict) -> None:
    for field in _OUTPUT_FIELDS:
        if field in output:
            version[field] = output[field]
        else:
            version.pop(field, None)


def sync_legacy_v1_from_output(board: dict) -> None:
    versions = ensure_board_versions(board)
    output = versions["v1"]["outputs"][0]
    for field in _OUTPUT_FIELDS:
        if field in output:
            board[field] = output[field]
        else:
            board.pop(field, None)
    _mirror_output_to_version(versions["v1"], output)


def sync_v1_from_board(board: dict) -> None:
    versions = ensure_board_versions(board)
    output = versions["v1"]["outputs"][0]
    for field in _OUTPUT_FIELDS:
        if field in board:
            output[field] = board[field]
        else:
            output.pop(field, None)
    _mirror_output_to_version(versions["v1"], output)


def storyboard_output_id(mode: str = "v1", page: int | None = None, output_id: str | None = None) -> str:
    mode = normalize_storyboard_mode(mode)
    if output_id:
        return output_id
    if mode == "v1":
        return "v1_main"
    return f"{mode}_p{_normalize_page(page)}"


def get_storyboard_outputs(board: dict, mode: str = "v1") -> list[dict]:
    mode = normalize_storyboard_mode(mode)
    versions = ensure_board_versions(board)
    return versions.setdefault(mode, {"outputs": []}).setdefault("outputs", [])


def get_storyboard_target(
    board: dict,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
) -> dict:
    mode = normalize_storyboard_mode(mode)
    outputs = get_storyboard_outputs(board, mode)
    target_id = storyboard_output_id(mode, page, output_id)
    target = next((item for item in outputs if item.get("id") == target_id), None)
    if target is None and page is not None:
        page_num = _normalize_page(page)
        target = next((item for item in outputs if item.get("page") == page_num), None)
    if target is None:
        if mode == "v1":
            raise StoryboardVersionError("未找到故事板 v1 主图")
        page_text = f" 第 {_normalize_page(page)} 页" if page is not None else ""
        raise StoryboardVersionError(f"未找到故事板 {mode}{page_text} 输出")
    return target


def get_storyboard_status(
    board: dict,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
) -> str:
    return get_storyboard_target(board, mode, page, output_id).get("board_status", "needed")


def set_storyboard_submitted(
    board: dict,
    task_id: str,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
) -> dict:
    mode = normalize_storyboard_mode(mode)
    target = get_storyboard_target(board, mode, page, output_id)
    target["board_status"] = "submitted"
    target["board_task_id"] = task_id
    target.pop("board_error", None)
    if mode == "v1":
        sync_legacy_v1_from_output(board)
    return target


def storyboard_image_relative_path(scene_key: str, mode: str = "v1", page: int | None = None) -> str:
    filename = storyboard_image_filename(scene_key, mode, page)
    return f"storyboards/{scene_key}/{filename}"


def storyboard_image_filename(scene_key: str, mode: str = "v1", page: int | None = None) -> str:
    mode = normalize_storyboard_mode(mode)
    if mode != "v1":
        return f"{mode}_p{page or 1}.png"
    return f"{scene_key}.png"


def storyboard_image_path(project_dir: Path, scene_key: str, mode: str = "v1", page: int | None = None) -> Path:
    return project_dir / storyboard_image_relative_path(scene_key, mode, page)
