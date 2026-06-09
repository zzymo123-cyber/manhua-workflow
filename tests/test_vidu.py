import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.vidu import submit_image_task, ViduError


def _mock_response(json_data, is_success=True, text=""):
    mock_resp = MagicMock()
    mock_resp.is_success = is_success
    mock_resp.status_code = 200 if is_success else 400
    mock_resp.text = text
    mock_resp.json.return_value = json_data
    return mock_resp


def test_submit_text_to_image():
    mock_resp = _mock_response({"task_id": "abc123"})

    with patch("api.vidu._request", return_value=mock_resp) as request:
        result = submit_image_task(
            api_key="test_key",
            prompt="测试提示词",
            image_paths=[],
            ratio="3:4",
        )
    assert result["task_id"] == "abc123"
    assert request.call_args.args[0] == "POST"
    assert request.call_args.args[1].endswith("/ent/v2/reference2image")


def test_submit_with_reference_image_uses_same_async_endpoint():
    mock_resp = _mock_response({"task_id": "def456"})

    with patch("api.vidu._request", return_value=mock_resp) as request:
        result = submit_image_task(
            api_key="test_key",
            prompt="编辑提示词",
            image_paths=["https://example.com/ref.png"],
            ratio="16:9",
        )
    assert result["task_id"] == "def456"
    body = request.call_args.kwargs["json"]
    assert body["images"] == ["https://example.com/ref.png"]
    assert request.call_args.args[1].endswith("/ent/v2/reference2image")


def test_submit_without_task_id_raises():
    mock_resp = _mock_response({})

    with patch("api.vidu._request", return_value=mock_resp):
        with pytest.raises(ViduError, match="API 未返回 task_id"):
            submit_image_task(api_key="test_key", prompt="test", image_paths=[])


def test_submit_auth_error_is_classified():
    mock_resp = _mock_response({"message": "invalid api key"}, is_success=False)
    mock_resp.status_code = 401

    with patch("api.vidu._request", return_value=mock_resp):
        with pytest.raises(ViduError, match="认证失败"):
            submit_image_task(api_key="bad_key", prompt="test", image_paths=[])
