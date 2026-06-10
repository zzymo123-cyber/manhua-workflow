import base64
import io
import json
import os
import time
import httpx
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

BASE_URL = "https://www.wetoken.top/api/v3/contents/generations/tasks"
ASSET_URL = "https://asset.wetoken.lingxixai.com/api/asset"
MODEL = "doubao-seedance-2-0-260128"


class WetokenError(Exception):
    pass


def _headers(api_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _image_to_data_uri(path: str) -> str:
    p = Path(path)
    suffix = p.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(suffix, "image/png")
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


# ── GitHub 推送（获取公网 URL）──

def _get_gh_config() -> tuple[str, str, str]:
    """从 settings.json 读取 GitHub 配置"""
    try:
        from api.routes.settings import read_settings
        s = read_settings()
        return s.get("gh_token", ""), s.get("gh_owner", ""), s.get("gh_repo", "")
    except Exception:
        return "", "", ""


def _push_to_github(local_path: str, filename: str) -> str:
    """推图片到 GitHub 仓库，返回 raw.githubusercontent.com 公网 URL"""
    gh_token, gh_owner, gh_repo = _get_gh_config()
    if not gh_token or not gh_owner or not gh_repo:
        raise WetokenError("缺少 GitHub 配置（gh_token/gh_owner/gh_repo），无法上传素材")

    img = Image.open(local_path).convert("RGB")
    w, h = img.size
    nw, nh = 1024, int(h * 1024 / w)
    buf = io.BytesIO()
    img.resize((nw, nh), Image.LANCZOS).save(buf, "JPEG", quality=88)
    content_b64 = base64.b64encode(buf.getvalue()).decode()

    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{gh_owner}/{gh_repo}/contents/{filename}"

    body = {"message": f"upload {filename}", "content": content_b64}
    r = httpx.get(api_url, headers=headers)
    if r.status_code == 200:
        body["sha"] = r.json()["sha"]

    resp = httpx.put(api_url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return f"https://raw.githubusercontent.com/{gh_owner}/{gh_repo}/main/{filename}"


# ── Wetoken 素材上传 ──

def upload_asset(api_key: str, public_url: str, name: str) -> str:
    """上传图片到 Wetoken 素材 API，返回 asset_id"""
    resp = httpx.post(
        f"{ASSET_URL}/createMedia",
        headers=_headers(api_key),
        json={"url": public_url, "name": name, "assetType": "Image",
              "moderation": {"Strategy": "Skip"}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["Result"]["Id"]


def poll_asset_status(api_key: str, asset_id: str, timeout: int = 180) -> str:
    """轮询素材状态，返回 'Active' 或抛异常"""
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            resp = httpx.get(
                f"{ASSET_URL}/get",
                headers=_headers(api_key),
                params={"id": asset_id},
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()["Result"]
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_error = str(e)
            time.sleep(3)
            continue
        status = result["Status"]
        if status == "Active":
            return "Active"
        if status == "Failed":
            raise WetokenError(f"素材处理失败: {result.get('Error', {}).get('Message', 'unknown')}")
        time.sleep(3)
    detail = f"，最后错误：{last_error}" if last_error else ""
    raise WetokenError(f"素材 {asset_id} 超时未就绪{detail}")


def _get_ledger_path(project_dir: Path) -> Path:
    return project_dir / "asset_ledger.json"


def _load_ledger(project_dir: Path) -> dict:
    path = _get_ledger_path(project_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"assets": {}}


def _save_ledger(project_dir: Path, ledger: dict) -> None:
    path = _get_ledger_path(project_dir)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_cached_asset_uri(ledger: dict, local_path: str) -> str | None:
    """从账本查找已上传素材的 asset:// URI"""
    for info in ledger.get("assets", {}).values():
        if info.get("source_path") == local_path and info.get("status") == "Active":
            return info.get("asset_uri")
    return None


def _cache_asset(project_dir: Path, asset_id: str, asset_uri: str, public_url: str, local_path: str, name: str):
    """记录素材到账本"""
    ledger = _load_ledger(project_dir)
    import datetime
    ledger["assets"][asset_id] = {
        "id": asset_id,
        "asset_uri": asset_uri,
        "source_url": public_url,
        "source_path": local_path,
        "name": name,
        "type": "Image",
        "status": "Active",
        "uploaded_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_ledger(project_dir, ledger)


def upload_local_image(api_key: str, local_path: str, name: str, project_dir: Path) -> str:
    """
    上传本地图片到 Wetoken 素材平台，返回 asset:// URI。
    先查账本缓存，没有则推 GitHub → 上传素材 → 等待 Active → 写账本。
    """
    # 查缓存
    ledger = _load_ledger(project_dir)
    cached = _get_cached_asset_uri(ledger, local_path)
    if cached:
        return cached

    # 推 GitHub 获取公网 URL（文件名加分类前缀避免同名冲突）
    # 从路径推断分类：characters/xxx → char_xxx, scenes_props/xxx → scene_xxx, storyboards/xxx → board_xxx
    rel = ""
    try:
        rel = str(Path(local_path).relative_to(project_dir)).replace("\\", "/")
    except ValueError:
        pass
    prefix = ""
    if rel.startswith("characters/"):
        prefix = "char_"
    elif rel.startswith("scenes_props/"):
        prefix = "scene_"
    elif rel.startswith("storyboards/"):
        prefix = "board_"
    filename = f"{prefix}{name.replace(' ', '_').replace('/', '_')}.jpg"
    public_url = _push_to_github(local_path, filename)

    # 上传到 Wetoken 素材 API
    asset_id = upload_asset(api_key, public_url, name)

    # 等待就绪
    poll_asset_status(api_key, asset_id)

    # 缓存
    asset_uri = f"asset://{asset_id}"
    _cache_asset(project_dir, asset_id, asset_uri, public_url, local_path, name)
    return asset_uri


# ── 视频任务提交 ──

def submit_video_task(
    api_key: str,
    prompt: str,
    image_paths: list[str],
    duration: int = 10,
    ratio: str = "16:9",
    resolution: str = "720p",
    generate_audio: bool = True,
    watermark: bool = False,
    project_dir: Path | None = None,
) -> str:
    """
    提交视频生成任务（多参考图模式）。
    所有图片统一作为 reference_image，不使用 first_frame（API 不允许混用）。
    """
    content = [{"type": "text", "text": prompt}]

    for img_path in image_paths:
        if project_dir and Path(img_path).exists():
            name = Path(img_path).stem
            asset_uri = upload_local_image(api_key, img_path, name, project_dir)
            content.append({"type": "image_url", "image_url": {"url": asset_uri}, "role": "reference_image"})
        else:
            data_uri = _image_to_data_uri(img_path) if Path(img_path).exists() else None
            if data_uri:
                content.append({"type": "image_url", "image_url": {"url": data_uri}, "role": "reference_image"})

    body = {
        "model": MODEL,
        "content": content,
        "duration": duration,
        "ratio": ratio,
        "resolution": resolution,
        "generate_audio": generate_audio,
        "watermark": watermark,
    }
    resp = httpx.post(BASE_URL, headers=_headers(api_key), json=body, timeout=60)
    if not resp.is_success:
        try:
            err_detail = resp.json()
        except Exception:
            err_detail = resp.text
        raise WetokenError(f"Wetoken API {resp.status_code}: {err_detail}")
    data = resp.json()
    if "id" not in data:
        raise WetokenError(f"Unexpected response: {data}")
    return data["id"]


def poll_task(api_key: str, task_id: str) -> dict:
    """
    查询视频任务状态。
    返回: {"status": "pending"|"completed"|"failed", "video_url": str|None, "error": str|None}
    """
    resp = httpx.get(f"{BASE_URL}/{task_id}", headers=_headers(api_key), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", "")

    if status == "succeeded":
        video_url = data.get("content", {}).get("video_url")
        return {"status": "completed", "video_url": video_url, "error": None}
    elif status in ("failed", "expired"):
        error = data.get("error", {}).get("message", status)
        return {"status": "failed", "video_url": None, "error": str(error)}
    else:
        return {"status": "pending", "video_url": None, "error": None}


def download_video(url: str, dest_path: Path) -> None:
    resp = httpx.get(url, timeout=120, follow_redirects=True)
    resp.raise_for_status()
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
    """异步查询视频任务状态"""
    client = await _get_async_client()
    resp = await client.get(f"{BASE_URL}/{task_id}", headers=_headers(api_key), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", "")

    if status == "succeeded":
        video_url = data.get("content", {}).get("video_url")
        return {"status": "completed", "video_url": video_url, "error": None}
    elif status in ("failed", "expired"):
        error = data.get("error", {}).get("message", status)
        return {"status": "failed", "video_url": None, "error": str(error)}
    else:
        return {"status": "pending", "video_url": None, "error": None}


async def download_video_async(url: str, dest_path: Path) -> None:
    """异步下载视频到本地"""
    client = await _get_async_client()
    resp = await client.get(url, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(resp.content)


async def submit_video_task_async(
    api_key: str,
    prompt: str,
    image_paths: list[str],
    duration: int = 10,
    ratio: str = "16:9",
    resolution: str = "720p",
    generate_audio: bool = True,
    watermark: bool = False,
    project_dir: Path | None = None,
) -> str:
    """异步提交视频生成任务（用 to_thread 包装同步上传链路）"""
    import asyncio
    return await asyncio.to_thread(
        submit_video_task, api_key, prompt, image_paths,
        duration, ratio, resolution, generate_audio, watermark, project_dir,
    )
