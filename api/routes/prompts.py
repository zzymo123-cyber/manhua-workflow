import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from api import llm, pipeline as pl
from api.routes.settings import get_api_key

router = APIRouter()

# ── 提示词模板（内联自 vidu-studio prompt_templates.md）──

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


class GenerateRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    project_name: str
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    characters: Optional[list[str]] = None
    scene_location: Optional[str] = None
    script_segment: Optional[str] = None
    panels: Optional[list[dict]] = None


class BatchGenerateItem(BaseModel):
    type: str
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    characters: Optional[list[str]] = None
    scene_location: Optional[str] = None
    script_segment: Optional[str] = None
    panels: Optional[list[dict]] = None


class BatchGenerateRequest(BaseModel):
    project_name: str
    items: list[BatchGenerateItem]


@router.post("/batch-generate")
async def batch_generate_prompts(req: BatchGenerateRequest):
    """批量生成提示词，逐个处理，返回每项结果"""
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = pl.get_project_root(req.project_name)
    results = []
    for item in req.items:
        try:
            single_req = GenerateRequest(
                type=item.type, project_name=req.project_name,
                name=item.name, appearance_seed=item.appearance_seed,
                scene_key=item.scene_key, characters=item.characters,
                scene_location=item.scene_location, script_segment=item.script_segment,
                panels=item.panels,
            )
            result = await generate_prompt_endpoint(single_req)
            results.append({"name": item.name or item.scene_key or "", "ok": True, "prompt": result["prompt"]})
        except Exception as e:
            results.append({"name": item.name or item.scene_key or "", "ok": False, "error": str(e)})
    return {"results": results}


def _save_draft_prompt(project_dir, category: str, name: str, prompt: str):
    """把生成的 draft_prompt 写回 pipeline.json，让 refreshStatus 能读到它"""
    try:
        data = pl.read_pipeline(project_dir)
        if category == "storyboard":
            if name and name in data.get("storyboards", {}):
                data["storyboards"][name]["draft_prompt"] = prompt
                pl.write_pipeline(project_dir, data)
        else:
            if name and name in data.get("assets", {}).get(category, {}):
                data["assets"][category][name]["draft_prompt"] = prompt
                pl.write_pipeline(project_dir, data)
    except Exception:
        pass  # 写入失败不影响返回结果


def _save_video_parts(project_dir, scene_key: str, raw_prompt: str):
    """解析视频提示词分段（---PARTn---），写入 pipeline.json 的 video_parts"""
    import re
    data = pl.read_pipeline(project_dir)
    board = data.get("storyboards", {}).get(scene_key)
    if not board:
        return
    # 按 ---PARTn--- 分割（用 [0-9] 代替 \d，避免 cp936 locale 下 \d 不匹配）
    parts = re.split(r'---PART[0-9]+---', raw_prompt)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        # 没有分段标记，整段作为 Part 1
        parts = [raw_prompt.strip()]
    video_parts = []
    for i, p in enumerate(parts, 1):
        # 从提示词中累加 c{编号},{时长}s 格式的秒数
        # 用 [0-9] 代替 \d（cp936 兼容），同时支持中英文逗号
        durations = re.findall(r'c[0-9]+[，,]\s*([0-9]+)\s*s', p)
        total_sec = sum(int(d) for d in durations) if durations else 0
        # Seedance API 限制 4-15 秒
        total_sec = max(4, min(15, total_sec)) if total_sec else 0
        video_parts.append({
            "part": i,
            "prompt": p,
            "draft_prompt": p,
            "video_status": "needed",
            "duration": total_sec or None,
        })
    board["video_parts"] = video_parts
    pl.write_pipeline(project_dir, data)


@router.post("/generate")
async def generate_prompt_endpoint(req: GenerateRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = pl.get_project_root(req.project_name)
    templates = pl.read_prompt_templates(project_dir)

    if req.type == "character":
        system = templates.get("character", CHARACTER_SYSTEM)
        user_msg = f"角色名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "characters", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "scene":
        system = templates.get("scene", SCENE_SYSTEM)
        user_msg = f"场景名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "scenes", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "prop":
        system = templates.get("prop", PROP_SYSTEM)
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
        prompt = llm.generate_prompt(api_key, templates.get("storyboard", STORYBOARD_SYSTEM), user_msg)
        _save_draft_prompt(project_dir, "storyboard", req.scene_key, prompt)
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
        prompt = llm.generate_prompt(api_key, templates.get("video", VIDEO_SYSTEM), user_msg)
        # 解析分段并写入 pipeline.json 的 video_parts
        _save_video_parts(project_dir, req.scene_key, prompt)
        return {"prompt": prompt, "raw": prompt}

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")
