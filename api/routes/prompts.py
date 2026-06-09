import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from api import llm, pipeline as pl
from api.routes.settings import get_api_key
from api.storyboard_versions import (
    StoryboardVersionError,
    get_storyboard_status,
    get_storyboard_target,
    storyboard_image_relative_path,
    storyboard_output_id,
    sync_legacy_v1_from_output,
)

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

STORYBOARD_V2_SYSTEM = """你是专业影视导演分镜设计师。请根据输入剧情生成一张专业影视分镜板（storyboard sheet），整体为黑白铅笔线稿 / 手绘草图风格，画面规整，像导演工作用的分镜设计图。

【基础信息】
- 集数：从输入场景信息推断
- 题材：从输入剧情推断
- 本场冲突 / 主题：从输入剧情提炼
- 场景：从输入场景信息提炼
- 单张分镜板最长时长：15秒以内
- 镜头数量：建议 5-6 个

【单张时长规则】
- 每一张分镜板的镜头总时长必须控制在 15 秒以内
- 每格镜头都要标注清晰时间码
- 所有镜头时间累计不得超过 15.0 秒
- 如果当前剧情按正常节奏拆分后超过 15 秒，不要强行压缩到一张图内
- 超出 15 秒的内容，自动顺延到下一张分镜板
- 当前这一张只展示前 15 秒以内的内容
- 下一张继续承接剩余剧情，保持场景、人物、动作、空间和叙事连续
- 如果需要连续多张分镜板，请在标题或页脚标注：第1张 / 第2张 / 第3张……

【整体版式】
- 横版宽画幅
- 顶部为黑色标题栏
- 左上角显示：集数｜题材｜本场冲突/主题
- 右上角显示：场景名称
- 上半部分为本张分镜格，横向排布，9:16
- 每个分镜格顶部显示：镜头编号 + 时间码
- 每个分镜格底部有黑底中文说明栏
- 说明栏内容包含：景别/机位、动作描述、台词（没有台词写“台词：无”）
- 下半部分左侧为“俯视位置图”
- 下半部分右侧为“全景场景图”
- 页脚标注：本张剧情摘要、镜头数量、总时长、页码

【拆分原则】
1. 优先保证动作连续
2. 优先保证空间关系清楚
3. 优先保证前后因果明确
4. 优先保证本张分镜板总时长不超过15秒
5. 如果剧情太长，不要硬塞，超出部分自动划到下一张分镜板
6. 每一张图都应形成一个局部叙事单元
7. 分页位置优先断在动作完成、关键信息说完、视线变化、情绪落点或冲突节点成立之后

【每格分镜要求】
- 明确景别：远景 / 全景 / 中景 / 近景 / 特写
- 明确机位：正面 / 侧面 / 背面 / 过肩 / 俯拍 / 仰拍
- 明确动作、方向、空间层次和前后镜头连续性
- 不要把画面做成角色海报，要像能指导拍摄的分镜草图

【人物表现】
- 人物面部采用导演分镜草图式简化处理
- 不需要清晰五官，可以使用留白脸、弱化五官、简单表情线
- 优先表现身体姿态、动作方向、角色站位和镜头调度

【俯视位置图要求】
- 使用简洁平面示意图风格
- 标出主要场景结构、角色站位、移动路径、关键道具/障碍物/出入口
- 使用编号或简单标记区分角色并带简单图例
- 只绘制当前这张分镜板涉及到的空间调度

【全景场景图要求】
- 作为本段戏的 establishing shot / master shot
- 展示完整场景空间、主要角色相对位置、关键环境结构和冲突位置关系

【风格要求】
- 黑白铅笔草图、手绘 storyboard 风格、电影导演分镜稿
- 粗细线结合、动态线条清楚、分栏规整、黑色边框、中文说明栏清晰
- 不要彩色、不要照片感、不要厚涂、不要精修插画、不要动漫海报感、不要角色立绘感
- 不要过度细节化人物脸部，不要乱码文字，不要漏掉俯视位置图和全景场景图

返回完整图像生成提示词，不要解释。"""

VIDEO_V2_SYSTEM = """你是短剧视频提示词生成专家。输入来自 v2 专业影视分镜板模式：单张分镜板总时长不超过15秒，镜头数量通常为5-6个，包含镜头时间码、动作、台词、俯视位置图和全景场景图。

请根据故事板信息和剧本段落，生成可提交给视频生成模型的分段提示词。

规则：
- 保持真人电影风格，画面不要出现文字字幕，不要BGM
- 每个分段必须控制在 4-15 秒
- 优先一张 v2 分镜板对应一个视频 Part；剧情明显超长时拆成多个 Part
- 每个 Part 要描述镜头运动、角色动作、空间方向、情绪节奏和台词
- 保持角色、场景、道具和故事板图像参考的一致性
- 不要引用 UI 或说明文字，不要要求画面里出现时间码和中文栏

输出格式：
---PART1---
c1,{时长}s,（镜头设计）
(空间:{场景名})
(动作:{角色和动作方向})
(情绪:{情绪词} {强度}/10)
电影化视频描述，包含必要台词但不出现字幕。

如需多段，继续用 ---PART2--- 分隔。返回所有分段，不要解释。"""


class GenerateRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    project_name: str = ""
    project_path: str = ""
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    page: Optional[int] = None
    output_id: Optional[str] = None
    characters: Optional[list[str]] = None
    scene_location: Optional[str] = None
    script_segment: Optional[str] = None
    panels: Optional[list[dict]] = None
    shot_plan: Optional[dict] = None
    mode: str = "v1"


class BatchGenerateItem(BaseModel):
    type: str
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    page: Optional[int] = None
    output_id: Optional[str] = None
    characters: Optional[list[str]] = None
    scene_location: Optional[str] = None
    script_segment: Optional[str] = None
    panels: Optional[list[dict]] = None
    shot_plan: Optional[dict] = None
    mode: str = "v1"


class BatchGenerateRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    items: list[BatchGenerateItem]


def _require_project_dir(project_name: str = "", project_path: str = ""):
    project_dir = pl.resolve_project_dir(project_name, project_path)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    return project_dir


def _require_asset(data: dict, category: str, name: str | None, label: str) -> dict:
    if not name:
        raise HTTPException(status_code=400, detail=f"缺少{label}名称")
    item = data.get("assets", {}).get(category, {}).get(name)
    if item is None:
        raise HTTPException(status_code=400, detail=f"未找到{label}: {name}")
    return item


def _require_storyboard(data: dict, scene_key: str | None) -> dict:
    if not scene_key:
        raise HTTPException(status_code=400, detail="缺少故事板场景 key")
    board = data.get("storyboards", {}).get(scene_key)
    if board is None:
        raise HTTPException(status_code=400, detail=f"未找到故事板: {scene_key}")
    return board


def _require_completed_asset(data: dict, category: str, name: str, label: str) -> None:
    info = data.get("assets", {}).get(category, {}).get(name)
    if not info or info.get("status") != "completed":
        raise HTTPException(status_code=400, detail=f"{label}「{name}」未完成")


def _require_completed_storyboard(board: dict) -> None:
    if board.get("board_status") != "completed":
        raise HTTPException(status_code=400, detail="故事板尚未完成，无法生成视频提示词")


def _require_completed_storyboard_target(
    board: dict,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
) -> None:
    try:
        status = get_storyboard_status(board, mode, page, output_id)
    except StoryboardVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if status != "completed":
        raise HTTPException(status_code=400, detail="故事板尚未完成，无法生成视频提示词")


def _storyboard_target_or_400(
    board: dict,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
) -> dict:
    try:
        return get_storyboard_target(board, mode, page, output_id)
    except StoryboardVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch-generate")
async def batch_generate_prompts(req: BatchGenerateRequest):
    """批量生成提示词，逐个处理，返回每项结果"""
    api_key = get_api_key("IDEALAB_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="缺少 ideaLAB API Key，请先在设置中配置")
    _require_project_dir(req.project_name, req.project_path)
    results = []
    for item in req.items:
        try:
            single_req = GenerateRequest(
                type=item.type, project_name=req.project_name, project_path=req.project_path,
                name=item.name, appearance_seed=item.appearance_seed,
                scene_key=item.scene_key, page=item.page, output_id=item.output_id, characters=item.characters,
                scene_location=item.scene_location, script_segment=item.script_segment,
                panels=item.panels, shot_plan=item.shot_plan, mode=item.mode,
            )
            result = await generate_prompt_endpoint(single_req)
            results.append({"name": item.name or item.scene_key or "", "ok": True, "prompt": result["prompt"]})
        except HTTPException as e:
            results.append({"name": item.name or item.scene_key or "", "ok": False, "error": e.detail})
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


def _save_storyboard_draft_prompt(
    project_dir,
    scene_key: str,
    prompt: str,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
):
    try:
        data = pl.read_pipeline(project_dir)
        board = data.get("storyboards", {}).get(scene_key)
        if not board:
            return
        target = get_storyboard_target(board, mode, page, output_id)
        target["draft_prompt"] = prompt
        if mode == "v1":
            sync_legacy_v1_from_output(board)
        pl.write_pipeline(project_dir, data)
    except Exception:
        pass


def _save_video_parts(
    project_dir,
    scene_key: str,
    raw_prompt: str,
    mode: str = "v1",
    page: int | None = None,
    output_id: str | None = None,
):
    """解析视频提示词分段（---PARTn---），写入 pipeline.json 的 video_parts"""
    import re
    data = pl.read_pipeline(project_dir)
    board = data.get("storyboards", {}).get(scene_key)
    if not board:
        return
    legacy_board = "board_versions" not in board
    try:
        target = get_storyboard_target(board, mode, page, output_id)
    except StoryboardVersionError:
        return
    source_page = page or target.get("page", 1)
    source_output_id = storyboard_output_id(mode, source_page, output_id)
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
            "storyboard_mode": mode,
            "storyboard_output_id": source_output_id,
            "storyboard_page": source_page,
            "source_image": storyboard_image_relative_path(scene_key, mode, source_page),
        })
    target["video_parts"] = video_parts
    if legacy_board:
        board["video_parts"] = video_parts
    if mode == "v1":
        sync_legacy_v1_from_output(board)
    pl.write_pipeline(project_dir, data)


def _generate_prompt(api_key: str, system: str, user_msg: str) -> str:
    try:
        return llm.generate_prompt(api_key, system, user_msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ideaLAB API 错误: {e}")


def _template_key(base: str, mode: str) -> str:
    return f"{base}_v2" if mode == "v2" else base


def _json_block(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, indent=2)


@router.post("/generate")
async def generate_prompt_endpoint(req: GenerateRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="缺少 ideaLAB API Key，请先在设置中配置")
    project_dir = _require_project_dir(req.project_name, req.project_path)
    data = pl.read_pipeline(project_dir)
    templates = pl.read_prompt_templates(project_dir)

    if req.type == "character":
        _require_asset(data, "characters", req.name, "角色")
        system = templates.get("character", CHARACTER_SYSTEM)
        user_msg = f"角色名：{req.name}\n描述：{req.appearance_seed}"
        prompt = _generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "characters", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "scene":
        _require_asset(data, "scenes", req.name, "场景")
        system = templates.get("scene", SCENE_SYSTEM)
        user_msg = f"场景名：{req.name}\n描述：{req.appearance_seed}"
        prompt = _generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "scenes", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "prop":
        _require_asset(data, "props", req.name, "道具")
        system = templates.get("prop", PROP_SYSTEM)
        user_msg = f"道具名：{req.name}\n描述：{req.appearance_seed}"
        prompt = _generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "props", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "storyboard":
        board = _require_storyboard(data, req.scene_key)
        target = _storyboard_target_or_400(board, req.mode, req.page, req.output_id)
        char_info = []
        for char_name in (req.characters or []):
            _require_completed_asset(data, "characters", char_name, "角色")
            optimized = pl.get_prompt_optimized(project_dir, "characters", char_name)
            char_info.append({"name": char_name, "appearance": optimized or char_name})
        if req.scene_location:
            scene_category = "scenes" if req.scene_location in data.get("assets", {}).get("scenes", {}) else "props"
            _require_completed_asset(data, scene_category, req.scene_location, "场景/道具")
        scene_optimized = pl.get_prompt_optimized(project_dir, "scenes_props", req.scene_location or "")
        if req.mode == "v2":
            user_msg = (
                f"场景 key：{req.scene_key}\n"
                f"集数：{board.get('episode', '')}\n"
                f"场次：{board.get('scene_num', '')}\n"
                f"场景：{req.scene_location or board.get('scene_location', '')}\n"
                f"时间：{board.get('scene_time', '')}\n"
                f"角色信息：{char_info}\n"
                f"场景色调：{scene_optimized or ''}\n"
                f"本场剧情摘要：{board.get('story_summary', '')}\n"
                f"本场冲突/主题：{board.get('conflict_summary', '')}\n"
                f"本场道具：{board.get('props_in_scene', [])}\n"
                f"分镜计划 JSON：\n{_json_block(req.shot_plan or target.get('shot_plan') or board.get('shot_plan'))}\n"
                f"剧本原文：\n{req.script_segment or board.get('script_segment', '')}"
            )
        else:
            user_msg = (
                f"场景：{req.scene_key}\n"
                f"角色信息：{char_info}\n"
                f"场景色调：{scene_optimized or ''}\n"
                f"剧本段落：{req.script_segment or board.get('script_segment', '')}"
            )
        template_key = _template_key("storyboard", req.mode)
        prompt = _generate_prompt(api_key, templates.get(template_key, STORYBOARD_SYSTEM), user_msg)
        _save_storyboard_draft_prompt(project_dir, req.scene_key, prompt, req.mode, req.page, req.output_id)
        return {"prompt": prompt}

    elif req.type == "video":
        board = _require_storyboard(data, req.scene_key)
        _require_completed_storyboard_target(board, req.mode, req.page, req.output_id)
        target = _storyboard_target_or_400(board, req.mode, req.page, req.output_id)
        board_meta_dir = project_dir / "storyboards" / (req.scene_key or "")
        panels = req.panels or []
        board_optimized = ""
        if board_meta_dir.exists():
            meta = pl.get_meta(project_dir, "storyboards", req.scene_key or "")
            if meta:
                primary = meta.get("primary_image")
                for v in meta.get("versions", []):
                    if v.get("filename") == primary:
                        board_optimized = v.get("prompt", {}).get("optimized", "")
                        if not panels:
                            panels = v.get("panels", [])
        if req.mode != "v2" and not panels:
            raise HTTPException(status_code=400, detail="缺少故事板 panels，无法生成视频提示词")

        user_msg = (
            f"故事板名：{req.scene_key}\n"
            f"色调风格段：{board_optimized}\n"
            f"panels（9格）：{panels}\n"
            f"分镜计划 JSON：\n{_json_block(req.shot_plan or target.get('shot_plan') or board.get('shot_plan'))}\n"
            f"剧情摘要：{board.get('story_summary', '')}\n"
            f"本场冲突/主题：{board.get('conflict_summary', '')}\n"
            f"剧本台词/动作行：{req.script_segment or board.get('script_segment', '')}"
        )
        template_key = _template_key("video", req.mode)
        prompt = _generate_prompt(api_key, templates.get(template_key, VIDEO_SYSTEM), user_msg)
        # 解析分段并写入 pipeline.json 的 video_parts
        _save_video_parts(project_dir, req.scene_key, prompt, req.mode, req.page, req.output_id)
        return {"prompt": prompt, "raw": prompt}

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")
