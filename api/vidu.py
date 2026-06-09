import base64
import time
import httpx
from pathlib import Path

from api.errors import describe_exception, describe_remote_error

VIDU_BASE = "https://api.vidu.cn"
SUBMIT_URL = f"{VIDU_BASE}/ent/v2/reference2image"
POLL_URL = f"{VIDU_BASE}/ent/v2/tasks/{{task_id}}/creations"

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


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }


def _img_to_data_uri(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def _request(method: str, url: str, **kwargs):
    with httpx.Client(trust_env=False, timeout=kwargs.pop("timeout", 120)) as client:
        return client.request(method, url, **kwargs)


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

    try:
        resp = _request("POST", SUBMIT_URL, headers=_headers(api_key), json=body, timeout=60)
    except Exception as e:
        raise ViduError(describe_exception("Vidu", e))
    if not resp.is_success:
        try:
            err = resp.json()
            reason = err.get("reason", "")
            message = err.get("message", "")
        except Exception:
            reason, message = "", resp.text[:200]
        detail = f"{reason}: {message}" if reason else message
        raise ViduError(describe_remote_error("Vidu", resp.status_code, detail))

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
