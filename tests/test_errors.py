import httpx

from api.errors import describe_exception, describe_remote_error


def test_describe_remote_auth_error():
    assert "认证失败" in describe_remote_error("Vidu", 401, "invalid api key")


def test_describe_remote_quota_error():
    assert "额度不足" in describe_remote_error("Wetoken", 402, "quota exceeded")


def test_describe_remote_rate_limit_error():
    assert "请求过于频繁" in describe_remote_error("ideaLAB", 429, "too many requests")


def test_describe_remote_content_error():
    assert "拒绝了当前内容" in describe_remote_error("Vidu", 400, "moderation blocked")


def test_describe_timeout_exception():
    assert "请求超时" in describe_exception("Wetoken", httpx.TimeoutException("timeout"))


def test_describe_network_exception():
    request = httpx.Request("GET", "https://example.com")
    assert "网络请求失败" in describe_exception("ideaLAB", httpx.ConnectError("boom", request=request))
