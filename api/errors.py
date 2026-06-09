import httpx


def describe_remote_error(service: str, status_code: int | None = None, message: str = "") -> str:
    text = str(message or "").strip()
    lower = text.lower()

    if status_code in (401, 403) or any(k in lower for k in ("unauthorized", "forbidden", "invalid api key", "token")):
        return f"{service} 认证失败，请检查 API Key 是否正确。"
    if status_code == 429 or any(k in lower for k in ("rate limit", "too many requests", "throttle")):
        return f"{service} 请求过于频繁，请稍后重试。"
    if status_code in (402, 429) or any(k in lower for k in ("quota", "balance", "insufficient", "credit", "余额", "额度")):
        return f"{service} 额度不足或达到使用限制，请检查账户额度。"
    if any(k in lower for k in ("moderation", "policy", "sensitive", "blocked", "content")):
        return f"{service} 拒绝了当前内容或素材，请调整提示词或参考图后重试。"
    if status_code and 400 <= status_code < 500:
        return f"{service} 请求参数不被接受，请检查提示词、比例、时长或参考素材。"
    if status_code and status_code >= 500:
        return f"{service} 服务暂时不可用，请稍后重试。"
    if text:
        return f"{service} 返回错误: {text}"
    return f"{service} 返回未知错误，请稍后重试。"


def describe_exception(service: str, exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"{service} 请求超时，请检查网络或稍后重试。"
    if isinstance(exc, httpx.RequestError):
        return f"{service} 网络请求失败，请检查网络连接或代理设置。"
    return describe_remote_error(service, message=str(exc))
