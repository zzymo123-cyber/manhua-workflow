import base64
import httpx
import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.vidu import submit_image_task, ViduError, _img_to_data_uri


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


def test_submit_image_task_uses_long_timeout_for_reference_uploads():
    mock_resp = _mock_response({"task_id": "with_timeout"})
    with patch("api.vidu._request", return_value=mock_resp) as request:
        submit_image_task(
            api_key="test_key",
            prompt="故事板提示词",
            image_paths=["https://example.com/ref.png"],
            ratio="16:9",
        )
    timeout = request.call_args.kwargs["timeout"]
    assert timeout.write >= 300
    assert timeout.read >= 300


def test_submit_image_task_retries_transient_disconnect():
    mock_resp = _mock_response({"task_id": "retry_ok"})
    with patch("api.vidu.time.sleep"), \
         patch("api.vidu._request", side_effect=[
             httpx.RemoteProtocolError("Server disconnected without sending a response."),
             mock_resp,
         ]) as request:
        result = submit_image_task(
            api_key="test_key",
            prompt="测试提示词",
            image_paths=[],
            ratio="16:9",
        )

    assert result["task_id"] == "retry_ok"
    assert request.call_count == 2


def test_local_reference_image_is_compressed_before_upload(tmp_path):
    image_path = tmp_path / "large.png"
    Image.new("RGB", (2400, 1600), color=(120, 80, 40)).save(image_path)

    data_uri = _img_to_data_uri(str(image_path))

    assert data_uri.startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(data_uri.split(",", 1)[1])
    assert len(payload) < image_path.stat().st_size


def test_submit_no_task_id_raises():
    mock_resp = _mock_response({"data": []})
    with patch("api.vidu._request", return_value=mock_resp):
        with pytest.raises(ViduError):
            submit_image_task(api_key="test_key", prompt="test", image_paths=[])
