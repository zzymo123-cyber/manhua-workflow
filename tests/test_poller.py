import asyncio, json, pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

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

    mock_poll_result = {"status": "completed", "image_url": "https://example.com/img.png", "error": None}

    with patch("api.poller.vidu.poll_task", return_value=mock_poll_result), \
         patch("api.poller.vidu.download_image") as mock_dl:
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
