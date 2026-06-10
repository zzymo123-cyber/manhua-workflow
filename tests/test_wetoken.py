import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.wetoken import submit_video_task, poll_task, poll_asset_status, WetokenError


def test_submit_returns_task_id():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "wetoken_123"}
    mock_resp.raise_for_status = MagicMock()

    with patch("api.wetoken.httpx.post", return_value=mock_resp):
        task_id = submit_video_task(
            api_key="test_key",
            prompt="测试视频提示词",
            image_paths=[],
            duration=10,
            ratio="16:9",
        )
    assert task_id == "wetoken_123"


def test_poll_task_succeeded():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "succeeded",
        "content": {"video_url": "https://example.com/video.mp4"}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("api.wetoken.httpx.get", return_value=mock_resp):
        result = poll_task("test_key", "wetoken_123")
    assert result["status"] == "completed"
    assert result["video_url"] == "https://example.com/video.mp4"


def test_poll_task_running():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "running", "content": {}}
    mock_resp.raise_for_status = MagicMock()

    with patch("api.wetoken.httpx.get", return_value=mock_resp):
        result = poll_task("test_key", "wetoken_123")
    assert result["status"] == "pending"


def test_poll_task_failed():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "failed",
        "error": {"message": "quota exceeded"}
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("api.wetoken.httpx.get", return_value=mock_resp):
        result = poll_task("test_key", "wetoken_123")
    assert result["status"] == "failed"
    assert "quota" in result["error"]


def test_poll_asset_status_continues_after_read_timeout():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"Result": {"Status": "Active"}}

    with patch("api.wetoken.httpx.get", side_effect=[httpx.ReadTimeout("slow"), mock_resp]), \
         patch("api.wetoken.time.sleep"):
        assert poll_asset_status("test_key", "asset_123", timeout=10) == "Active"
