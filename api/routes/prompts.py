import math
import re
import json
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
This is an empty environment reference board: no people, no characters, no face, no body, no hands, no silhouettes, no reflections of people.
Focus on the location itself: architecture, furniture, props, materials, lighting, spatial layout.
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

STORYBOARD_V2_SYSTEM = """你是专业影视导演分镜设计师。根据剧本段落、角色/场景参考信息，生成一张专业影视分镜板（storyboard sheet）提示词。

整体为黑白铅笔线稿 / 手绘草图风格，画面规整，像导演工作用的分镜设计图。

【基础信息】
- 集数：根据剧本段落自动识别
- 题材：根据项目内容自动概括
- 本场冲突 / 主题：根据剧本段落提炼
- 场景：根据输入场景名称填写
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
- 说明栏内容包含：景别 / 机位、动作描述、台词；如果没有台词就写“台词：无”
- 下半部分左侧为“俯视位置图”
- 下半部分右侧为“全景场景图”
- 页脚标注：本张剧情摘要、镜头数量、总时长、页码（如第1张/共2张）

【拆分原则】
1. 优先保证动作连续
2. 优先保证空间关系清楚
3. 优先保证前后因果明确
4. 优先保证本张分镜板总时长不超过15秒
5. 如果剧情太长，不要硬塞，超出部分自动划到下一张分镜板
6. 每一张图都应形成一个局部叙事单元，有明确的开始、推进和落点
7. 分页位置优先断在：动作完成之后、关键信息说完之后、视线变化或情绪落点之后、冲突节点暂时成立之后
8. 不要在动作中间最尴尬的位置强行截断，除非这是刻意制造悬念

【镜头拆分逻辑】
请按剧情节奏自动拆分，但优先遵循以下顺序：
1. 建立场景空间
2. 主要角色进入或行动开始
3. 角色发现问题 / 目标 / 危险
4. 冲突升级或动作变化
5. 关键动作 / 关键信息出现
6. 结果落点或情绪落点

注意：如果完整走完这 6 步会超过 15 秒，只保留能落在本张 15 秒内的镜头，剩余步骤自动延续到下一张分镜板。当前图不要试图讲完所有内容。

【每格分镜要求】
- 明确景别：远景 / 全景 / 中景 / 近景 / 特写
- 明确机位：正面 / 侧面 / 背面 / 过肩 / 俯拍 / 仰拍
- 明确动作：角色正在做什么，不要只画站着
- 明确方向：角色看向哪里、走向哪里、攻击哪里、躲避哪里
- 明确空间：前景、中景、远景关系清楚
- 镜头之间要连续，不要每一格像独立插画
- 不要把画面做成角色海报，要像能指导拍摄的分镜草图

【人物表现】
- 人物面部采用导演分镜草图式简化处理
- 不需要清晰五官
- 可以使用留白脸、弱化五官、简单表情线
- 不要写实肖像感
- 不要精细刻画眼睛、鼻子、嘴巴
- 优先表现身体姿态、动作方向、角色站位和镜头调度
- 只有关键情绪镜头中，才允许用少量表情线表现惊讶、愤怒、恐惧或犹豫
- 角色之间通过服装轮廓、身形、站位、编号或简单标记区分，不依赖精细脸部

【俯视位置图要求】
下半部分左侧绘制“俯视位置图”：使用简洁平面示意图风格，标出主要场景结构、主要角色站位、移动路径、关键道具 / 障碍物 / 高地 / 出入口；使用编号或简单标记区分角色，并带简单图例。只绘制当前这张分镜板中涉及到的空间调度。

【全景场景图要求】
下半部分右侧绘制“全景场景图”：作为整场戏或本段戏的 establishing shot / master shot，展示完整场景空间、主要角色相对位置、关键环境结构、本张冲突发生的位置关系。

【风格要求】
- 黑白铅笔草图
- 手绘 storyboard 风格
- 电影导演分镜稿
- 粗细线结合
- 动态线条清楚
- 分栏规整
- 黑色边框
- 中文说明栏清晰
- 整体像专业影视制作前期分镜板
- 不要彩色
- 不要照片感
- 不要厚涂
- 不要精修插画
- 不要动漫海报感
- 不要角色立绘感
- 不要过度细节化人物脸部

【优先级】
最高优先级：单张总时长不超过15秒、版式完整、镜头数量正确、空间关系清楚、动作连续、人物脸部简化、中文信息尽量清晰、整体像导演分镜板。

【避免】
不要把每格画成独立海报；不要让人物位置前后矛盾；不要让角色突然换方向；不要让场景结构每格都变；不要画精致脸部特写；不要使用彩色；不要生成真实照片风格；不要出现多余人物；不要出现乱码文字；不要漏掉底部俯视位置图和全景场景图；不要把超过15秒的剧情硬塞进一张图。

返回完整填充后的提示词文本，同时在末尾附上 JSON：
---PANELS---
[{"index":1,"timecode":"0.0-2.5s","shot":"...","camera":"...","action":"...","dialogue":"台词：..."}]
"""

VIDEO_SYSTEM = """你是视频提示词生成专家，严格套用 v2 结构化镜头格式。

输入：
- 故事板色调段（来自 prompt.optimized）
- panels（9格，每格含 shot + action）
- 剧本台词/动作行

输出：将9格按情绪节拍拆成2-3段，每段格式：

画幅规定：生成 16:9 横屏视频，保持横版电影构图，不要竖屏、方图或短视频竖版裁切。

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

VIDEO_V2_SYSTEM = """你是视频提示词生成专家，根据 v2 专业影视分镜板生成视频分段提示词。

输入：
- v2 分镜板提示词或故事板色调段
- panels（5-6 个镜头为主，每个镜头含 timecode / shot / camera / action / dialogue）
- 剧本台词/动作行

输出：按 v2 分镜板的镜头顺序拆成连续视频分段，每段不超过15秒。不要假设一定是9格。

画幅规定：生成 9:16 竖屏视频，按手机竖屏构图重新组织镜头，保留当前 v2 分镜板的叙事顺序与空间关系，不要输出横屏或方图构图。

每段格式：
---PART{n}---
分段时长：{总秒数}s
参考：共享角色图、共享场景图、当前 v2 分镜板图
镜头序列：
c{编号},{时长}s,（{timecode}，{shot}，{camera}）
(空间:{场景名})
(姿态:{{角色A}}-{动作基底})
(位置:{{角色A}}-{位置与运动方向})
(情绪:{{角色A}}-{情绪词} {强度}/10)
{散文段：景别+镜头运动+动作连续性+台词；画面不要出现任何文字字幕}

规则：
- 严格沿用 v2 分镜板的 5-6 镜头节奏
- 每段总时长不超过15秒
- 如果 panels 已经分页，按当前页生成当前视频分段
- 保持角色站位、运动方向、空间关系连续
- 不要把 v2 改写成九宫格逻辑
- 返回所有分段，每段用 ---PART{n}--- 分隔。"""

VIDEO_OUTPUT_GUARD = """

输出硬性限制：生成视频必须无 BGM、无背景音乐、无配乐；画面必须无字幕、无标题、无说明文字、无水印、无歌词、无任何屏幕文字。不要生成字幕轨，不要在画面中显示台词文本。
Hard requirement: no BGM, no background music, no music track; no subtitles, no captions, no title cards, no on-screen text, no watermark, no lyrics."""

# 内置默认值常量，供 pipeline.py 延迟加载
_BUILTIN_DEFAULTS = {
    "character": CHARACTER_SYSTEM,
    "scene": SCENE_SYSTEM,
    "prop": PROP_SYSTEM,
    "storyboard_v1": STORYBOARD_SYSTEM,
    "storyboard_v2": STORYBOARD_V2_SYSTEM,
    "video_v1": VIDEO_SYSTEM,
    "video_v2": VIDEO_V2_SYSTEM,
}


class GenerateRequest(BaseModel):
    type: str  # character | scene | prop | storyboard | video
    project_name: str = ""
    project_path: str = ""
    board_version: str = "v1"   # 故事板/视频版本标识，如 "v1"/"v2"
    name: Optional[str] = None
    appearance_seed: Optional[str] = None
    scene_key: Optional[str] = None
    board_id: Optional[str] = None
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
    board_id: Optional[str] = None
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
    board_id: Optional[str] = None
    part: Optional[int] = None
    draft_prompt: str


class StoryboardRouteRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    board_version: str


class SceneAnalysisRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    scene_key: str


class StoryboardPlanRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    scene_key: str
    board_version: str = "v2"


class LockStoryboardPlanRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    scene_key: str
    board_version: str = "v2"


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


def _scene_template_with_no_people_guard(system: str) -> str:
    guard = (
        "\n\n硬性限制：这是纯场景/空环境参考图，只允许出现空间、建筑、家具、道具、材质和光线；"
        "禁止出现任何人物、角色、脸、身体、手、背影、剪影、镜中人物或人形轮廓。"
    )
    if "禁止出现任何人物" in system:
        return system
    return system.rstrip() + guard


def video_prompt_with_output_guard(prompt: str) -> str:
    if "Hard requirement: no BGM" in prompt or "输出硬性限制：生成视频必须无 BGM" in prompt:
        return prompt
    return prompt.rstrip() + VIDEO_OUTPUT_GUARD


def _video_template_with_output_guard(system: str) -> str:
    if "无 BGM" in system and "无字幕" in system:
        return system
    return system.rstrip() + VIDEO_OUTPUT_GUARD


def _get_scene(data: dict, board_version: str, scene_key: str) -> dict | None:
    return data.get("storyboards", {}).get(board_version, {}).get(scene_key)


def _iter_version_scenes(data: dict, scene_key: str):
    for version, scenes in (data.get("storyboards") or {}).items():
        if isinstance(scenes, dict) and isinstance(scenes.get(scene_key), dict):
            yield version, scenes[scene_key]


def _get_source_scene(data: dict, scene_key: str) -> dict | None:
    source = (data.get("source_scenes") or {}).get(scene_key)
    if isinstance(source, dict):
        return source
    for _, scene in _iter_version_scenes(data, scene_key):
        return scene
    return None


def _new_unplanned_scene(scene_key: str, source_scene: dict, board_version: str) -> dict:
    layout = "director_sheet_15s" if board_version == "v2" else "nine_grid"
    return {
        **source_scene,
        "source_scene_key": scene_key,
        "scene_analysis": source_scene.get("scene_analysis", {}),
        "storyboard_plan": source_scene.get("storyboard_plan", {}),
        "layout": layout,
        "boards": [],
        "draft_prompt": "",
        "status": "unplanned",
        "board_task_id": None,
        "video_parts": [],
    }


def _get_board(data: dict, board_version: str, scene_key: str, board_id: str | None = None) -> dict | None:
    scene = _get_scene(data, board_version, scene_key)
    if not scene:
        return None
    boards = scene.get("boards")
    if isinstance(boards, list) and boards:
        if board_id:
            return next((b for b in boards if b.get("board_id") == board_id), None)
        return boards[0]
    return scene


def _sync_scene_from_first_board(scene: dict) -> None:
    boards = scene.get("boards")
    if not isinstance(boards, list) or not boards:
        scene.setdefault("draft_prompt", "")
        scene.setdefault("status", "unplanned")
        scene.setdefault("board_task_id", None)
        scene.setdefault("video_parts", [])
        return
    first = boards[0]
    scene["draft_prompt"] = first.get("draft_prompt", "")
    scene["status"] = first.get("status", "needed")
    scene["board_task_id"] = first.get("board_task_id")
    scene["video_parts"] = first.get("video_parts", [])


def _extract_json_payload(raw: str):
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"raw": raw}


def _apply_scene_analysis(data: dict, scene_key: str, analysis: dict) -> None:
    if isinstance(data.get("source_scenes"), dict) and isinstance(data["source_scenes"].get(scene_key), dict):
        data["source_scenes"][scene_key]["scene_analysis"] = analysis
    for _, scene in _iter_version_scenes(data, scene_key):
        scene["scene_analysis"] = analysis


def _storyboard_planning_system(board_version: str) -> str:
    if board_version == "v1":
        return (
            "你是影视九宫格故事板规划师。请基于导演分析，为当前场景生成 v1 规划，只返回 JSON，不要解释。"
            "JSON 格式：{\"boards\":[{\"covered_text\":\"...\",\"shot_count\":9,\"estimated_duration\":30,"
            "\"prompt_seed\":\"...\",\"plan\":{...},\"asset_refs\":{\"characters\":[\"...\"],\"scene\":\"...\",\"props\":[\"...\"]}}]}。"
            "covered_text 必须摘取原文关键句，不超过120字，不要只写抽象概述。"
            "v1 只生成一张 3x3 九宫格故事板，用 9 格压缩整场戏的起承转合、核心事件、情绪转折和悬疑落点。"
            "必须覆盖导演分析中的核心事件和全部信息揭示点。"
            "plan 中应包含 grid、shot_sequence、emotion_arc、spatial_anchors。shot_sequence 用 9 个短句。"
            "保持 JSON 紧凑，不要复述完整剧本，不要生成最终图像提示词。"
        )
    return (
        "你是专业影视导演分镜规划师。请基于导演分析，为当前场景生成 v2 规划，只返回 JSON，不要解释。"
        "JSON 格式：{\"boards\":[{\"covered_text\":\"...\",\"shot_count\":5,\"estimated_duration\":12,"
        "\"prompt_seed\":\"...\",\"plan\":{...},\"asset_refs\":{\"characters\":[\"...\"],\"scene\":\"...\",\"props\":[\"...\"]}}]}。"
        "covered_text 必须摘取原文中本页覆盖的关键句，不超过120字，不要只写抽象概述。"
        "v2 是导演分镜分页路线：每张板只覆盖 15 秒以内的连续剧情，每张建议 5-6 个镜头，剧情过长必须拆成多张。"
        "必须覆盖导演分析 reveals 中的每个信息揭示点；不同揭示点不能用笼统的“苦衷/解释”带过。"
        "每张 plan 中应包含 shots、page_break_reason、spatial_continuity、emotion_beat。"
        "shots 只写 5-6 个短句，每句包含景别/机位/动作/台词要点，不要展开成长段。"
        "保持 JSON 紧凑，不要复述完整剧本，不要生成最终图像提示词。"
    )


def _analysis_splits(analysis: dict) -> list[str]:
    candidates = analysis.get("v2_15s_split") or analysis.get("page_breaks") or []
    if isinstance(candidates, str):
        candidates = [candidates]
    result = []
    for item in candidates:
        if isinstance(item, dict):
            text = item.get("content") or item.get("summary") or "；".join(
                str(v) for v in item.values() if v
            )
        else:
            text = str(item)
        text = text.strip()
        if text:
            result.append(text)
    return result


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _infer_props_for_text(assets: dict, text: str) -> list[str]:
    if not text:
        return []
    generic_tokens = {"邮件", "照片", "小乐", "婉瑜", "江宁", "女士", "先生"}
    props = []
    for name in (assets.get("props") or {}):
        clean_name = name or ""
        tokens = [t for t in re.split(r"[（()）+、/·\\s]+", clean_name) if len(t) >= 2]
        bigrams = [clean_name[i:i + 2] for i in range(max(0, len(clean_name) - 1))]
        keyword_hit = any(t not in generic_tokens and t in text for t in tokens + bigrams)
        if name and (name in text or any(t in text for t in tokens) or keyword_hit):
            props.append(name)
    return props


def _normalize_asset_refs(source_scene: dict, plan_item: dict, assets: dict) -> dict:
    raw_refs = plan_item.get("asset_refs") if isinstance(plan_item.get("asset_refs"), dict) else {}
    characters = _as_list(plan_item.get("characters") or raw_refs.get("characters") or source_scene.get("characters_in_scene"))
    scene_name = plan_item.get("scene_location") or raw_refs.get("scene") or source_scene.get("scene_location") or ""
    props = _as_list(plan_item.get("props") or raw_refs.get("props"))
    if not props:
        text = "\n".join(str(v) for v in (
            plan_item.get("covered_text", ""),
            plan_item.get("prompt_seed", ""),
            json.dumps(plan_item.get("plan", {}), ensure_ascii=False),
        ) if v)
        props = _infer_props_for_text(assets, text)
    return {
        "characters": characters,
        "scene": scene_name,
        "props": props,
    }


def _asset_refs_for_board(scene: dict | None, board: dict | None) -> dict:
    scene = scene or {}
    board = board or {}
    refs = board.get("asset_refs") if isinstance(board.get("asset_refs"), dict) else {}
    return {
        "characters": _as_list(board.get("characters") or refs.get("characters") or scene.get("characters_in_scene")),
        "scene": board.get("scene_location") or refs.get("scene") or scene.get("scene_location") or "",
        "props": _as_list(board.get("props") or refs.get("props")),
    }


def _asset_prompt_context(project_dir: Path, refs: dict) -> dict:
    characters = []
    for char_name in refs.get("characters") or []:
        optimized = pl.get_prompt_optimized(project_dir, "characters", char_name)
        characters.append({"name": char_name, "appearance": optimized or char_name})
    scene_name = refs.get("scene") or ""
    scene_optimized = pl.get_prompt_optimized(project_dir, "scenes_props", scene_name) if scene_name else ""
    props = []
    for prop_name in refs.get("props") or []:
        optimized = pl.get_prompt_optimized(project_dir, "scenes_props", prop_name)
        props.append({"name": prop_name, "appearance": optimized or prop_name})
    return {
        "asset_refs": refs,
        "characters": characters,
        "scene": {"name": scene_name, "appearance": scene_optimized or scene_name},
        "props": props,
    }


def _plan_single_v2_board(api_key: str, source_scene: dict, scene_key: str, assets: dict,
                          analysis: dict, split_text: str, page: int, total_pages: int) -> dict | None:
    system = (
        "你是专业影视导演分镜规划师。只为一个 v2 分镜板分页生成规划。"
        "只返回一个 JSON 对象，不要解释。格式："
        "{\"covered_text\":\"原文关键句摘录，不超过120字\",\"shot_count\":5,\"estimated_duration\":12,"
        "\"prompt_seed\":\"一句话概括本页\",\"plan\":{\"shots\":[\"景别-机位-动作-台词要点\"],"
        "\"page_break_reason\":\"...\",\"spatial_continuity\":\"...\",\"emotion_beat\":\"...\"},"
        "\"asset_refs\":{\"characters\":[\"...\"],\"scene\":\"...\",\"props\":[\"...\"]}}。"
        "shots 必须 5-6 个短句；本页总时长不超过15秒；不要生成最终图像提示词。"
    )
    user_msg = (
        f"场景Key：{scene_key}\n"
        f"场景标题：{source_scene.get('script_title', '')}\n"
        f"页码：第{page}页/共{total_pages}页\n"
        f"可用角色资产：{list((assets.get('characters') or {}).keys())}\n"
        f"可用场景资产：{list((assets.get('scenes') or {}).keys())}\n"
        f"可用道具资产：{list((assets.get('props') or {}).keys())}\n"
        f"导演分析：{json.dumps(analysis, ensure_ascii=False)}\n"
        f"本页应覆盖的节拍：{split_text}\n"
        f"原文：\n{source_scene.get('script_segment', '')}"
    )
    raw = llm.generate_prompt(api_key, system, user_msg)
    parsed = _extract_json_payload(raw)
    if not isinstance(parsed, dict) or not parsed.get("covered_text"):
        return None
    parsed.setdefault("prompt_seed", split_text)
    parsed.setdefault("estimated_duration", 15)
    return parsed


def _plan_v2_boards_by_split(api_key: str, source_scene: dict, scene_key: str, assets: dict, analysis: dict) -> list[dict]:
    splits = _analysis_splits(analysis)
    if not splits:
        return []
    boards = []
    total_pages = len(splits)
    for idx, split_text in enumerate(splits, 1):
        item = _plan_single_v2_board(api_key, source_scene, scene_key, assets, analysis, split_text, idx, total_pages)
        if not item:
            return []
        boards.append(item)
    return boards


def _archive_existing_boards(scene: dict, reason: str) -> None:
    boards = scene.get("boards")
    if not isinstance(boards, list) or not boards:
        return
    if not any(
        b.get("draft_prompt") or b.get("board_task_id") or b.get("result_url") or b.get("video_parts")
        for b in boards if isinstance(b, dict)
    ):
        return
    import datetime
    scene.setdefault("archived_boards", []).append({
        "reason": reason,
        "archived_at": datetime.datetime.now().isoformat(),
        "boards": boards,
    })


def _make_board_from_plan(scene_key: str, board_version: str, page: int, total_pages: int,
                          source_scene: dict, plan_item: dict, assets: dict | None = None) -> dict:
    layout = "director_sheet_15s" if board_version == "v2" else "nine_grid"
    default_shots = 5 if board_version == "v2" else 9
    board_id = plan_item.get("board_id") or f"{scene_key}_{board_version}_p{page:02d}"
    covered_text = plan_item.get("covered_text") or source_scene.get("script_segment", "")
    prompt_seed = plan_item.get("prompt_seed") or plan_item.get("summary") or covered_text
    plan = plan_item.get("plan") or {k: v for k, v in plan_item.items() if k not in {
        "board_id", "covered_text", "prompt_seed", "draft_prompt", "status"
    }}
    plan_shots = plan.get("shots") if isinstance(plan, dict) else None
    shot_count = len(plan_shots) if isinstance(plan_shots, list) and plan_shots else plan_item.get("shot_count") or default_shots
    asset_refs = _normalize_asset_refs(source_scene, plan_item, assets or {})
    return {
        "board_id": board_id,
        "source_scene_key": scene_key,
        "page": page,
        "total_pages": total_pages,
        "layout": plan_item.get("layout") or layout,
        "shot_count": shot_count,
        "estimated_duration": plan_item.get("estimated_duration"),
        "covered_text": covered_text,
        "characters": asset_refs["characters"],
        "scene_location": asset_refs["scene"],
        "props": asset_refs["props"],
        "asset_refs": asset_refs,
        "prompt_seed": prompt_seed,
        "plan": plan,
        "draft_prompt": "",
        "status": "planned",
        "board_task_id": None,
        "result_url": None,
        "video_parts": [],
    }


def _ensure_storyboard_can_generate(board: dict | None) -> None:
    if board is None:
        raise HTTPException(status_code=404, detail="故事板不存在")
    if board.get("status") != "locked":
        raise HTTPException(status_code=409, detail="故事板规划尚未锁定，不能生成最终提示词")


def _save_draft_prompt(project_dir, category: str, name: str, prompt: str,
                       board_version: str = "v1", board_id: str | None = None):
    try:
        data = pl.read_pipeline(project_dir)
        if category == "storyboard":
            scene = _get_scene(data, board_version, name)
            board = _get_board(data, board_version, name, board_id)
            if board is not None:
                board["draft_prompt"] = prompt
                board["status"] = "drafted"
                if scene is not None:
                    _sync_scene_from_first_board(scene)
                pl.write_pipeline(project_dir, data)
        else:
            asset = data.get("assets", {}).get(category, {}).get(name)
            if asset:
                asset["draft_prompt"] = prompt
                asset["status"] = "drafted"
                pl.write_pipeline(project_dir, data)
    except Exception:
        pass


def _save_video_parts(project_dir, scene_key: str, raw_prompt: str,
                      board_version: str = "v1", board_id: str | None = None):
    data = pl.read_pipeline(project_dir)
    scene = _get_scene(data, board_version, scene_key)
    board = _get_board(data, board_version, scene_key, board_id)
    if not scene or not board:
        return
    _parse_video_parts_into_scene(board, video_prompt_with_output_guard(raw_prompt))
    _sync_scene_from_first_board(scene)
    pl.write_pipeline(project_dir, data)


def _parse_video_parts_into_scene(scene: dict, raw_prompt: str):
    parts = re.split(r'---PART[0-9]+---', raw_prompt)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        parts = [raw_prompt.strip()]
    video_parts = []
    for i, p in enumerate(parts, 1):
        p = video_prompt_with_output_guard(p)
        durations = re.findall(r'c[0-9]+[，,]\s*([0-9]+(?:\.[0-9]+)?)\s*s', p)
        total_sec = math.ceil(sum(float(d) for d in durations)) if durations else 0
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
            system = _scene_template_with_no_people_guard(_get_template(templates, "scene"))
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
            data = pl.read_pipeline(project_dir)
            board = _get_board(data, item.board_version, item.scene_key, item.board_id)
            if board is None:
                return {"type": "storyboard", "scene_key": item.scene_key, "board_version": item.board_version,
                        "board_id": item.board_id, "ok": False, "error": "故事板不存在"}
            if board.get("status") != "locked":
                return {"type": "storyboard", "scene_key": item.scene_key, "board_version": item.board_version,
                        "board_id": item.board_id or board.get("board_id"), "ok": False,
                        "error": "故事板规划尚未锁定，不能生成最终提示词"}
            scene = _get_scene(data, item.board_version, item.scene_key)
            script_segment = item.script_segment or (board or {}).get("covered_text", "")
            prompt_seed = (board or {}).get("prompt_seed", "")
            asset_context = _asset_prompt_context(project_dir, _asset_refs_for_board(scene, board))
            user_msg = (
                f"场景：{item.scene_key}\n"
                f"分镜板ID：{item.board_id or (board or {}).get('board_id', '')}\n"
                f"导演分析：{json.dumps((scene or {}).get('scene_analysis', {}), ensure_ascii=False)}\n"
                f"锁定规划：{json.dumps((board or {}).get('plan', {}), ensure_ascii=False)}\n"
                f"规划种子：{prompt_seed}\n"
                f"锁定资产引用：{json.dumps(asset_context['asset_refs'], ensure_ascii=False)}\n"
                f"角色信息：{asset_context['characters']}\n"
                f"场景色调：{asset_context['scene']}\n"
                f"道具信息：{asset_context['props']}\n"
                f"剧本段落：{script_segment}"
            )
            system = _get_template(templates, "storyboard", item.board_version)
            prompt = await llm.generate_prompt_async(api_key, system, user_msg)
            return {"type": "storyboard", "scene_key": item.scene_key, "board_version": item.board_version,
                    "board_id": item.board_id or (board or {}).get("board_id"), "prompt": prompt, "ok": True}

        elif item.type == "video":
            data = pl.read_pipeline(project_dir)
            board = _get_board(data, item.board_version, item.scene_key, item.board_id) or {}
            board_meta_dir = project_dir / "storyboards" / (item.scene_key or "")
            panels = item.panels or []
            board_optimized = ""
            if board_meta_dir.exists():
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
                f"分镜板ID：{item.board_id or board.get('board_id', '')}\n"
                f"色调风格段：{board_optimized}\n"
                f"panels（按当前版本分镜）：{panels}\n"
                f"剧本台词/动作行：{item.script_segment or board.get('covered_text', '')}"
            )
            system = _video_template_with_output_guard(_get_template(templates, "video", item.board_version))
            prompt = video_prompt_with_output_guard(await llm.generate_prompt_async(api_key, system, user_msg))
            return {"type": "video", "scene_key": item.scene_key, "board_version": item.board_version,
                    "board_id": item.board_id or board.get("board_id"), "prompt": prompt, "raw": prompt, "ok": True}

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
            board = _get_board(data, r["board_version"], r["scene_key"], r.get("board_id"))
            if board is not None:
                board["draft_prompt"] = r["prompt"]
                board["status"] = "drafted"
                if scene is not None:
                    _sync_scene_from_first_board(scene)
        elif r["type"] == "video":
            scene = _get_scene(data, r["board_version"], r["scene_key"])
            board = _get_board(data, r["board_version"], r["scene_key"], r.get("board_id"))
            if board is not None:
                _parse_video_parts_into_scene(board, r["raw"])
                if scene is not None:
                    _sync_scene_from_first_board(scene)

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


@router.post("/select-storyboard-route")
async def select_storyboard_route(req: StoryboardRouteRequest):
    if req.board_version not in ("v1", "v2"):
        raise HTTPException(status_code=400, detail="故事板生产线只能是 v1 或 v2")
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    data = pl.read_pipeline(project_dir)
    source_scenes = data.get("source_scenes") or {}
    if not source_scenes:
        raise HTTPException(status_code=400, detail="项目没有可规划的剧本场次")

    data["storyboard_route"] = req.board_version
    route_scenes = {}
    existing = (data.get("storyboards") or {}).get(req.board_version, {})
    for scene_key, source_scene in source_scenes.items():
        route_scenes[scene_key] = existing.get(scene_key) or _new_unplanned_scene(scene_key, source_scene, req.board_version)
    data["storyboards"] = {req.board_version: route_scenes}

    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"ok": True, "board_version": req.board_version, "scenes": len(route_scenes)}


@router.post("/analyze-scene")
async def analyze_scene(req: SceneAnalysisRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    data = pl.read_pipeline(project_dir)
    scene = _get_source_scene(data, req.scene_key)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    system = (
        "你是短剧影视导演。请对单场戏做场景导演分析，只返回 JSON，不要解释。"
        "字段包含 core_event, emotion_beats, action_beats, reveals, blocking, space_needs, page_breaks, v1_compression, v2_15s_split。"
    )
    user_msg = (
        f"场景Key：{req.scene_key}\n"
        f"场景标题：{scene.get('script_title', '')}\n"
        f"场景地点：{scene.get('scene_location', '')}\n"
        f"人物：{scene.get('characters_in_scene', [])}\n"
        f"原文：\n{scene.get('script_segment', '')}"
    )
    raw = llm.generate_prompt(api_key, system, user_msg)
    parsed = _extract_json_payload(raw)
    analysis = parsed if isinstance(parsed, dict) else {"items": parsed}
    _apply_scene_analysis(data, req.scene_key, analysis)
    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"analysis": analysis, "raw": raw}


@router.post("/plan-storyboards")
async def plan_storyboards(req: StoryboardPlanRequest):
    if req.board_version not in ("v1", "v2"):
        raise HTTPException(status_code=400, detail="故事板生产线只能是 v1 或 v2")
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    data = pl.read_pipeline(project_dir)
    source_scene = _get_source_scene(data, req.scene_key)
    if not source_scene:
        raise HTTPException(status_code=404, detail="场景不存在")

    if data.get("storyboard_route") != req.board_version:
        data["storyboard_route"] = req.board_version
        data["storyboards"] = {req.board_version: {}}
    data.setdefault("storyboards", {}).setdefault(req.board_version, {})
    scene = data["storyboards"][req.board_version].setdefault(
        req.scene_key,
        _new_unplanned_scene(req.scene_key, source_scene, req.board_version),
    )
    analysis = scene.get("scene_analysis") or source_scene.get("scene_analysis") or {}
    if not analysis:
        raise HTTPException(status_code=409, detail="请先生成 scene_analysis，再生成故事板规划")

    system = _storyboard_planning_system(req.board_version)
    user_msg = (
        f"版本：{req.board_version}\n"
        f"场景Key：{req.scene_key}\n"
        f"场景标题：{source_scene.get('script_title', '')}\n"
        f"可用角色资产：{list((data.get('assets', {}).get('characters') or {}).keys())}\n"
        f"可用场景资产：{list((data.get('assets', {}).get('scenes') or {}).keys())}\n"
        f"可用道具资产：{list((data.get('assets', {}).get('props') or {}).keys())}\n"
        f"导演分析：{json.dumps(analysis, ensure_ascii=False)}\n"
        f"原文：\n{source_scene.get('script_segment', '')}"
    )
    raw = llm.generate_prompt(api_key, system, user_msg)
    parsed = _extract_json_payload(raw)
    plan = parsed if isinstance(parsed, dict) else {"boards": parsed}
    plan_boards = plan.get("boards") if isinstance(plan.get("boards"), list) else []
    if not plan_boards:
        if req.board_version == "v2":
            plan_boards = _plan_v2_boards_by_split(api_key, source_scene, req.scene_key, data.get("assets", {}), analysis)
        if not plan_boards:
            raise HTTPException(status_code=502, detail="LLM 未返回有效的故事板规划 JSON，请重试或缩短当前场次")

    _archive_existing_boards(scene, "replan")
    boards = [
        _make_board_from_plan(req.scene_key, req.board_version, idx, len(plan_boards), source_scene, item, data.get("assets", {}))
        for idx, item in enumerate(plan_boards, 1)
        if isinstance(item, dict)
    ]
    scene["scene_analysis"] = analysis
    scene["storyboard_plan"] = scene.get("storyboard_plan") or {}
    scene["storyboard_plan"][req.board_version] = {"boards": plan_boards}
    scene["boards"] = boards
    _sync_scene_from_first_board(scene)
    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"plan": scene["storyboard_plan"][req.board_version], "boards": boards, "raw": raw}


@router.post("/lock-storyboard-plan")
async def lock_storyboard_plan(req: LockStoryboardPlanRequest):
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    data = pl.read_pipeline(project_dir)
    scene = _get_scene(data, req.board_version, req.scene_key)
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    boards = scene.get("boards") if isinstance(scene.get("boards"), list) else []
    if not boards:
        raise HTTPException(status_code=409, detail="当前场景还没有故事板规划")
    for board in boards:
        if board.get("status") in ("planned", "unplanned", "locked"):
            board["status"] = "locked"
    _sync_scene_from_first_board(scene)
    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()
    pl.write_pipeline(project_dir, data)
    return {"ok": True, "locked": sum(1 for b in boards if b.get("status") == "locked")}


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
        system = _scene_template_with_no_people_guard(_get_template(templates, "scene"))
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
        data = pl.read_pipeline(project_dir)
        board = _get_board(data, req.board_version, req.scene_key, req.board_id)
        scene = _get_scene(data, req.board_version, req.scene_key)
        _ensure_storyboard_can_generate(board)
        script_segment = req.script_segment or (board or {}).get("covered_text", "")
        prompt_seed = (board or {}).get("prompt_seed", "")
        asset_context = _asset_prompt_context(project_dir, _asset_refs_for_board(scene, board))
        user_msg = (
            f"场景：{req.scene_key}\n"
            f"分镜板ID：{req.board_id or (board or {}).get('board_id', '')}\n"
            f"导演分析：{json.dumps((scene or {}).get('scene_analysis', {}), ensure_ascii=False)}\n"
            f"锁定规划：{json.dumps((board or {}).get('plan', {}), ensure_ascii=False)}\n"
            f"规划种子：{prompt_seed}\n"
            f"锁定资产引用：{json.dumps(asset_context['asset_refs'], ensure_ascii=False)}\n"
            f"角色信息：{asset_context['characters']}\n"
            f"场景色调：{asset_context['scene']}\n"
            f"道具信息：{asset_context['props']}\n"
            f"剧本段落：{script_segment}"
        )
        system = _get_template(templates, "storyboard", req.board_version)
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "storyboard", req.scene_key, prompt, req.board_version, req.board_id)
        return {"prompt": prompt}

    elif req.type == "video":
        data = pl.read_pipeline(project_dir)
        board = _get_board(data, req.board_version, req.scene_key, req.board_id) or {}
        board_meta_dir = project_dir / "storyboards" / (req.scene_key or "")
        panels = req.panels or []
        board_optimized = ""
        if board_meta_dir.exists():
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
            f"分镜板ID：{req.board_id or board.get('board_id', '')}\n"
            f"色调风格段：{board_optimized}\n"
            f"panels（按当前版本分镜）：{panels}\n"
            f"剧本台词/动作行：{req.script_segment or board.get('covered_text', '')}"
        )
        system = _video_template_with_output_guard(_get_template(templates, "video", req.board_version))
        prompt = video_prompt_with_output_guard(llm.generate_prompt(api_key, system, user_msg))
        _save_video_parts(project_dir, req.scene_key, prompt, req.board_version, req.board_id)
        return {"prompt": prompt, "raw": prompt}

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")


@router.put("/update-draft")
async def update_draft(req: UpdateDraftRequest):
    project_dir = _resolve_project_dir(req.project_path, req.project_name)
    data = pl.read_pipeline(project_dir)

    if req.category == "storyboard":
        scene = _get_scene(data, req.board_version, req.scene_key)
        board = _get_board(data, req.board_version, req.scene_key, req.board_id)
        if scene is None or board is None:
            raise HTTPException(status_code=404, detail="故事板场景不存在")
        board["draft_prompt"] = req.draft_prompt
        board["status"] = "drafted"
        _sync_scene_from_first_board(scene)

    elif req.category == "video_part":
        scene = _get_scene(data, req.board_version, req.scene_key)
        board = _get_board(data, req.board_version, req.scene_key, req.board_id)
        if scene is None or board is None:
            raise HTTPException(status_code=404, detail="故事板场景不存在")
        for vp in board.get("video_parts", []):
            if vp["part"] == req.part:
                vp["draft_prompt"] = req.draft_prompt
                vp["video_status"] = "drafted"
                _sync_scene_from_first_board(scene)
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
