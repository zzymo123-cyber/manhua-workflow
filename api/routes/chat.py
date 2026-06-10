import json
import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from api import llm, pipeline as pl, vidu, wetoken
from api.routes.settings import get_api_key
from api.routes.tasks import (
    _prepare_image_resubmit_after_success,
    _prepare_video_resubmit_after_success,
    _video_generation_prompt,
    _video_ratio_for_version,
    _video_reference_paths,
)

router = APIRouter()


class ChatRequest(BaseModel):
    project_name: str
    message: str
    history: list[dict] = []
    current_scene_key: Optional[str] = None
    active_board_version: Optional[str] = None
    current_board_id: Optional[str] = None


# ── 摘要构建 ──────────────────────────────────────────────────────────────────

def _asset_summary(assets: dict) -> list[dict]:
    """资产摘要（扁平模型，无版本）"""
    result = []
    for name, info in assets.items():
        draft = info.get("draft_prompt", "")
        result.append({
            "name": name,
            "status": info.get("status", "needed"),
            "template_variant": info.get("template_variant", "default"),
            "draft_preview": draft[:80] + ("..." if len(draft) > 80 else ""),
        })
    return result


def _build_system_prompt(project_name: str, scene_key: Optional[str],
                         active_board_version: Optional[str] = None,
                         current_board_id: Optional[str] = None) -> str:
    project_dir = pl.get_project_root(project_name)
    try:
        pipeline_data = pl.read_pipeline(project_dir)
    except Exception:
        pipeline_data = {}

    assets = pipeline_data.get("assets", {})
    char_summary = _asset_summary(assets.get("characters", {}))
    scene_summary = _asset_summary(assets.get("scenes", {}))
    prop_summary = _asset_summary(assets.get("props", {}))

    board_summary = []
    for board_version, scene_key_item, scene in _iter_storyboard_scenes(pipeline_data):
        boards = []
        for board in _scene_boards(scene):
            draft = board.get("draft_prompt", "")
            boards.append({
                "board_id": board.get("board_id", ""),
                "page": board.get("page", 1),
                "total_pages": board.get("total_pages", 1),
                "layout": board.get("layout", scene.get("layout", "")),
                "shot_count": board.get("shot_count"),
                "estimated_duration": board.get("estimated_duration"),
                "status": board.get("status", "needed"),
                "draft_preview": draft[:80] + ("..." if len(draft) > 80 else ""),
                "video_parts": [
                    {"part": vp.get("part"), "status": vp.get("video_status", "needed")}
                    for vp in board.get("video_parts", [])
                ],
            })
        board_summary.append({
            "board_version": board_version,
            "scene_key": scene_key_item,
            "title": scene.get("script_title", scene_key_item),
            "boards": boards,
        })

    # 当前选中场景传完整详情
    scene_context = ""
    if scene_key:
        board_version = active_board_version or "v1"
        storyboard = _get_scene(pipeline_data, board_version, scene_key) or {}
        current_board = _find_board(storyboard, current_board_id)
        meta = pl.get_meta(project_dir, "storyboards", scene_key)
        panels = []
        if meta:
            primary = meta.get("primary_image")
            for v in meta.get("versions", []):
                if v.get("filename") == primary:
                    panels = v.get("panels", [])
        scene_context = f"""
【当前选中场景（完整详情）】
场景：{scene_key}
当前故事板版本：{board_version}
当前分镜板ID：{current_board.get('board_id', '') if current_board else ''}
当前分镜板：{json.dumps(current_board or {}, ensure_ascii=False)}
panels：{json.dumps(panels, ensure_ascii=False)}
"""

    # submitted 状态提示
    submitted_items = []
    for name, asset in assets.get("characters", {}).items():
        if asset.get("status") == "submitted":
            submitted_items.append(f"角色「{name}」")
    for name, asset in assets.get("scenes", {}).items():
        if asset.get("status") == "submitted":
            submitted_items.append(f"场景「{name}」")
    for name, asset in assets.get("props", {}).items():
        if asset.get("status") == "submitted":
            submitted_items.append(f"道具「{name}」")
    submitted_hint = ""
    if submitted_items:
        submitted_hint = f"\n【注意】以下资产正在生成中：{', '.join(submitted_items)}。修改其草稿不影响当前进行中的任务，需告知用户。\n"

    summary = json.dumps({
        "project": pipeline_data.get("project", project_name),
        "characters": char_summary,
        "scenes": scene_summary,
        "props": prop_summary,
        "storyboards": board_summary,
    }, ensure_ascii=False, indent=2)

    return f"""你是漫剧工作流助手。当前项目摘要如下：

数据模型说明：
- 角色/场景/道具为扁平模型（每个资产只有一份，无版本概念）
- 故事板为 storyboards[board_version][scene_key].boards[]，v1/v2 共用源场景与资产库
- v1 通常是一场一张 9 格故事板；v2 会按 15 秒以内拆成多张 5-6 镜头分镜板
- video_parts 挂在具体 board 下，必须带 board_version 和 board_id 才能精确操作

{summary}
{submitted_hint}{scene_context}
你可以查询进度、修改提示词草稿、生成提示词、提交任务、选定故事板版本、添加故事板版本。
所有写操作通过 actions 数组返回，纯查询时 actions 为空数组。

【可用 action 列表】

读取完整提示词（当需要在原有基础上修改时，先用此 action 获取全文）：
{{"action":"get_full_prompt","target":"character|scene|prop","name":"名称"}}
{{"action":"get_full_prompt","target":"storyboard","name":"场景key","board_version":"v2","board_id":"s01_01_v2_p01"}}
{{"action":"get_full_prompt","target":"video_part","name":"场景key","board_version":"v2","board_id":"s01_01_v2_p01","part":1}}

修改草稿提示词：
{{"action":"update_draft_prompt","target":"character|scene|prop","name":"名称","value":"完整新提示词"}}
{{"action":"update_draft_prompt","target":"storyboard","name":"场景key","board_version":"v2","board_id":"s01_01_v2_p01","value":"完整新提示词"}}
{{"action":"update_draft_prompt","target":"video_part","name":"场景key","board_version":"v2","board_id":"s01_01_v2_p01","part":1,"value":"完整新提示词"}}

重新生成提示词（调 LLM 重新生成，自动写入草稿）：
{{"action":"generate_prompt","target":"character|scene|prop","name":"名称","template_variant":"default"}}

提交任务到生成队列：
{{"action":"submit_task","target":"character|scene|prop","name":"名称"}}
{{"action":"submit_task","target":"storyboard","name":"场景key","board_version":"v2","board_id":"s01_01_v2_p01"}}
{{"action":"submit_task","target":"video_part","name":"场景key","board_version":"v2","board_id":"s01_01_v2_p01","part":1}}

【重要规则】
- 需要修改某个资产的提示词时，必须先用 get_full_prompt 获取完整内容，再基于原文修改
- get_full_prompt 是中间步骤，不要告诉用户"我去读取一下"，直接在内部处理
- submit_task 会消耗 API 配额，直接执行，不需要再次确认
- 角色/场景/道具无版本概念，不需要指定 version_id
- 故事板必须优先使用 board_version 和 board_id；不要再使用旧的 board_versions/version_id 结构
- 返回合法 JSON，不能有其他内容：{{"reply":"...","actions":[...]}}"""


# ── 读取完整提示词 ─────────────────────────────────────────────────────────────

def _find_board_version(board: dict, version_id: int) -> dict | None:
    for bv in board.get("board_versions", []):
        if bv.get("id") == version_id:
            return bv
    return None


def _uses_new_storyboards(storyboards: dict) -> bool:
    if not storyboards:
        return False
    first = next(iter(storyboards.values()))
    return not (isinstance(first, dict) and any(k in first for k in ("episode", "board_versions", "script_title")))


def _iter_storyboard_scenes(data: dict):
    storyboards = data.get("storyboards", {})
    if _uses_new_storyboards(storyboards):
        for board_version, scenes in storyboards.items():
            if not isinstance(scenes, dict):
                continue
            for scene_key, scene in scenes.items():
                if isinstance(scene, dict):
                    yield board_version, scene_key, scene
    else:
        for scene_key, scene in storyboards.items():
            if isinstance(scene, dict):
                yield "legacy", scene_key, scene


def _get_scene(data: dict, board_version: str, scene_key: str) -> dict | None:
    storyboards = data.get("storyboards", {})
    if _uses_new_storyboards(storyboards):
        return storyboards.get(board_version, {}).get(scene_key)
    return storyboards.get(scene_key)


def _scene_boards(scene: dict) -> list[dict]:
    boards = scene.get("boards")
    if isinstance(boards, list) and boards:
        return boards
    if isinstance(scene.get("board_versions"), list):
        return scene.get("board_versions", [])
    return [scene]


def _find_board(scene: dict, board_id: str | None = None, version_id: int = 0) -> dict | None:
    if not scene:
        return None
    boards = scene.get("boards")
    if isinstance(boards, list) and boards:
        if board_id:
            return next((b for b in boards if b.get("board_id") == board_id), None)
        return boards[0]
    if "board_versions" in scene:
        return _find_board_version(scene, version_id)
    return scene


def _sync_scene_from_first_board(scene: dict) -> None:
    boards = scene.get("boards")
    if not isinstance(boards, list) or not boards:
        return
    first = boards[0]
    scene["draft_prompt"] = first.get("draft_prompt", "")
    scene["status"] = first.get("status", "needed")
    scene["board_task_id"] = first.get("board_task_id")
    scene["video_parts"] = first.get("video_parts", [])


def _get_full_prompt(project_name: str, target: str, name: str, version_id: int = 0,
                     board_version: str = "v1", board_id: str | None = None,
                     part: int | None = None) -> str:
    """读取指定资产的完整 draft_prompt"""
    project_dir = pl.get_project_root(project_name)
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return ""

    if target == "character":
        return data.get("assets", {}).get("characters", {}).get(name, {}).get("draft_prompt", "")
    elif target == "scene":
        return data.get("assets", {}).get("scenes", {}).get(name, {}).get("draft_prompt", "")
    elif target == "prop":
        return data.get("assets", {}).get("props", {}).get(name, {}).get("draft_prompt", "")
    elif target == "storyboard":
        scene = _get_scene(data, board_version, name) or {}
        bv = _find_board(scene, board_id, version_id)
        return bv.get("draft_prompt", "") if bv else ""
    elif target == "video_part":
        scene = _get_scene(data, board_version, name) or {}
        bv = _find_board(scene, board_id, version_id)
        if bv:
            for vp in bv.get("video_parts", []):
                if vp.get("part") == (part or version_id):
                    return vp.get("draft_prompt", "")
        return ""
    return ""


# ── 执行 actions ──────────────────────────────────────────────────────────────

def _execute_actions(project_name: str, actions: list[dict]) -> list[dict]:
    results = []
    if not actions:
        return results

    project_dir = pl.get_project_root(project_name)
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return results

    changed = False

    for action in actions:
        act = action.get("action")
        name = action.get("name")

        if act == "get_full_prompt":
            continue

        elif act == "update_draft_prompt":
            target = action.get("target")
            value = action.get("value", "")
            version_id = action.get("version_id", 0)
            board_version = action.get("board_version") or action.get("version") or "v1"
            board_id = action.get("board_id")
            ok = False
            if target in ("character", "scene", "prop"):
                cat_map = {"character": "characters", "scene": "scenes", "prop": "props"}
                asset = data.get("assets", {}).get(cat_map[target], {}).get(name)
                if asset:
                    asset["draft_prompt"] = value
                    asset["status"] = "drafted"
                    ok = True
            elif target == "storyboard":
                scene = _get_scene(data, board_version, name)
                if scene:
                    bv = _find_board(scene, board_id, version_id)
                    if bv:
                        bv["draft_prompt"] = value
                        bv["status"] = "drafted"
                        _sync_scene_from_first_board(scene)
                        ok = True
            elif target == "video_part":
                part = action.get("part")
                scene = _get_scene(data, board_version, name)
                if scene:
                    bv = _find_board(scene, board_id, version_id)
                    if bv:
                        for vp in bv.get("video_parts", []):
                            if vp.get("part") == part:
                                vp["draft_prompt"] = value
                                vp["video_status"] = "drafted"
                                _sync_scene_from_first_board(scene)
                                ok = True
                                break
            if ok:
                changed = True
                label = f"已修改「{name}」" + (f" v{version_id}" if target in ("storyboard", "video_part") else "")
                results.append({"action": act, "target": target, "name": name, "ok": True, "label": label})
            else:
                results.append({"action": act, "target": target, "name": name, "ok": False,
                                 "label": f"修改失败：未找到「{name}」"})

        elif act == "generate_prompt":
            target = action.get("target")
            template_variant = action.get("template_variant", "default")
            result_label = _do_generate_prompt(project_name, target, name, template_variant)
            results.append({"action": act, "target": target, "name": name, "ok": True,
                             "label": result_label})

        elif act == "submit_task":
            target = action.get("target")
            version_id = action.get("version_id", 0)
            board_version = action.get("board_version") or action.get("version") or "v1"
            board_id = action.get("board_id")
            part = action.get("part")
            ok, label = _do_submit_task(project_name, data, target, name, version_id, part, board_version, board_id)
            if ok:
                changed = True
            results.append({"action": act, "target": target, "name": name, "ok": ok, "label": label})

        elif act == "select_version":
            target = action.get("target")
            version_id = action.get("version_id", 0)
            ok, label = _do_select_version(data, target, name, version_id)
            if ok:
                changed = True
            results.append({"action": act, "target": target, "name": name, "ok": ok, "label": label})

        elif act == "add_version":
            target = action.get("target")
            template_variant = action.get("template_variant", "default")
            ok, label = _do_add_version(data, target, name, template_variant)
            if ok:
                changed = True
            results.append({"action": act, "target": target, "name": name, "ok": ok, "label": label})

    if changed:
        data["updated_at"] = datetime.datetime.now().isoformat()
        pl.write_pipeline(project_dir, data)

    return results


def _do_generate_prompt(project_name: str, target: str, name: str,
                         template_variant: str = "default") -> str:
    """调用 LLM 生成提示词并写入 draft_prompt"""
    from api.routes import prompts as prompts_module
    from api.routes.prompts import GenerateRequest
    import asyncio

    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = pl.get_project_root(project_name)
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return f"生成失败：无法读取项目"

    assets = data.get("assets", {})
    seed = ""
    if target == "character":
        seed = assets.get("characters", {}).get(name, {}).get("seed", "")
    elif target in ("scene", "prop"):
        seed = (assets.get("scenes", {}) or assets.get("props", {})).get(name, {}).get("seed", "")

    try:
        req = GenerateRequest(type=target, project_name=project_name, name=name,
                                appearance_seed=seed, template_variant=template_variant)
        result = asyncio.run(prompts_module.generate_prompt_endpoint(req))
        return f"已重新生成「{name}」提示词"
    except Exception as e:
        return f"生成失败：{e}"


def _do_submit_task(project_name: str, data: dict, target: str, name: str,
                      version_id: int, part=None, board_version: str = "v1",
                      board_id: str | None = None) -> tuple[bool, str]:
    """提交任务到 Vidu/Wetoken，返回 (成功, 描述)"""
    project_dir = pl.get_project_root(project_name)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    try:
        if target == "character":
            asset = data.get("assets", {}).get("characters", {}).get(name)
            if asset:
                prompt = asset.get("draft_prompt", "")
                if not prompt:
                    return False, f"「{name}」没有提示词"
                result = vidu.submit_image_task(vidu_key, prompt, [], ratio="3:4")
                now = datetime.datetime.now().isoformat()
                _prepare_image_resubmit_after_success(project_dir, asset, now)
                asset["status"] = "submitted"
                asset["task_id"] = result["task_id"]
                return True, f"角色「{name}」已提交"

        elif target == "scene":
            asset = data.get("assets", {}).get("scenes", {}).get(name)
            if asset:
                prompt = asset.get("draft_prompt", "")
                if not prompt:
                    return False, f"「{name}」没有提示词"
                result = vidu.submit_image_task(vidu_key, prompt, [], ratio="16:9")
                now = datetime.datetime.now().isoformat()
                _prepare_image_resubmit_after_success(project_dir, asset, now)
                asset["status"] = "submitted"
                asset["task_id"] = result["task_id"]
                return True, f"场景「{name}」已提交"

        elif target == "prop":
            asset = data.get("assets", {}).get("props", {}).get(name)
            if asset:
                prompt = asset.get("draft_prompt", "")
                if not prompt:
                    return False, f"「{name}」没有提示词"
                result = vidu.submit_image_task(vidu_key, prompt, [], ratio="1:1")
                now = datetime.datetime.now().isoformat()
                _prepare_image_resubmit_after_success(project_dir, asset, now)
                asset["status"] = "submitted"
                asset["task_id"] = result["task_id"]
                return True, f"道具「{name}」已提交"

        elif target == "storyboard":
            scene = _get_scene(data, board_version, name) or {}
            bv = _find_board(scene, board_id, version_id)
            if bv:
                prompt = bv.get("draft_prompt", "")
                if not prompt:
                    return False, f"故事板「{name}」{board_version}/{board_id or version_id} 没有提示词"
                result = vidu.submit_image_task(vidu_key, prompt, [], ratio="16:9")
                now = datetime.datetime.now().isoformat()
                _prepare_image_resubmit_after_success(project_dir, bv, now)
                bv["status"] = "submitted"
                bv["board_task_id"] = result["task_id"]
                _sync_scene_from_first_board(scene)
                return True, f"故事板「{name}」{board_version}/{board_id or version_id} 已提交"

        elif target == "video_part":
            scene = _get_scene(data, board_version, name) or {}
            bv = _find_board(scene, board_id, version_id)
            if bv:
                for vp in bv.get("video_parts", []):
                    if vp.get("part") == part:
                        duration = vp.get("duration") or 10
                        prompt = vp.get("draft_prompt", vp.get("prompt", ""))
                        if not prompt:
                            return False, f"「{name}」Part {part} 没有提示词"
                        prompt = _video_generation_prompt(prompt)
                        ratio = _video_ratio_for_version(board_version)
                        image_paths = _video_reference_paths(
                            project_dir, data, board_version, name, board_id, []
                        )
                        task_id = wetoken.submit_video_task(
                            wetoken_key, prompt, image_paths,
                            duration=duration, ratio=ratio, project_dir=project_dir,
                        )
                        now = datetime.datetime.now().isoformat()
                        _prepare_video_resubmit_after_success(project_dir, vp, now)
                        vp["video_status"] = "submitted"
                        vp["video_task_id"] = task_id
                        vp["draft_prompt"] = prompt
                        vp["prompt"] = prompt
                        vp["ratio"] = ratio
                        _sync_scene_from_first_board(scene)
                        return True, f"已提交视频「{name}」Part {part}"

        return False, f"未找到目标: {target} {name}"
    except Exception as e:
        return False, f"提交失败：{e}"


def _do_select_version(data: dict, target: str, name: str, version_id: int) -> tuple[bool, str]:
    """在 pipeline data 上选定故事板版本"""
    if target != "storyboard":
        return False, f"只有故事板支持版本选定，{target} 不支持"

    board = data.get("storyboards", {}).get(name)
    if not board:
        return False, f"故事板 {name} 不存在"
    bv = _find_board_version(board, version_id)
    if not bv:
        return False, f"版本 {version_id} 不存在"
    if bv.get("status") != "completed":
        return False, f"版本 {version_id} 未完成，不能选定"
    board["selected_board_version"] = version_id
    return True, f"已选定故事板「{name}」v{version_id}"


def _do_add_version(data: dict, target: str, name: str,
                      template_variant: str = "default") -> tuple[bool, str]:
    """在 pipeline data 上添加新故事板版本"""
    if target != "storyboard":
        return False, f"只有故事板支持添加版本，{target} 不支持"

    board = data.get("storyboards", {}).get(name)
    if not board:
        return False, f"故事板 {name} 不存在"
    versions = board.setdefault("board_versions", [])
    new_id = max((v["id"] for v in versions), default=-1) + 1
    versions.append({
        "id": new_id, "draft_prompt": "", "status": "needed",
        "board_task_id": None, "template_variant": template_variant,
        "video_parts": [],
    })
    return True, f"已为故事板「{name}」添加 v{new_id}"


# ── 两步循环 ──────────────────────────────────────────────────────────────────

def _run_agent(api_key: str, messages: list[dict], system_prompt: str,
               project_name: str) -> tuple[str, list[dict], list[dict]]:
    result = llm.chat_with_agent(api_key, messages, system_prompt)
    actions = result.get("actions", [])

    # 检查是否有 get_full_prompt
    get_actions = [a for a in actions if a.get("action") == "get_full_prompt"]
    if get_actions:
        fetched = []
        for a in get_actions:
            target = a.get("target")
            name = a.get("name")
            version_id = a.get("version_id", 0)
            board_version = a.get("board_version") or a.get("version") or "v1"
            board_id = a.get("board_id")
            part = a.get("part")
            full = _get_full_prompt(project_name, target, name, version_id, board_version, board_id, part)
            fetched.append(f"【{target}「{name}」{board_version}/{board_id or version_id} 完整提示词】\n{full}")

        augmented_messages = messages + [
            {"role": "assistant", "content": result.get("_raw", json.dumps(result, ensure_ascii=False))},
            {"role": "user", "content": "以下是你请求的完整提示词内容：\n\n" + "\n\n".join(fetched) + "\n\n请基于以上内容完成修改操作。"}
        ]
        result2 = llm.chat_with_agent(api_key, augmented_messages, system_prompt)
        actions = result2.get("actions", [])
        reply = result2.get("reply", "")
    else:
        reply = result.get("reply", "")

    tool_results = _execute_actions(project_name, actions)
    return reply, actions, tool_results


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    system_prompt = _build_system_prompt(
        req.project_name,
        req.current_scene_key,
        req.active_board_version,
        req.current_board_id,
    )

    history = req.history[-20:]
    messages = history + [{"role": "user", "content": req.message}]

    reply, actions, tool_results = _run_agent(api_key, messages, system_prompt, req.project_name)

    has_writes = any(r.get("ok") for r in tool_results)

    return {
        "reply": reply,
        "tool_results": tool_results,
        "has_writes": has_writes,
    }
