import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.vidu import submit_image_task, ViduError


def _mock_client(json_data):
    """创建 mock httpx.Client，其 post 返回指定数据"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_submit_text_to_image():
    mock_client = _mock_client({
        "task_id": "abc123",
        "data": [{"url": "https://example.com/img.png"}]
    })

    with patch("api.vidu.httpx.Client", return_value=mock_client):
        result = submit_image_task(
            api_key="test_key",
            prompt="测试提示词",
            image_paths=[],
            ratio="3:4",
        )
    assert result["task_id"] == "abc123"
    assert result["image_url"] == "https://example.com/img.png"


def test_submit_image_edit():
    mock_client = _mock_client({
        "task_id": "def456",
        "data": [{"url": "https://example.com/edit.png"}]
    })

    with patch("api.vidu.httpx.Client", return_value=mock_client):
        result = submit_image_task(
            api_key="test_key",
            prompt="编辑提示词",
            image_paths=["https://example.com/ref.png"],
            ratio="16:9",
        )
    assert result["task_id"] == "def456"
    assert result["image_url"] == "https://example.com/edit.png"
    # 应该调用 /edits 端点
    call_url = str(mock_client.post.call_args.args[0])
    assert "/edits" in call_url


def test_submit_no_image_url_raises():
    mock_client = _mock_client({"task_id": "abc", "data": []})

    with patch("api.vidu.httpx.Client", return_value=mock_client):
        with pytest.raises(ViduError, match="No image URL"):
            submit_image_task(api_key="test_key", prompt="test", image_paths=[])
