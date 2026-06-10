"""测试 pipeline 数据迁移：旧格式 {scene_key: board_obj} → 新格式 {"v1": {scene_key: scene_obj}}"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.pipeline import migrate_pipeline, _migrate_old_board


# ── _migrate_old_board 单元测试 ──

def test_migrate_old_board_with_board_versions():
    """有 board_versions 时取第一个版本的数据"""
    board = {
        "episode": 1,
        "script_title": "场景A",
        "characters_in_scene": ["角色A"],
        "scene_location": "客厅",
        "board_versions": [{"draft_prompt": "一张图", "status": "completed", "board_task_id": "tid1"}],
        "selected_board_version": None,
    }
    result = _migrate_old_board(board)
    assert result["status"] == "completed"
    assert result["draft_prompt"] == "一张图"
    assert result["board_task_id"] == "tid1"
    assert "board_versions" not in result
    assert "selected_board_version" not in result


def test_migrate_old_board_with_empty_board_versions():
    """board_versions 为空列表时不崩溃，status 默认 needed"""
    board = {
        "episode": 1,
        "script_title": "场景B",
        "characters_in_scene": [],
        "board_versions": [],          # ← 触发之前 bug 的场景
        "selected_board_version": None,
    }
    result = _migrate_old_board(board)
    assert result["status"] == "needed"
    assert result["draft_prompt"] == ""
    assert result["board_task_id"] is None
    assert "board_versions" not in result


def test_migrate_old_board_without_board_versions():
    """没有 board_versions 字段（半迁移状态），board_status 字段名兼容"""
    board = {
        "episode": 1,
        "board_status": "submitted",
        "draft_prompt": "已有提示词",
        "video_parts": [],
    }
    result = _migrate_old_board(board)
    assert result["status"] == "submitted"
    assert "board_status" not in result


def test_migrate_old_board_already_new_format():
    """已是新格式（有 status 在顶层，无 board_versions），直接返回"""
    board = {
        "episode": 1,
        "status": "needed",
        "draft_prompt": "",
        "video_parts": [],
    }
    result = _migrate_old_board(board)
    assert result["status"] == "needed"
    assert result["draft_prompt"] == ""


# ── migrate_pipeline 集成测试 ──

def _old_scene(title="场景", bv=None):
    """构造一个旧格式 scene_obj"""
    return {
        "episode": 1,
        "script_title": title,
        "characters_in_scene": [],
        "scene_location": "",
        "script_segment": "",
        "board_versions": bv if bv is not None else [],
        "selected_board_version": None,
    }


def test_migrate_pipeline_old_format():
    """旧格式正确迁移为 {v1: {scene_key: scene_obj}}"""
    data = {
        "project": "test",
        "storyboards": {
            "s01_01": _old_scene("A", [{"draft_prompt": "p", "status": "needed", "board_task_id": None}]),
            "s01_02": _old_scene("B", []),   # 空 board_versions
        },
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    sb = result["storyboards"]
    assert list(sb.keys()) == ["v1"]
    assert set(sb["v1"].keys()) == {"s01_01", "s01_02"}
    assert sb["v1"]["s01_01"]["status"] == "needed"
    assert sb["v1"]["s01_02"]["status"] == "needed"   # 空 board_versions → needed


def test_migrate_pipeline_skips_null_top_level_key():
    """旧格式中顶层的 selected_board_version: null 不被迁入 v1"""
    data = {
        "project": "test",
        "storyboards": {
            "s01_01": _old_scene("A"),
            "selected_board_version": None,  # ← 旧格式污染字段
        },
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    v1 = result["storyboards"]["v1"]
    assert "selected_board_version" not in v1
    assert "s01_01" in v1


def test_migrate_pipeline_new_format_is_noop():
    """新格式不重复迁移"""
    data = {
        "project": "test",
        "storyboards": {
            "v1": {"s01_01": {"status": "needed", "draft_prompt": "", "video_parts": []}}
        },
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    assert result["storyboards"]["v1"]["s01_01"]["status"] == "needed"
    # 幂等
    result2 = migrate_pipeline(result)
    assert result2 is result


def test_migrate_pipeline_sets_migrated_flag():
    """迁移后设置 _migrated 标记"""
    data = {
        "project": "test",
        "storyboards": {"s01_01": _old_scene()},
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    assert result["_migrated"] is True


def test_write_pipeline_strips_migrated_flag(tmp_path):
    """write_pipeline 不持久化 _migrated 标记；read_pipeline 重新加回"""
    from api.pipeline import write_pipeline, read_pipeline

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    data = {
        "project": "test",
        "_migrated": True,
        "storyboards": {"v1": {}},
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    write_pipeline(project_dir, data)
    raw = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "_migrated" not in raw

    result = read_pipeline(project_dir)
    assert result["_migrated"] is True
