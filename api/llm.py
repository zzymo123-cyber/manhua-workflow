import asyncio
import json
import os
import httpx
import anthropic

DEFAULT_BASE_URL = "https://idealab.alibaba-inc.com/api/anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_LLM_PROVIDER = "idealab"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


def _read_settings() -> dict:
    try:
        from api.routes.settings import read_settings
        return read_settings()
    except Exception:
        return {}


def _get_llm_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "")
    if not provider:
        provider = _read_settings().get("llm_provider", "")
    provider = (provider or DEFAULT_LLM_PROVIDER).strip().lower()
    if provider == "ds":
        return "deepseek"
    return provider


def _get_client(api_key: str) -> anthropic.Anthropic:
    base_url = os.environ.get("IDEALAB_BASE_URL", "")
    if not base_url:
        base_url = _read_settings().get("idealab_base_url", "") or DEFAULT_BASE_URL
    # *.alibaba-inc.com 在 Windows ProxyOverride 直连，httpx 不读 ProxyOverride，显式绕过代理
    http_client = httpx.Client(trust_env=False, verify=False)
    return anthropic.Anthropic(api_key=api_key, base_url=base_url, http_client=http_client)


def _get_deepseek_config(fallback_api_key: str = "") -> tuple[str, str, str]:
    settings = _read_settings()
    api_key = (
        os.environ.get("DEEPSEEK_API_KEY")
        or settings.get("deepseek_api_key", "")
        or fallback_api_key
    )
    base_url = (
        os.environ.get("DEEPSEEK_BASE_URL")
        or settings.get("deepseek_base_url", "")
        or DEFAULT_DEEPSEEK_BASE_URL
    )
    model = (
        os.environ.get("DEEPSEEK_MODEL")
        or settings.get("deepseek_model", "")
        or DEFAULT_DEEPSEEK_MODEL
    )
    return api_key, base_url, model


def _get_deepseek_client(api_key: str, base_url: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url)


def _generate_deepseek_prompt(api_key: str, system: str, user_message: str, model: str | None = None) -> str:
    ds_key, base_url, ds_model = _get_deepseek_config(api_key)
    client = _get_deepseek_client(ds_key, base_url)
    resp = client.chat.completions.create(
        model=model or ds_model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    return resp.choices[0].message.content or ""


def generate_prompt(api_key: str, system: str, user_message: str, model: str = DEFAULT_MODEL) -> str:
    """调用 LLM 生成提示词，返回纯文本"""
    if _get_llm_provider() == "deepseek":
        return _generate_deepseek_prompt(api_key, system, user_message, None)
    client = _get_client(api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
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
    if _get_llm_provider() == "deepseek":
        ds_key, base_url, ds_model = _get_deepseek_config(api_key)
        client = _get_deepseek_client(ds_key, base_url)
        resp = client.chat.completions.create(
            model=ds_model,
            max_tokens=4096,
            messages=[{"role": "system", "content": system_prompt}] + messages,
        )
        content = resp.choices[0].message.content or ""
        try:
            data = json.loads(content)
            return {
                "reply": data.get("reply", ""),
                "actions": data.get("actions", []),
                "_raw": content,
            }
        except (json.JSONDecodeError, AttributeError):
            return {"reply": content, "actions": [], "_raw": content}

    client = _get_client(api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,
    )
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


# ── 异步版本 ──


async def generate_prompt_async(api_key: str, system: str, user_message: str, model: str = DEFAULT_MODEL) -> str:
    """异步调用 LLM 生成提示词"""
    return await asyncio.to_thread(generate_prompt, api_key, system, user_message, model)


async def chat_with_agent_async(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """异步 Agent 聊天"""
    return await asyncio.to_thread(chat_with_agent, api_key, messages, system_prompt, model)
