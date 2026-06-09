import json
import pytest
from unittest.mock import patch

from api.poller import _process_submitted_tasks


@pytest.mark.asyncio
async def test_vidu_submitted_task_becomes_completed(tmp_path):
    """Vidu submitted 任务轮询后变 completed"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)

    pipeline = {
        "project": "测试项目",
        "assets": {
            "characters": {
                "婉瑜": {"status": "submitted", "task_id": "vidu_abc", "seed": "描述"}
            }
        },
        "storyboards": {}
    }
    pipeline_path = project_dir / "pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/img.png", "error": None}

    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image"):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads(pipeline_path.read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "completed"


@pytest.mark.asyncio
async def test_vidu_failed_task_becomes_failed(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)

    pipeline = {
        "project": "测试项目",
        "assets": {
            "characters": {
                "婉瑜": {"status": "submitted", "task_id": "vidu_abc", "seed": "描述"}
            }
        },
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "failed", "image_url": None, "error": "TIMEOUT"}

    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "failed"
    assert updated["assets"]["characters"]["婉瑜"]["error"] == "TIMEOUT"


@pytest.mark.asyncio
async def test_vidu_poll_exception_keeps_task_submitted(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {
            "characters": {
                "婉瑜": {"status": "submitted", "task_id": "vidu_abc", "seed": "描述"}
            }
        },
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    with patch("api.poller.vidu.poll_task", side_effect=Exception("网络失败")):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    item = updated["assets"]["characters"]["婉瑜"]
    assert item["status"] == "submitted"
    assert "轮询失败" in item["error"]
    assert "网络失败" in item["error"]


@pytest.mark.asyncio
async def test_vidu_download_exception_marks_task_failed(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline = {
        "project": "测试项目",
        "assets": {
            "characters": {
                "婉瑜": {"status": "submitted", "task_id": "vidu_abc", "seed": "描述"}
            }
        },
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/img.png", "error": None}
    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image", side_effect=Exception("下载失败")):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    item = updated["assets"]["characters"]["婉瑜"]
    assert item["status"] == "failed"
    assert "下载或写入失败" in item["error"]
    assert "下载失败" in item["error"]


@pytest.mark.asyncio
async def test_storyboard_completed_writes_primary_image_meta(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {"board_status": "submitted", "board_task_id": "vidu_board"}
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/board.png", "error": None}

    def fake_download(_url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-board")

    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image", side_effect=fake_download):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["storyboards"]["E01-S1"]["board_status"] == "completed"

    meta = json.loads((project_dir / "storyboards" / "E01-S1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["primary_image"] == "E01-S1.png"
    assert meta["category"] == "storyboards"
    assert (project_dir / "storyboards" / "E01-S1" / "E01-S1.png").exists()


@pytest.mark.asyncio
async def test_v1_storyboard_poll_syncs_board_version_status(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {
                "board_status": "submitted",
                "board_task_id": "vidu_board",
                "board_versions": {
                    "v1": {"board_status": "submitted", "board_task_id": "vidu_board"},
                    "v2": {"pages": []},
                },
            }
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/board.png", "error": None}

    def fake_download(_url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-board")

    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image", side_effect=fake_download):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    board = updated["storyboards"]["E01-S1"]
    assert board["board_status"] == "completed"
    assert board["board_versions"]["v1"]["board_status"] == "completed"


@pytest.mark.asyncio
async def test_v2_storyboard_page_completed_writes_page_image(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {
                "board_status": "needed",
                "board_versions": {
                    "v1": {"board_status": "needed"},
                    "v2": {"pages": [
                        {"page": 1, "board_status": "needed"},
                        {"page": 2, "board_status": "submitted", "board_task_id": "vidu_v2_page2"},
                    ]},
                },
            }
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "success", "image_url": "https://example.com/board.png", "error": None}

    def fake_download(_url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-v2-board")

    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image", side_effect=fake_download):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    board = updated["storyboards"]["E01-S1"]
    assert board["board_status"] == "needed"
    assert board["board_versions"]["v2"]["pages"][1]["board_status"] == "completed"
    assert (project_dir / "storyboards" / "E01-S1" / "v2_p2.png").exists()


@pytest.mark.asyncio
async def test_wetoken_download_exception_records_download_error(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {
                "video_parts": [
                    {"part": 1, "video_status": "submitted", "video_task_id": "wetoken_abc"}
                ]
            }
        }
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "completed", "video_url": "https://example.com/video.mp4", "error": None}
    with patch("api.poller.wetoken.poll_task", return_value=mock_poll_result), \
         patch("api.poller.wetoken.download_video", side_effect=Exception("下载失败")):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    part = updated["storyboards"]["E01-S1"]["video_parts"][0]
    assert part["video_status"] == "completed"
    assert part["video_url"] == "https://example.com/video.mp4"
    assert "本地下载失败" in part["video_download_error"]


@pytest.mark.asyncio
async def test_v1_video_poll_syncs_board_version_parts(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {
                "video_parts": [
                    {"part": 1, "video_status": "submitted", "video_task_id": "wetoken_abc"}
                ],
                "board_versions": {
                    "v1": {
                        "video_parts": [
                            {"part": 1, "video_status": "submitted", "video_task_id": "wetoken_abc"}
                        ],
                    },
                    "v2": {"pages": []},
                },
            }
        }
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "completed", "video_url": "https://example.com/video.mp4", "error": None}

    def fake_download(_url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-video")

    with patch("api.poller.wetoken.poll_task", return_value=mock_poll_result), \
         patch("api.poller.wetoken.download_video", side_effect=fake_download):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    board = updated["storyboards"]["E01-S1"]
    assert board["video_parts"][0]["video_status"] == "completed"
    assert board["board_versions"]["v1"]["video_parts"][0]["video_status"] == "completed"


@pytest.mark.asyncio
async def test_v2_video_page_completed_downloads_to_page_part(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {
                "board_versions": {
                    "v2": {"pages": [
                        {"page": 1, "video_parts": []},
                        {"page": 2, "video_parts": [
                            {"part": 1, "video_status": "submitted", "video_task_id": "video_v2"}
                        ]},
                    ]}
                }
            }
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False), encoding="utf-8")

    mock_poll_result = {"status": "completed", "video_url": "https://example.com/video.mp4", "error": None}

    def fake_download(_url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-video")

    with patch("api.poller.wetoken.poll_task", return_value=mock_poll_result), \
         patch("api.poller.wetoken.download_video", side_effect=fake_download):
        await _process_submitted_tasks(project_dir, "test_vidu_key", "test_wetoken_key")

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    part = updated["storyboards"]["E01-S1"]["board_versions"]["v2"]["pages"][1]["video_parts"][0]
    assert part["video_status"] == "completed"
    assert part["local_path"] == "videos/E01-S1/v2_p2_part1.mp4"
    assert (project_dir / "videos" / "E01-S1" / "v2_p2_part1.mp4").exists()
