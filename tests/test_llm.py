import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.llm import generate_prompt, chat_with_agent


@pytest.fixture(autouse=True)
def use_idealab_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "idealab")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)


def _mock_anthropic_resp(text: str):
    """构造符合 Anthropic SDK 响应结构的 mock: resp.content[0].text"""
    mock_resp = MagicMock()
    mock_block = MagicMock()
    mock_block.text = text
    mock_resp.content = [mock_block]
    return mock_resp


def _mock_openai_resp(text: str):
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_resp.choices = [mock_choice]
    return mock_resp


def test_generate_prompt_returns_text():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_anthropic_resp("生成的提示词内容")

    with patch("api.llm._get_client", return_value=mock_client):
        result = generate_prompt(
            api_key="test",
            system="你是提示词生成器",
            user_message="生成角色提示词",
        )
    assert result == "生成的提示词内容"


def test_chat_with_agent_returns_reply_and_actions():
    mock_client = MagicMock()
    import json
    response_json = json.dumps({
        "reply": "已修改提示词",
        "actions": [{"action": "update_draft_prompt", "target": "storyboard",
                     "scene_key": "E01-S1", "value": "新提示词"}]
    })
    mock_client.messages.create.return_value = _mock_anthropic_resp(response_json)

    with patch("api.llm._get_client", return_value=mock_client):
        result = chat_with_agent(
            api_key="test",
            messages=[{"role": "user", "content": "修改提示词"}],
            system_prompt="你是助手",
        )
    assert result["reply"] == "已修改提示词"
    assert len(result["actions"]) == 1


def test_chat_returns_empty_actions_on_plain_reply():
    mock_client = MagicMock()
    import json
    response_json = json.dumps({"reply": "当前有3个场景未生成视频", "actions": []})
    mock_client.messages.create.return_value = _mock_anthropic_resp(response_json)

    with patch("api.llm._get_client", return_value=mock_client):
        result = chat_with_agent(
            api_key="test",
            messages=[{"role": "user", "content": "哪些场景还没生成视频？"}],
            system_prompt="你是助手",
        )
    assert result["actions"] == []


def test_generate_prompt_uses_deepseek_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setattr("api.llm._read_settings", lambda: {
        "deepseek_api_key": "ds-key",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_model": "deepseek-v4-flash",
    })
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_resp("DS 生成内容")

    with patch("api.llm._get_deepseek_client", return_value=mock_client) as get_client:
        result = generate_prompt(
            api_key="unused",
            system="系统提示",
            user_message="用户提示",
        )

    assert result == "DS 生成内容"
    get_client.assert_called_once_with("ds-key", "https://api.deepseek.com")
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["messages"][0] == {"role": "system", "content": "系统提示"}
    assert kwargs["messages"][1] == {"role": "user", "content": "用户提示"}


def test_chat_with_agent_uses_deepseek_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ds")
    monkeypatch.setattr("api.llm._read_settings", lambda: {
        "deepseek_api_key": "ds-key",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_model": "deepseek-v4-pro",
    })
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_resp(
        '{"reply":"OK","actions":[{"action":"noop"}]}'
    )

    with patch("api.llm._get_deepseek_client", return_value=mock_client):
        result = chat_with_agent(
            api_key="unused",
            messages=[{"role": "user", "content": "你好"}],
            system_prompt="你是助手",
        )

    assert result["reply"] == "OK"
    assert result["actions"] == [{"action": "noop"}]
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-pro"
    assert kwargs["messages"] == [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "你好"},
    ]
