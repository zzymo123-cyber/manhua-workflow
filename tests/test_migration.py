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
    assert sb["v1"]["s01_01"]["status"] == "drafted"
    assert sb["v1"]["s01_02"]["status"] == "planned"   # 空 board_versions → planned seed


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
    """版本化场景格式会补齐 boards，且迁移幂等"""
    data = {
        "project": "test",
        "storyboards": {
            "v1": {"s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": [],
                "scene_location": "客厅",
                "script_segment": "测试",
                "status": "needed",
                "draft_prompt": "已有提示词",
                "video_parts": [],
            }}
        },
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    assert result["storyboards"]["v1"]["s01_01"]["status"] == "drafted"
    assert result["storyboards"]["v1"]["s01_01"]["boards"][0]["draft_prompt"] == "已有提示词"
    assert result["storyboards"]["v1"]["s01_01"]["boards"][0]["shot_count"] == 9
    # 幂等
    result2 = migrate_pipeline(result)
    assert result2 is result


def test_migrate_pipeline_plans_v2_boards_for_existing_versioned_scene():
    """旧的场景级 v2 项目加载时补成 15 秒内多张 board"""
    data = {
        "project": "test",
        "storyboards": {
            "v2": {"s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "\n".join([
                    "阿明推门进入。",
                    "**阿明**：第一句对白很长很长。",
                    "他看向桌面。",
                    "**阿明**：第二句对白继续推进。",
                    "手机震动。",
                    "他伸手去拿。",
                    "**阿明**：第三句对白制造悬念。",
                    "门外传来脚步声。",
                    "他回头。",
                    "门把手转动。",
                ]),
                "status": "drafted",
                "draft_prompt": "旧v2提示词",
                "board_task_id": None,
                "video_parts": [],
            }}
        },
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    boards = result["storyboards"]["v2"]["s01_01"]["boards"]
    assert len(boards) > 1
    assert boards[0]["draft_prompt"] == "旧v2提示词"
    assert all(board["layout"] == "director_sheet_15s" for board in boards)
    assert all(board["estimated_duration"] <= 15 for board in boards)


def test_migrate_pipeline_sets_migrated_flag():
    """迁移后设置 _migrated 标记"""
    data = {
        "project": "test",
        "storyboards": {"s01_01": _old_scene()},
        "assets": {"characters": {}, "scenes": {}, "props": {}},
    }
    result = migrate_pipeline(data)
    assert result["_migrated"] is True


def test_migrate_pipeline_clears_seed_storyboard_draft_prompt():
    seed_prompt = (
        "分镜板ID：s01_01_v2_p01\n"
        "本页剧情：\n"
        "△ 测试剧情\n"
        "版本：v2 专业影视分镜板。请生成黑白铅笔线稿/导演分镜稿。"
    )
    data = {
        "project": "test",
        "_migrated": True,
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v2": {
                "s01_01": {
                    "boards": [{
                        "board_id": "s01_01_v2_p01",
                        "layout": "director_sheet_15s",
                        "covered_text": "△ 测试剧情",
                        "draft_prompt": seed_prompt,
                        "status": "drafted",
                        "board_task_id": None,
                        "video_parts": [],
                    }]
                }
            }
        },
    }

    result = migrate_pipeline(data)
    board = result["storyboards"]["v2"]["s01_01"]["boards"][0]
    assert board["prompt_seed"] == seed_prompt
    assert board["draft_prompt"] == ""
    assert board["status"] == "planned"


def test_migrate_pipeline_adds_storyboard_asset_refs():
    data = {
        "project": "test",
        "_migrated": True,
        "assets": {
            "characters": {"婉瑜": {}, "小乐": {}},
            "scenes": {"小乐卧室": {}},
            "props": {"故事书": {}},
        },
        "storyboards": {
            "v2": {
                "s01_01": {
                    "characters_in_scene": ["婉瑜", "小乐"],
                    "scene_location": "小乐卧室",
                    "script_segment": "婉瑜拿起故事书。",
                    "boards": [{
                        "board_id": "s01_01_v2_p01",
                        "covered_text": "婉瑜拿起故事书。",
                        "prompt_seed": "睡前故事",
                        "draft_prompt": "",
                        "status": "planned",
                        "video_parts": [],
                    }],
                }
            }
        },
    }

    result = migrate_pipeline(data)
    board = result["storyboards"]["v2"]["s01_01"]["boards"][0]
    assert board["asset_refs"] == {
        "characters": ["婉瑜", "小乐"],
        "scene": "小乐卧室",
        "props": ["故事书"],
    }
    assert board["characters"] == ["婉瑜", "小乐"]
    assert board["scene_location"] == "小乐卧室"
    assert board["props"] == ["故事书"]


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
