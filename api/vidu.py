import base64
import io
import time
import httpx
import asyncio
from pathlib import Path

from PIL import Image, ImageOps

VIDU_BASE = "https://api.vidu.cn"
SUBMIT_URL = f"{VIDU_BASE}/ent/v2/reference2image"
POLL_URL = f"{VIDU_BASE}/ent/v2/tasks/{{task_id}}/creations"
SUBMIT_TIMEOUT = httpx.Timeout(300.0, connect=30.0, read=300.0, write=300.0, pool=30.0)

RATIO_TO_ASPECT = {
    "1:1": "1:1",
    "3:4": "3:4",
    "4:3": "4:3",
    "16:9": "16:9",
    "9:16": "9:16",
    "2:3": "2:3",
    "3:2": "3:2",
}


class ViduError(Exception):
    pass


_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
    httpx.WriteTimeout,
)


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }


def _img_to_data_uri(path: str) -> str:
    """Encode local reference images compactly for Vidu request payloads."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1280, 1280), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


def _request(method: str, url: str, **kwargs):
    with httpx.Client(trust_env=False, timeout=kwargs.pop("timeout", 120)) as client:
        return client.request(method, url, **kwargs)


def _request_with_retries(method: str, url: str, attempts: int = 3, **kwargs):
    last_error = None
    for attempt in range(attempts):
        try:
            return _request(method, url, **kwargs)
        except _TRANSIENT_EXCEPTIONS as e:
            last_error = e
            if attempt < attempts - 1:
                time.sleep(0.8 * (attempt + 1))
    raise ViduError(f"Vidu 连接中断，已重试 {attempts} 次仍失败: {last_error}")


async def _async_request_with_retries(client: httpx.AsyncClient, method: str, url: str,
                                      attempts: int = 3, **kwargs):
    last_error = None
    for attempt in range(attempts):
        try:
            return await client.request(method, url, **kwargs)
        except _TRANSIENT_EXCEPTIONS as e:
            last_error = e
            if attempt < attempts - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
    raise ViduError(f"Vidu 连接中断，已重试 {attempts} 次仍失败: {last_error}")


def submit_image_task(
    api_key: str,
    prompt: str,
    image_paths: list,
    ratio: str = "16:9",
) -> dict:
    """提交图片生成任务（异步），返回 {"task_id": ...}"""
    aspect_ratio = RATIO_TO_ASPECT.get(ratio, "16:9")
    body = {
        "model": "viduimage-2",
        "prompt": prompt,
        "resolution": "2K",
        "quality": "high",
        "moderation": "disabled",
        "aspect_ratio": aspect_ratio,
    }
    if image_paths:
        body["images"] = [
            p if p.startswith("http") else _img_to_data_uri(p)
            for p in image_paths
        ]

    resp = _request_with_retries("POST", SUBMIT_URL, headers=_headers(api_key), json=body, timeout=SUBMIT_TIMEOUT)
    if not resp.is_success:
        try:
            err = resp.json()
            reason = err.get("reason", "")
            message = err.get("message", "")
        except Exception:
            reason, message = "", resp.text[:200]
        raise ViduError(f"{reason}: {message}" if reason else f"HTTP {resp.status_code}: {message}")

    task_id = resp.json().get("task_id")
    if not task_id:
        raise ViduError(f"API 未返回 task_id：{resp.text[:200]}")
    return {"task_id": task_id}


def poll_task(api_key: str, task_id: str) -> dict:
    """轮询任务状态，返回 {"status": ..., "image_url": ..., "error": ...}"""
    url = POLL_URL.format(task_id=task_id)
    resp = _request("GET", url, headers=_headers(api_key), timeout=30)
    if not resp.is_success:
        return {"status": "pending", "image_url": None, "error": None}

    data = resp.json()
    state = data.get("state", "unknown")

    if state == "success":
        creations = data.get("creations", [])
        image_url = creations[0]["url"] if creations else None
        return {"status": "success", "image_url": image_url, "error": None}
    elif state in ("failed", "error"):
        return {"status": "failed", "image_url": None, "error": data.get("err_code", "unknown")}
    else:
        return {"status": "pending", "image_url": None, "error": None}


def poll_until_done(api_key: str, task_id: str, timeout: int = 300, interval: int = 5) -> str:
    """阻塞轮询直到完成，返回图片 URL。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = poll_task(api_key, task_id)
        if result["status"] == "success":
            return result["image_url"]
        if result["status"] in ("failed", "error"):
            raise ViduError(f"任务失败：{result['error']}")
        time.sleep(interval)
    raise ViduError(f"任务 {task_id} 超时（{timeout}s）")


def download_image(url: str, dest_path: Path) -> None:
    """从 URL 下载图片到本地"""
    resp = _request("GET", url, follow_redirects=True, timeout=120)
    resp.raise_for_status()
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(resp.content)


# ── 异步版本 ──

_async_client: httpx.AsyncClient | None = None


async def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(trust_env=False, timeout=120)
    return _async_client


async def close_async_client():
    global _async_client
    if _async_client and not _async_client.is_closed:
        await _async_client.aclose()
    _async_client = None


async def poll_task_async(api_key: str, task_id: str) -> dict:
    """异步轮询任务状态"""
    url = POLL_URL.format(task_id=task_id)
    client = await _get_async_client()
    resp = await client.get(url, headers=_headers(api_key), timeout=30)
    if not resp.is_success:
        return {"status": "pending", "image_url": None, "error": None}

    data = resp.json()
    state = data.get("state", "unknown")

    if state == "success":
        creations = data.get("creations", [])
        image_url = creations[0]["url"] if creations else None
        return {"status": "success", "image_url": image_url, "error": None}
    elif state in ("failed", "error"):
        return {"status": "failed", "image_url": None, "error": data.get("err_code", "unknown")}
    else:
        return {"status": "pending", "image_url": None, "error": None}


async def download_image_async(url: str, dest_path: Path) -> None:
    """异步下载图片到本地"""
    client = await _get_async_client()
    resp = await client.get(url, follow_redirects=True, timeout=120)
    resp.raise_for_status()
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(resp.content)


async def submit_image_task_async(
    api_key: str,
    prompt: str,
    image_paths: list,
    ratio: str = "16:9",
) -> dict:
    """异步提交图片生成任务"""
    aspect_ratio = RATIO_TO_ASPECT.get(ratio, "16:9")
    body = {
        "model": "viduimage-2",
        "prompt": prompt,
        "resolution": "2K",
        "quality": "high",
        "moderation": "disabled",
        "aspect_ratio": aspect_ratio,
    }
    if image_paths:
        body["images"] = [
            p if p.startswith("http") else _img_to_data_uri(p)
            for p in image_paths
        ]
    client = await _get_async_client()
    resp = await _async_request_with_retries(
        client, "POST", SUBMIT_URL, headers=_headers(api_key), json=body, timeout=SUBMIT_TIMEOUT
    )
    if not resp.is_success:
        try:
            err = resp.json()
            reason = err.get("reason", "")
            message = err.get("message", "")
        except Exception:
            reason, message = "", resp.text[:200]
        raise ViduError(f"{reason}: {message}" if reason else f"HTTP {resp.status_code}: {message}")
    task_id = resp.json().get("task_id")
    if not task_id:
        raise ViduError(f"API 未返回 task_id：{resp.text[:200]}")
    return {"task_id": task_id}
