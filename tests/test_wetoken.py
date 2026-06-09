import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.wetoken import submit_video_task, poll_task, WetokenError


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


def test_submit_quota_error_is_classified():
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 402
    mock_resp.json.return_value = {"error": {"message": "quota exceeded"}}
    mock_resp.text = "quota exceeded"

    with patch("api.wetoken.httpx.post", return_value=mock_resp):
        with pytest.raises(WetokenError, match="额度不足"):
            submit_video_task(
                api_key="test_key",
                prompt="测试视频提示词",
                image_paths=[],
            )


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
