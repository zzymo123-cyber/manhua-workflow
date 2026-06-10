import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.vidu import submit_image_task, ViduError


def _mock_response(json_data, status_code=200, is_success=True):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.is_success = is_success
    mock_resp.json.return_value = json_data
    mock_resp.text = str(json_data)
    return mock_resp


def test_submit_image_task_returns_task_id():
    mock_resp = _mock_response({"task_id": "abc123"})
    with patch("api.vidu._request", return_value=mock_resp):
        result = submit_image_task(
            api_key="test_key",
            prompt="测试提示词",
            image_paths=[],
            ratio="3:4",
        )
    assert result["task_id"] == "abc123"


def test_submit_image_task_with_ref_images():
    mock_resp = _mock_response({"task_id": "def456"})
    with patch("api.vidu._request", return_value=mock_resp):
        result = submit_image_task(
            api_key="test_key",
            prompt="编辑提示词",
            image_paths=["https://example.com/ref.png"],
            ratio="16:9",
        )
    assert result["task_id"] == "def456"


def test_submit_no_task_id_raises():
    mock_resp = _mock_response({"data": []})
    with patch("api.vidu._request", return_value=mock_resp):
        with pytest.raises(ViduError):
            submit_image_task(api_key="test_key", prompt="test", image_paths=[])
