import json
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

SETTINGS_PATH = Path(__file__).parent.parent.parent / "settings.json"

DEFAULTS = {
    "vidu_api_key": "",
    "wetoken_api_key": "",
    "idealab_api_key": "",
    "idealab_base_url": "https://api.idealab.com/v1",
    "llm_provider": "idealab",
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-flash",
    "gh_token": "",
    "gh_owner": "",
    "gh_repo": "",
}


class SettingsModel(BaseModel):
    vidu_api_key: Optional[str] = None
    wetoken_api_key: Optional[str] = None
    idealab_api_key: Optional[str] = None
    idealab_base_url: Optional[str] = None
    llm_provider: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: Optional[str] = None
    deepseek_model: Optional[str] = None
    gh_token: Optional[str] = None
    gh_owner: Optional[str] = None
    gh_repo: Optional[str] = None


def read_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return {**DEFAULTS, **data}
        except Exception:
            pass
    return {**DEFAULTS}


def write_settings(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_api_key(key_name: str) -> str:
    """优先 settings.json，其次环境变量"""
    import os
    mapping = {
        "VIDU_API_KEY": "vidu_api_key",
        "WETOKEN_API_KEY": "wetoken_api_key",
        "IDEALAB_API_KEY": "idealab_api_key",
        "DEEPSEEK_API_KEY": "deepseek_api_key",
    }
    settings = read_settings()
    val = settings.get(mapping.get(key_name, ""), "")
    if val:
        return val
    return os.environ.get(key_name, "")


@router.get("/settings")
async def get_settings():
    s = read_settings()
    # 脱敏：只显示最后4位
    return {
        "vidu_api_key": _mask(s["vidu_api_key"]),
        "wetoken_api_key": _mask(s["wetoken_api_key"]),
        "idealab_api_key": _mask(s["idealab_api_key"]),
        "idealab_base_url": s["idealab_base_url"],
        "llm_provider": s.get("llm_provider", "idealab"),
        "deepseek_api_key": _mask(s.get("deepseek_api_key", "")),
        "deepseek_base_url": s.get("deepseek_base_url", ""),
        "deepseek_model": s.get("deepseek_model", ""),
        "gh_token": _mask(s.get("gh_token", "")),
        "gh_owner": s.get("gh_owner", ""),
        "gh_repo": s.get("gh_repo", ""),
        "_has_vidu": bool(s["vidu_api_key"]),
        "_has_wetoken": bool(s["wetoken_api_key"]),
        "_has_idealab": bool(s["idealab_api_key"]),
        "_has_deepseek": bool(s.get("deepseek_api_key", "")),
        "_has_gh": bool(s.get("gh_token", "")),
    }


@router.put("/settings")
async def update_settings(req: SettingsModel):
    current = read_settings()
    for k, v in req.model_dump().items():
        if v is not None:
            current[k] = v
    try:
        write_settings(current)
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"写入 settings.json 失败: {e}")
    return {"ok": True}


def _mask(val: str) -> str:
    if len(val) <= 4:
        return val
    return "*" * (len(val) - 4) + val[-4:]
