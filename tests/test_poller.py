import asyncio, json, pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.poller import _process_submitted_tasks


async def _write_downloaded_file(_url, dest):
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"image")


def _make_pipeline_with_submitted_character():
    """构造含 submitted 角色的 pipeline 数据（扁平资产格式）"""
    return {
        "project": "测试项目",
        "_migrated": True,
        "assets": {
            "characters": {
                "婉瑜": {
                    "seed": "描述",
                    "draft_prompt": "提示词",
                    "status": "submitted",
                    "task_id": "vidu_abc",
                    "result_url": None,
                }
            },
            "scenes": {},
            "props": {},
        },
        "storyboards": {}
    }


def _make_pipeline_with_submitted_storyboard():
    """构造含 submitted 故事板版本的 pipeline 数据"""
    return {
        "project": "测试项目",
        "_migrated": True,
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "s01_01": {
                "episode": 1, "scene_num": 1,
                "script_title": "第1集·场景1·卧室",
                "characters_in_scene": [],
                "scene_location": "",
                "script_segment": "",
                "dependency_stale": False, "stale_reasons": [],
                "selected_board_version": None,
                "board_versions": [{
                    "id": 0,
                    "draft_prompt": "故事板提示词",
                    "status": "submitted",
                    "board_task_id": "vidu_board_1",
                    "template_variant": "default",
                    "video_parts": [],
                }],
            }
        }
    }


def _make_pipeline_with_submitted_video():
    """构造含 submitted 视频分段的 pipeline 数据"""
    return {
        "project": "测试项目",
        "_migrated": True,
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "s01_01": {
                "episode": 1, "scene_num": 1,
                "script_title": "第1集·场景1·卧室",
                "characters_in_scene": [],
                "scene_location": "",
                "script_segment": "",
                "dependency_stale": False, "stale_reasons": [],
                "selected_board_version": 0,
                "board_versions": [{
                    "id": 0,
                    "draft_prompt": "故事板提示词",
                    "status": "completed",
                    "board_task_id": None,
                    "template_variant": "default",
                    "video_parts": [{
                        "part": 1,
                        "draft_prompt": "视频提示词",
                        "prompt": "视频提示词",
                        "duration": 10,
                        "video_status": "submitted",
                        "video_task_id": "wt_123",
                        "video_url": None,
                        "local_path": None,
                    }],
                }],
            }
        }
    }


def _new_scene(status="needed", board_task_id=None, video_parts=None):
    return {
        "episode": 1,
        "scene_num": 1,
        "script_title": "第1集·场景1·客厅",
        "characters_in_scene": ["阿明"],
        "scene_location": "客厅",
        "script_segment": "**阿明**：走。",
        "draft_prompt": "故事板提示词",
        "status": status,
        "board_task_id": board_task_id,
        "video_parts": video_parts or [],
    }


@pytest.mark.asyncio
async def test_vidu_submitted_task_becomes_completed(tmp_path):
    """Vidu submitted 扁平资产轮询后变 completed"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)

    pipeline = _make_pipeline_with_submitted_character()
    pipeline_path = project_dir / "pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/img.png", "error": None}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image_async", new_callable=AsyncMock, side_effect=_write_downloaded_file):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads(pipeline_path.read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "completed"


@pytest.mark.asyncio
async def test_completed_asset_with_missing_file_is_downloaded_again(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    pipeline = _make_pipeline_with_submitted_character()
    asset = pipeline["assets"]["characters"]["婉瑜"]
    asset["status"] = "completed"
    asset["result_url"] = "characters/婉瑜/婉瑜.png"
    pipeline["updated_at"] = "2099-01-01T00:00:00"
    pipeline_path = project_dir / "pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/img.png", "error": None}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image_async", new_callable=AsyncMock, side_effect=_write_downloaded_file):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads(pipeline_path.read_text(encoding="utf-8"))
    asset = updated["assets"]["characters"]["婉瑜"]
    assert asset["status"] == "completed"
    assert (project_dir / "characters" / "婉瑜" / "婉瑜.png").exists()


@pytest.mark.asyncio
async def test_vidu_pending_task_records_last_check(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = _make_pipeline_with_submitted_character()
    pipeline["updated_at"] = "2099-01-01T00:00:00"
    pipeline_path = project_dir / "pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "pending", "image_url": None, "error": None}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads(pipeline_path.read_text(encoding="utf-8"))
    asset = updated["assets"]["characters"]["婉瑜"]
    assert asset["status"] == "submitted"
    assert asset["submitted_at"] == "2099-01-01T00:00:00"
    assert asset["last_checked_at"]
    assert asset["status_message"] == "服务端处理中，等待生成结果"


@pytest.mark.asyncio
async def test_new_storyboard_version_submitted_becomes_completed(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    pipeline = {
        "project": "测试项目",
        "_migrated": True,
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboard_route": "v1",
        "storyboards": {
            "v1": {"s01_01": _new_scene(status="submitted", board_task_id="vidu_v1")},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/board.png", "error": None}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image_async", new_callable=AsyncMock, side_effect=_write_downloaded_file):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["storyboards"]["v1"]["s01_01"]["status"] == "completed"


@pytest.mark.asyncio
async def test_new_storyboard_version_video_becomes_completed(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    video_part = {
        "part": 1,
        "draft_prompt": "视频提示词",
        "prompt": "视频提示词",
        "duration": 10,
        "video_status": "submitted",
        "video_task_id": "wetoken_v2",
        "video_url": None,
        "local_path": None,
    }
    pipeline = {
        "project": "测试项目",
        "_migrated": True,
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboard_route": "v2",
        "storyboards": {
            "v2": {"s01_01": _new_scene(status="completed", video_parts=[video_part])},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "completed", "video_url": "https://example.com/video.mp4", "error": None}

    with patch("api.poller.wetoken.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result), \
         patch("api.poller.wetoken.download_video_async", new_callable=AsyncMock):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    vp = updated["storyboards"]["v2"]["s01_01"]["video_parts"][0]
    assert vp["video_status"] == "completed"
    assert vp["video_url"] == "https://example.com/video.mp4"


@pytest.mark.asyncio
async def test_vidu_failed_task_becomes_failed(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)

    pipeline = _make_pipeline_with_submitted_character()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "failed", "image_url": None, "error": "TIMEOUT"}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "failed"
    assert updated["assets"]["characters"]["婉瑜"]["error"] == "TIMEOUT"


@pytest.mark.asyncio
async def test_board_version_submitted_becomes_completed(tmp_path):
    """故事板版本 submitted 轮询后变 completed"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "storyboards" / "s01_01").mkdir(parents=True)

    pipeline = _make_pipeline_with_submitted_storyboard()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/board.png", "error": None}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image_async", new_callable=AsyncMock, side_effect=_write_downloaded_file):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["storyboards"]["s01_01"]["board_versions"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_video_submitted_becomes_completed(tmp_path):
    """视频 submitted 轮询后变 completed"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    pipeline = _make_pipeline_with_submitted_video()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "completed", "video_url": "https://example.com/video.mp4", "error": None}

    with patch("api.poller.wetoken.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result), \
         patch("api.poller.wetoken.download_video_async", new_callable=AsyncMock):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    vp = updated["storyboards"]["s01_01"]["board_versions"][0]["video_parts"][0]
    assert vp["video_status"] == "completed"
    assert vp["video_url"] == "https://example.com/video.mp4"


@pytest.mark.asyncio
async def test_props_failed_task_includes_error(tmp_path):
    """道具失败时包含 error 字段（修复原有 bug）"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    pipeline = {
        "project": "测试项目", "_migrated": True,
        "assets": {
            "characters": {}, "scenes": {},
            "props": {"玉佩": {"seed": "描述", "draft_prompt": "提示词", "status": "submitted", "task_id": "vidu_prop", "result_url": None}},
        },
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "failed", "image_url": None, "error": "CONTENT_MOD"}

    with patch("api.poller.vidu.poll_task_async", new_callable=AsyncMock, return_value=mock_poll_result):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["props"]["玉佩"]["status"] == "failed"
    assert updated["assets"]["props"]["玉佩"]["error"] == "CONTENT_MOD"
