import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from api import llm, pipeline as pl
from api.routes.settings import get_api_key
router = APIRouter()

# ── 内置默认提示词模板 ──

CHARACTER_SYSTEM = """你是影视角色提示词生成专家。根据用户提供的角色描述，填充以下模板并返回完整提示词。模板骨架保持英文，填充部分用中文。直接返回提示词文本，不要解释。

模板：
请创作一张高完成度的「电影级角色设定板」。

角色名称：{name}
年龄：{age}
风格方向：电影级风格化写实
外貌特征：{appearance}
服装设定：{costume}

要求生成一张像影视或动画项目开发用的高级角色提案板，而不是普通三视图。
版面结构必须包含：1.主视觉角色立像 2.全身多角度转面图 3.头部研究图 4.电影感情绪肖像 5.服装与配件拆解 6.专业标注信息
排版：横版大画幅，不规则网格，中性灰背景
表现：真实演员质感，五官在所有角度严格一致，材质真实"""

SCENE_SYSTEM = """你是影视场景提示词生成专家。根据描述填充场景参考板提示词。直接返回提示词文本，不要解释。

使用以下模板：
Create a cinematic multi-angle scene reference board of one single physical location.
Scene: {description}
All four panels must show the exact same physical room from different camera positions only.
Keep consistent across all panels: same room layout, same architecture, same furniture, same lighting.
Only change the camera angle.
Create a clean 2x2 reference grid. No text, no labels.
Panel: top-left: front wide shot, top-right: reverse angle, bottom-left: top-down, bottom-right: cinematic medium shot."""

PROP_SYSTEM = """你是影视道具提示词生成专家。根据描述填充道具参考板提示词。直接返回提示词文本。

使用以下模板：
Create a cinematic multi-angle reference board of one single physical object.
Object: {description}
All four panels must show the exact same object from different camera positions.
Create a clean 2x2 reference grid. No text, no labels.
Panel: top-left: front master, top-right: side profile, bottom-left: top-down, bottom-right: hero close-up detail."""

STORYBOARD_SYSTEM = """你是影视故事板提示词生成专家。根据剧本段落和角色/场景参考信息，生成包含9格动作描述的故事板提示词。

严格套用以下模板格式（英文骨架+中文填充）：

Use Image A as the character reference for {char_a}.
Use Image C as the environment reference for {scene}.

Create a clean 3x3 cinematic storyboard grid in full color.

CRITICAL: character must be visible in every panel.

NOT a game CG screenshot. NOT a 3D render. NOT anime.
Modern digital cinema camera, live-action feature film production stills.
NO film grain.

Panel sequence（每格必须写明所有在场角色位置和朝向）:
1. [shot type] — [动作描述，含所有角色位置]
...（共9格）

Style: full-color cinematic storyboard, live-action production still board.
No text, no captions, no panel numbers, no watermark.

返回完整填充后的提示词文本，同时在末尾附上 JSON：
---PANELS---
[{"index":1,"shot":"...","action":"..."},...]"""

VIDEO_SYSTEM = """你是视频提示词生成专家，严格套用 v2 结构化镜头格式。

输入：
- 故事板色调段（来自 prompt.optimized）
- panels（9格，每格含 shot + action）
- 剧本台词/动作行

输出：将9格按情绪节拍拆成2-3段，每段格式：

段头：
{{Portrait 1}} 为{char_a} {{Portrait N}} 为故事板

真人电影风格，画面不要出现任何文字，生成视频无BGM。

每格镜头单元：
c{编号},{时长}s,（第{格数}格，{shot}）
(空间:{场景名})
(姿态:{{角色A}}-{动作基底})
(位置:{{角色A}}-{位置})
(情绪:{{角色A}}-{情绪词} {强度}/10)
{散文段：景别+镜头运动+台词}【不出现任何文字字幕】

时长计算：正常3字/秒，耳语2字/秒，VO 2.5字/秒
每段10-15秒，不超过20秒

返回所有分段的提示词，每段用 ---PART{n}--- 分隔。"""

# 内置默认值常量，供 pipeline.py 延迟加载
_BUILTIN_DEFAULTS = {
    "character": CHARACTER_SYSTEM,
    "scene": SCENE_SYSTEM,
    "prop": PROP_SYSTEM,
    "storyboard_v1": STORYBOARD_SYSTEM,
    "video_v1": VIDEO_SYSTEM,
}


class GenerateRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    project_name: str = ""
    project_path: str = ""
    board_version: str = "v1"   # 故事板/视频版本标识，如 "v1"/"v2"
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    characters: Optional[list[str]] = None
    scene_location: Optional[str] = None
    script_segment: Optional[str] = None
    panels: Optional[list[dict]] = None


class BatchGenerateItem(BaseModel):
    type: str
    board_version: str = "v1"
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    characters: Optional[list[str]] = None
    scene_location: Optional[str] = None
    script_segment: Optional[str] = None
    panels: Optional[list[dict]] = None


class BatchGenerateRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    items: list[BatchGenerateItem]


class UpdateDraftRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    category: str   # characters | scenes | props | storyboard | video_part
    board_version: str = "v1"
    name: Optional[str] = None
    scene_key: Optional[str] = None
    part: Optional[int] = None
    draft_prompt: str


def _resolve_project_dir(project_path: str, project_name: str):
    if project_path:
        return Path(project_path)
    return pl.get_project_root(project_name)


def _get_template(templates: dict, type_key: str, board_version: str = "v1") -> str:
    """
    取模板内容。
    - character/scene/prop：直接按 key 取
    - storyboard/video：按 storyboard_{ver} / video_{ver} 取，fallback 到 storyboard_v1/video_v1
    """
    if type_key in ("storyboard", "video"):
        versioned_key = f"{type_key}_{board_version}"
        content = templates.get(versioned_key)
        if content:
            return content
        # fallback 到 v1
        fallback = templates.get(f"{type_key}_v1")
        if fallback:
            return fallback
        return _BUILTIN_DEFAULTS.get(f"{type_key}_v1", "")
    # character / scene / prop
    content = templates.get(type_key)
    if isinstance(content, str):
        return content
    # 兼容旧变体格式 {"default": "..."}
    if isinstance(content, dict):
        return content.get("default", "")
    return _BUILTIN_DEFAULTS.get(type_key, "")


def _get_scene(data: dict, board_version: str, scene_key: str) -> dict | None:
    return data.get("storyboards", {}).get(board_version, {}).get(scene_key)


def _save_draft_prompt(project_dir, category: str, name: str, prompt: str, board_version: str = "v1"):
    try:
        data = pl.read_pipeline(project_dir)
        if category == "storyboard":
            scene = _get_scene(data, board_version, name)
            if scene is not None:
                scene["draft_prompt"] = prompt
                scene["status"] = "drafted"
                pl.write_pipeline(project_dir, data)
        else:
            asset = data.get("assets", {}).get(category, {}).get(name)
            if asset:
                asset["draft_prompt"] = prompt
                asset["status"] = "drafted"
                pl.write_pipeline(project_dir, data)
    except Exception:
        pass


def _save_video_parts(project_dir, scene_key: str, raw_prompt: str, board_version: str = "v1"):
    data = pl.read_pipeline(project_dir)
    scene = _get_scene(data, board_version, scene_key)
    if not scene:
        return
    _parse_video_parts_into_scene(scene, raw_prompt)
    pl.write_pipeline(project_dir, data)


def _parse_video_parts_into_scene(scene: dict, raw_prompt: str):
    parts = re.split(r'---PART[0-9]+---', raw_prompt)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        parts = [raw_prompt.strip()]
    video_parts = []
    for i, p in enumerate(parts, 1):
        durations = re.findall(r'c[0-9]+[，,]\s*([0-9]+)\s*s', p)
        total_sec = sum(int(d) for d in durations) if durations else 0
        total_sec = max(4, min(15, total_sec)) if total_sec else 0
        video_parts.append({
            "part": i,
            "draft_prompt": p,
            "prompt": p,
            "duration": total_sec or None,
            "video_status": "drafted",
            "video_task_id": None,
            "video_url": None,
            "local_path": None,
        })
    scene["video_parts"] = video_parts


async def _generate_single(item: BatchGenerateItem, project_name: str, project_path: str,
                            api_key: str, project_dir, templates: dict) -> dict:
    try:
        if item.type == "character":
            system = _get_template(templates, "character")
            user_msg = f"角色名：{item.name}\n描述：{item.appearance_seed}"
            prompt = await llm.generate_prompt_async(api_key, system, user_msg)
            return {"type": "character", "name": item.name, "category": "characters",
                    "prompt": prompt, "ok": True}

        elif item.type == "scene":
            system = _get_template(templates, "scene")
            user_msg = f"场景名：{item.name}\n描述：{item.appearance_seed}"
            prompt = await llm.generate_prompt_async(api_key, system, user_msg)
            return {"type": "scene", "name": item.name, "category": "scenes",
                    "prompt": prompt, "ok": True}

        elif item.type == "prop":
            system = _get_template(templates, "prop")
            user_msg = f"道具名：{item.name}\n描述：{item.appearance_seed}"
            prompt = await llm.generate_prompt_async(api_key, system, user_msg)
            return {"type": "prop", "name": item.name, "category": "props",
                    "prompt": prompt, "ok": True}

        elif item.type == "storyboard":
            char_info = []
            for char_name in (item.characters or []):
                optimized = pl.get_prompt_optimized(project_dir, "characters", char_name)
                char_info.append({"name": char_name, "appearance": optimized or char_name})
            scene_optimized = pl.get_prompt_optimized(project_dir, "scenes_props", item.scene_location or "")
            user_msg = (
                f"场景：{item.scene_key}\n"
                f"角色信息：{char_info}\n"
                f"场景色调：{scene_optimized or ''}\n"
                f"剧本段落：{item.script_segment or ''}"
            )
            system = _get_template(templates, "storyboard", item.board_version)
            prompt = await llm.generate_prompt_async(api_key, system, user_msg)
            return {"type": "storyboard", "scene_key": item.scene_key, "board_version": item.board_version,
                    "prompt": prompt, "ok": True}

        elif item.type == "video":
            board_meta_dir = project_dir / "storyboards" / (item.scene_key or "")
            panels = item.panels or []
            board_optimized = ""
            if board_meta_dir.exists():
                import json
                meta_path = board_meta_dir / "meta.json"
                if meta_path.exists():
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    primary = meta.get("primary_image")
                    for v in meta.get("versions", []):
                        if v.get("filename") == primary:
                            board_optimized = v.get("prompt", {}).get("optimized", "")
                            if not panels:
                                panels = v.get("panels", [])
            user_msg = (
                f"故事板名：{item.scene_key}\n"
                f"色调风格段：{board_optimized}\n"
                f"panels（9格）：{panels}\n"
                f"剧本台词/动作行：{item.script_segment or ''}"
            )
            system = _get_template(templates, "video", item.board_version)
            prompt = await llm.generate_prompt_async(api_key, system, user_msg)
            return {"type": "video", "scene_key": item.scene_key, "board_version": item.board_version,
                    "prompt": prompt, "raw": prompt, "ok": True}

        else:
            return {"type": item.type, "name": item.name or "", "ok": False, "error": f"未知类型: {item.type}"}
    except Exception as e:
        return {"type": item.type, "name": item.name or item.scene_key or "", "ok": False, "error": str(e)}


@router.post("/batch-generate")
async def batch_generate_prompts(req: BatchGenerateRequest):
    import asyncio
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    templates = pl.read_prompt_templates(project_dir)

    sem = asyncio.Semaphore(5)

    async def _generate_one(item: BatchGenerateItem):
        async with sem:
            return await _generate_single(item, req.project_name, req.project_path,
                                          api_key, project_dir, templates)

    results = await asyncio.gather(*[_generate_one(item) for item in req.items])

    data = pl.read_pipeline(project_dir)
    for r in results:
        if not r.get("ok"):
            continue
        if r["type"] in ("character", "scene", "prop"):
            category = r["category"]
            asset = data.get("assets", {}).get(category, {}).get(r["name"])
            if asset:
                asset["draft_prompt"] = r["prompt"]
                asset["status"] = "drafted"
        elif r["type"] == "storyboard":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            if scene is not None:
                scene["draft_prompt"] = r["prompt"]
                scene["status"] = "drafted"
        elif r["type"] == "video":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            if scene is not None:
                _parse_video_parts_into_scene(scene, r["raw"])

    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)

    response_results = []
    for r in results:
        name = r.get("name") or r.get("scene_key") or ""
        if r.get("ok"):
            response_results.append({"name": name, "ok": True, "prompt": r.get("prompt", "")})
        else:
            response_results.append({"name": name, "ok": False, "error": r.get("error", "")})
    return {"results": response_results}


@router.post("/generate")
async def generate_prompt_endpoint(req: GenerateRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    templates = pl.read_prompt_templates(project_dir)

    if req.type == "character":
        system = _get_template(templates, "character")
        user_msg = f"角色名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "characters", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "scene":
        system = _get_template(templates, "scene")
        user_msg = f"场景名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "scenes", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "prop":
        system = _get_template(templates, "prop")
        user_msg = f"道具名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "props", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "storyboard":
        char_info = []
        for char_name in (req.characters or []):
            optimized = pl.get_prompt_optimized(project_dir, "characters", char_name)
            char_info.append({"name": char_name, "appearance": optimized or char_name})
        scene_optimized = pl.get_prompt_optimized(project_dir, "scenes_props", req.scene_location or "")
        user_msg = (
            f"场景：{req.scene_key}\n"
            f"角色信息：{char_info}\n"
            f"场景色调：{scene_optimized or ''}\n"
            f"剧本段落：{req.script_segment or ''}"
        )
        system = _get_template(templates, "storyboard", req.board_version)
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "storyboard", req.scene_key, prompt, req.board_version)
        return {"prompt": prompt}

    elif req.type == "video":
        board_meta_dir = project_dir / "storyboards" / (req.scene_key or "")
        panels = req.panels or []
        board_optimized = ""
        if board_meta_dir.exists():
            import json
            meta_path = board_meta_dir / "meta.json"
            if meta_path.exists():
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                primary = meta.get("primary_image")
                for v in meta.get("versions", []):
                    if v.get("filename") == primary:
                        board_optimized = v.get("prompt", {}).get("optimized", "")
                        if not panels:
                            panels = v.get("panels", [])
        user_msg = (
            f"故事板名：{req.scene_key}\n"
            f"色调风格段：{board_optimized}\n"
            f"panels（9格）：{panels}\n"
            f"剧本台词/动作行：{req.script_segment or ''}"
        )
        system = _get_template(templates, "video", req.board_version)
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_video_parts(project_dir, req.scene_key, prompt, req.board_version)
        return {"prompt": prompt, "raw": prompt}

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")


@router.put("/update-draft")
async def update_draft(req: UpdateDraftRequest):
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    data = pl.read_pipeline(project_dir)

    if req.category == "storyboard":
        scene = _get_scene(data, req.board_version, req.scene_key)
        if scene is None:
            raise HTTPException(status_code=404, detail="故事板场景不存在")
        scene["draft_prompt"] = req.draft_prompt
        scene["status"] = "drafted"

    elif req.category == "video_part":
        scene = _get_scene(data, req.board_version, req.scene_key)
        if scene is None:
            raise HTTPException(status_code=404, detail="故事板场景不存在")
        for vp in scene.get("video_parts", []):
            if vp["part"] == req.part:
                vp["draft_prompt"] = req.draft_prompt
                vp["video_status"] = "drafted"
                break
        else:
            raise HTTPException(status_code=404, detail=f"Part {req.part} 不存在")

    else:
        asset = data.get("assets", {}).get(req.category, {}).get(req.name)
        if not asset:
            raise HTTPException(status_code=404, detail=f"资产 {req.name} 不存在")
        asset["draft_prompt"] = req.draft_prompt
        asset["status"] = "drafted"

    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"ok": True}
