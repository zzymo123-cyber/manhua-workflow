import json
import os
import httpx
import anthropic

from api.errors import describe_exception

DEFAULT_BASE_URL = "https://idealab.alibaba-inc.com/api/anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"


class LLMError(Exception):
    pass


def _get_client(api_key: str) -> anthropic.Anthropic:
    base_url = os.environ.get("IDEALAB_BASE_URL", "")
    if not base_url:
        try:
            from api.routes.settings import read_settings
            base_url = read_settings().get("idealab_base_url", "") or DEFAULT_BASE_URL
        except Exception:
            base_url = DEFAULT_BASE_URL
    # *.alibaba-inc.com 在 Windows ProxyOverride 直连，httpx 不读 ProxyOverride，显式绕过代理
    http_client = httpx.Client(trust_env=False, verify=False)
    return anthropic.Anthropic(api_key=api_key, base_url=base_url, http_client=http_client)


def generate_prompt(api_key: str, system: str, user_message: str, model: str = DEFAULT_MODEL) -> str:
    """调用 LLM 生成提示词，返回纯文本"""
    client = _get_client(api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        raise LLMError(describe_exception("ideaLAB", e))
    return resp.content[0].text


def chat_with_agent(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Agent 聊天。LLM 必须返回 JSON: {"reply": "...", "actions": [...]}
    如果返回非 JSON，将整个内容作为 reply，actions 为空。
    """
    client = _get_client(api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
    except Exception as e:
        raise LLMError(describe_exception("ideaLAB", e))
    content = resp.content[0].text
    try:
        data = json.loads(content)
        return {
            "reply": data.get("reply", ""),
            "actions": data.get("actions", []),
            "_raw": content,
        }
    except (json.JSONDecodeError, AttributeError):
        return {"reply": content, "actions": [], "_raw": content}
