import json
import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from api import llm, pipeline as pl
from api.routes.settings import get_api_key
from api.storyboard_versions import (
    get_storyboard_target,
    set_storyboard_submitted,
    storyboard_image_path,
    sync_legacy_v1_from_output,
)
from api.video_params import VideoParamError, normalize_video_duration, normalize_video_ratio

router = APIRouter()


class ChatRequest(BaseModel):
    project_name: str = ""
    project_path: str = ""
    message: str
    history: list[dict] = []
    current_scene_key: Optional[str] = None


def _require_project_dir(project_name: str = "", project_path: str = ""):
    project_dir = pl.resolve_project_dir(project_name, project_path)
    if not (project_dir / "pipeline.json").exists():
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_dir}")
    return project_dir


# ── 摘要构建 ──────────────────────────────────────────────────────────────────

def _asset_summary(assets: dict) -> list[dict]:
    result = []
    for name, info in assets.items():
        draft = info.get("draft_prompt", "")
        result.append({
            "name": name,
            "status": info.get("status", "needed"),
            "draft_preview": draft[:100] + ("..." if len(draft) > 100 else ""),
        })
    return result


def _build_system_prompt(project_name: str, project_path: str, scene_key: Optional[str]) -> str:
    project_dir = pl.resolve_project_dir(project_name, project_path)
    project_ref = project_path or project_name
    try:
        pipeline_data = pl.read_pipeline(project_dir)
    except Exception:
        pipeline_data = {}

    assets = pipeline_data.get("assets", {})
    char_summary = _asset_summary(assets.get("characters", {}))
    scene_summary = _asset_summary(assets.get("scenes", {}))
    prop_summary = _asset_summary(assets.get("props", {}))

    board_summary = []
    for k, b in pipeline_data.get("storyboards", {}).items():
        target = get_storyboard_target(b, "v1")
        draft = target.get("draft_prompt", b.get("draft_prompt", ""))
        vp = target.get("video_parts", b.get("video_parts", []))
        board_summary.append({
            "name": k,
            "title": b.get("script_title", k),
            "board_status": target.get("board_status", b.get("board_status", "needed")),
            "draft_preview": draft[:100] + ("..." if len(draft) > 100 else ""),
            "video_parts": [{"part": p.get("part"), "status": p.get("video_status", "needed")} for p in vp],
        })

    # 当前选中场景传完整详情
    scene_context = ""
    if scene_key:
        storyboard = pipeline_data.get("storyboards", {}).get(scene_key, {})
        target = get_storyboard_target(storyboard, "v1") if storyboard else {}
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
故事板状态：{target.get('board_status', storyboard.get('board_status', 'unknown'))}
提示词草稿：{target.get('draft_prompt', storyboard.get('draft_prompt', ''))}
panels：{json.dumps(panels, ensure_ascii=False)}
"""

    # submitted 状态提示
    submitted_items = []
    for name, info in assets.get("characters", {}).items():
        if info.get("status") == "submitted":
            submitted_items.append(f"角色「{name}」")
    for name, info in assets.get("scenes", {}).items():
        if info.get("status") == "submitted":
            submitted_items.append(f"场景「{name}」")
    submitted_hint = ""
    if submitted_items:
        submitted_hint = f"\n【注意】以下资产正在生成中：{', '.join(submitted_items)}。修改其草稿不影响当前进行中的任务，需告知用户。\n"

    summary = json.dumps({
        "project": pipeline_data.get("project", project_ref),
        "characters": char_summary,
        "scenes": scene_summary,
        "props": prop_summary,
        "storyboards": board_summary,
    }, ensure_ascii=False, indent=2)

    return f"""你是漫剧工作流助手。当前项目摘要如下（draft_preview 为提示词前100字）：

{summary}
{submitted_hint}{scene_context}
你可以查询进度、修改提示词草稿、生成提示词、提交任务、调整参数。
所有写操作通过 actions 数组返回，纯查询时 actions 为空数组。

【可用 action 列表】

读取完整提示词（当需要在原有基础上修改时，先用此 action 获取全文）：
{{"action":"get_full_prompt","target":"character|scene|prop|storyboard","name":"名称"}}

修改草稿提示词：
{{"action":"update_draft_prompt","target":"character|scene|prop|storyboard","name":"名称","value":"完整新提示词"}}
视频分段：{{"action":"update_draft_prompt","target":"video_part","name":"场景key","part":1,"value":"完整新提示词"}}

重新生成提示词（调 LLM 重新生成，自动写入草稿）：
{{"action":"generate_prompt","target":"character|scene|prop","name":"名称"}}

提交任务到生成队列：
{{"action":"submit_task","target":"character|scene|prop|storyboard","name":"名称"}}
视频分段：{{"action":"submit_task","target":"video_part","name":"场景key","part":1}}

调整视频参数：
{{"action":"update_param","target":"video","name":"场景key","field":"duration|ratio","value":"值"}}

【重要规则】
- 需要修改某个资产的提示词时，必须先用 get_full_prompt 获取完整内容，再基于原文修改
- get_full_prompt 是中间步骤，不要告诉用户"我去读取一下"，直接在内部处理
- submit_task 会消耗 API 配额，直接执行，不需要再次确认
- 返回合法 JSON，不能有其他内容：{{"reply":"...","actions":[...]}}"""


# ── 读取完整提示词 ─────────────────────────────────────────────────────────────

def _get_full_prompt(project_name: str, project_path: str, target: str, name: str) -> str:
    """读取指定资产的完整 draft_prompt"""
    project_dir = pl.resolve_project_dir(project_name, project_path)
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return ""
    assets = data.get("assets", {})
    if target == "character":
        return assets.get("characters", {}).get(name, {}).get("draft_prompt", "")
    elif target == "scene":
        return assets.get("scenes", {}).get(name, {}).get("draft_prompt", "")
    elif target == "prop":
        return assets.get("props", {}).get(name, {}).get("draft_prompt", "")
    elif target == "storyboard":
        board = data.get("storyboards", {}).get(name, {})
        return get_storyboard_target(board, "v1").get("draft_prompt", "") if board else ""
    return ""


# ── 执行 actions ──────────────────────────────────────────────────────────────

def _execute_actions(project_name: str, project_path: str, actions: list[dict]) -> list[dict]:
    """
    执行写操作类 action，跳过 get_full_prompt（由两步循环处理）。
    返回每个 action 的执行结果，供前端显示工具调用小条。
    """
    results = []
    if not actions:
        return results

    project_dir = pl.resolve_project_dir(project_name, project_path)
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return results

    changed = False

    for action in actions:
        act = action.get("action")
        name = action.get("name")

        if act == "get_full_prompt":
            # 两步循环阶段已处理，这里跳过
            continue

        elif act == "update_draft_prompt":
            target = action.get("target")
            value = action.get("value", "")
            ok = False
            if target == "character" and name and name in data.get("assets", {}).get("characters", {}):
                data["assets"]["characters"][name]["draft_prompt"] = value
                ok = True
            elif target == "scene" and name and name in data.get("assets", {}).get("scenes", {}):
                data["assets"]["scenes"][name]["draft_prompt"] = value
                ok = True
            elif target == "prop" and name and name in data.get("assets", {}).get("props", {}):
                data["assets"]["props"][name]["draft_prompt"] = value
                ok = True
            elif target == "storyboard" and name and name in data.get("storyboards", {}):
                board = data["storyboards"][name]
                get_storyboard_target(board, "v1")["draft_prompt"] = value
                sync_legacy_v1_from_output(board)
                ok = True
            elif target == "video_part" and name:
                part_num = action.get("part")
                board = data.get("storyboards", {}).get(name, {})
                board_target = get_storyboard_target(board, "v1") if board else {}
                for p in board_target.get("video_parts", []):
                    if p.get("part") == part_num:
                        p["draft_prompt"] = value
                        sync_legacy_v1_from_output(board)
                        ok = True
            if ok:
                changed = True
                results.append({"action": act, "target": target, "name": name, "ok": True,
                                 "label": f"已修改「{name}」提示词"})
            else:
                results.append({"action": act, "target": target, "name": name, "ok": False,
                                 "label": f"修改失败：未找到「{name}」"})

        elif act == "update_param":
            target = action.get("target")
            field = action.get("field")
            value = action.get("value")
            ok = target == "video" and name in data.get("storyboards", {}) and field in {"duration", "ratio"}
            if ok:
                try:
                    value = normalize_video_duration(value) if field == "duration" else normalize_video_ratio(value)
                except VideoParamError as exc:
                    results.append({"action": act, "name": name, "ok": False,
                                     "label": f"参数更新失败：{exc}"})
                    continue
                board = data["storyboards"][name]
                get_storyboard_target(board, "v1")[f"video_{field}"] = value
                sync_legacy_v1_from_output(board)
                changed = True
                results.append({"action": act, "name": name, "ok": True,
                                 "label": f"已更新「{name}」{field}={value}"})
            else:
                results.append({"action": act, "name": name, "ok": False,
                                 "label": f"参数更新失败：未找到「{name}」或字段不支持"})

        elif act == "generate_prompt":
            # 调用提示词生成路由逻辑（复用现有函数）
            target = action.get("target")
            ok, result_label = _do_generate_prompt(project_name, project_path, target, name)
            results.append({"action": act, "target": target, "name": name, "ok": ok,
                             "label": result_label})

        elif act == "submit_task":
            target = action.get("target")
            part = action.get("part")
            ok, label = _do_submit_task(project_name, project_path, data, target, name, part)
            if ok:
                changed = True
            results.append({"action": act, "target": target, "name": name, "ok": ok, "label": label})

    if changed:
        data["updated_at"] = datetime.datetime.now().isoformat()
        pl.write_pipeline(project_dir, data)

    return results


def _do_generate_prompt(project_name: str, project_path: str, target: str, name: str) -> tuple[bool, str]:
    """调用 LLM 生成提示词并写入 draft_prompt，返回操作描述"""
    from api.routes import prompts as prompts_module

    api_key = get_api_key("IDEALAB_API_KEY")
    if not api_key:
        return False, "生成失败：缺少 ideaLAB API Key"

    project_dir = pl.resolve_project_dir(project_name, project_path)
    try:
        data = pl.read_pipeline(project_dir)
    except Exception:
        return False, "生成失败：无法读取项目"

    assets = data.get("assets", {})
    category_by_target = {"character": "characters", "scene": "scenes", "prop": "props"}
    category = category_by_target.get(target)
    if not category:
        return False, f"生成失败：不支持的目标类型 {target}"
    item = assets.get(category, {}).get(name)
    if not item:
        return False, f"生成失败：未找到「{name}」"

    seed = item.get("seed", "")
    system_by_target = {
        "character": prompts_module.CHARACTER_SYSTEM,
        "scene": prompts_module.SCENE_SYSTEM,
        "prop": prompts_module.PROP_SYSTEM,
    }
    if target == "character":
        user_msg = f"角色名：{name}\n描述：{seed}"
    elif target == "scene":
        user_msg = f"场景名：{name}\n描述：{seed}"
    else:
        user_msg = f"道具名：{name}\n描述：{seed}"

    try:
        templates = pl.read_prompt_templates(project_dir)
        system = templates.get(target, system_by_target[target])
        prompt = prompts_module._generate_prompt(api_key, system, user_msg)
        prompts_module._save_draft_prompt(project_dir, category, name, prompt)
        return True, f"已重新生成「{name}」提示词"
    except Exception as e:
        return False, f"生成失败：{e}"


def _clear_fields(item: dict, fields: tuple[str, ...]):
    for field in fields:
        item.pop(field, None)


def _has_prompt(prompt: str) -> bool:
    return bool(prompt.strip())


def _relative_path(project_dir, path) -> str:
    return str(path.relative_to(project_dir)).replace("\\", "/")


def _default_reference_path(project_dir, category: str, name: str):
    return project_dir / category / name / f"{name}.png"


def _asset_reference_path(project_dir, data: dict, category: str, name: str, label: str) -> tuple[str | None, str | None]:
    info = data.get("assets", {}).get(category, {}).get(name)
    if not info or info.get("status") != "completed":
        return None, f"{label}「{name}」未完成"

    file_category = "characters" if category == "characters" else "scenes_props"
    path = pl.get_primary_image_path(project_dir, file_category, name) or _default_reference_path(project_dir, file_category, name)
    if not path.exists():
        return None, f"缺少参考图：{_relative_path(project_dir, path)}"
    return str(path), None


def _storyboard_reference_paths(project_dir, data: dict, board: dict) -> tuple[list[str], list[str]]:
    paths = []
    issues = []
    for char in board.get("characters_in_scene", []):
        path, issue = _asset_reference_path(project_dir, data, "characters", char, "角色")
        if issue:
            issues.append(issue)
        elif path:
            paths.append(path)

    scene_name = board.get("scene_location")
    if scene_name:
        category = "scenes" if scene_name in data.get("assets", {}).get("scenes", {}) else "props"
        path, issue = _asset_reference_path(project_dir, data, category, scene_name, "场景/道具")
        if issue:
            issues.append(issue)
        elif path:
            paths.append(path)

    return paths, issues


def _video_reference_paths(project_dir, data: dict, scene_key: str, board: dict) -> tuple[list[str], list[str]]:
    paths, issues = _storyboard_reference_paths(project_dir, data, board)
    target = get_storyboard_target(board, "v1")
    if target.get("board_status") != "completed":
        issues.append("故事板尚未完成")
    else:
        board_path = storyboard_image_path(project_dir, scene_key, "v1")
        if not board_path.exists():
            issues.append(f"缺少参考图：{_relative_path(project_dir, board_path)}")
        else:
            paths.append(str(board_path))
    return paths, issues


def _reference_issue_label(issues: list[str]) -> str:
    preview = "，".join(issues[:3])
    suffix = f" 等 {len(issues)} 项" if len(issues) > 3 else ""
    return f"提交失败：前置参考未完成：{preview}{suffix}"


def _do_submit_task(project_name: str, project_path: str, data: dict, target: str, name: str, part) -> tuple[bool, str]:
    """提交任务到 Vidu/Wetoken，返回 (成功, 描述)"""
    from api import vidu, wetoken
    project_dir = pl.resolve_project_dir(project_name, project_path)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    try:
        if target == "character":
            prompt = data.get("assets", {}).get("characters", {}).get(name, {}).get("draft_prompt", "")
            if not _has_prompt(prompt):
                return False, f"「{name}」没有提示词，无法提交"
            if not vidu_key:
                return False, "提交失败：缺少 Vidu API Key"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="3:4")
            data["assets"]["characters"][name]["status"] = "submitted"
            data["assets"]["characters"][name]["task_id"] = result["task_id"]
            _clear_fields(data["assets"]["characters"][name], ("error",))
            return True, f"角色「{name}」已提交生成，等待完成"

        elif target == "scene":
            prompt = data.get("assets", {}).get("scenes", {}).get(name, {}).get("draft_prompt", "")
            if not _has_prompt(prompt):
                return False, f"「{name}」没有提示词，无法提交"
            if not vidu_key:
                return False, "提交失败：缺少 Vidu API Key"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="16:9")
            data["assets"]["scenes"][name]["status"] = "submitted"
            data["assets"]["scenes"][name]["task_id"] = result["task_id"]
            _clear_fields(data["assets"]["scenes"][name], ("error",))
            return True, f"场景「{name}」已提交生成，等待完成"

        elif target == "prop":
            prompt = data.get("assets", {}).get("props", {}).get(name, {}).get("draft_prompt", "")
            if not _has_prompt(prompt):
                return False, f"「{name}」没有提示词，无法提交"
            if not vidu_key:
                return False, "提交失败：缺少 Vidu API Key"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="1:1")
            data["assets"]["props"][name]["status"] = "submitted"
            data["assets"]["props"][name]["task_id"] = result["task_id"]
            _clear_fields(data["assets"]["props"][name], ("error",))
            return True, f"道具「{name}」已提交生成，等待完成"

        elif target == "storyboard":
            board = data.get("storyboards", {}).get(name, {})
            board_target = get_storyboard_target(board, "v1") if board else {}
            prompt = board_target.get("draft_prompt", "")
            if not _has_prompt(prompt):
                return False, f"「{name}」没有提示词，无法提交"
            if not vidu_key:
                return False, "提交失败：缺少 Vidu API Key"
            image_paths, issues = _storyboard_reference_paths(project_dir, data, board)
            if issues:
                return False, _reference_issue_label(issues)
            result = vidu.submit_image_task(vidu_key, prompt, image_paths, ratio="16:9")
            set_storyboard_submitted(data["storyboards"][name], result["task_id"], "v1")
            return True, f"故事板「{name}」已提交生成，等待完成"

        elif target == "video_part":
            board = data.get("storyboards", {}).get(name, {})
            board_target = get_storyboard_target(board, "v1") if board else {}
            prompt = ""
            for p in board_target.get("video_parts", []):
                if p.get("part") == part:
                    prompt = p.get("draft_prompt", p.get("prompt", ""))
            if not _has_prompt(prompt):
                return False, f"「{name}」Part {part} 没有提示词"
            if not wetoken_key:
                return False, "提交失败：缺少 Wetoken API Key"
            image_paths, issues = _video_reference_paths(project_dir, data, name, board)
            if issues:
                return False, _reference_issue_label(issues)
            try:
                duration = normalize_video_duration(board_target.get("video_duration"), default=10)
                ratio = normalize_video_ratio(board_target.get("video_ratio"), default="16:9")
            except VideoParamError as exc:
                return False, f"提交失败：{exc}"
            task_id = wetoken.submit_video_task(
                wetoken_key, prompt, image_paths,
                duration=duration, ratio=ratio, project_dir=project_dir,
            )
            for p in board_target.get("video_parts", []):
                if p.get("part") == part:
                    p["video_status"] = "submitted"
                    p["video_task_id"] = task_id
                    _clear_fields(p, ("video_error", "video_download_error", "video_url", "local_path"))
            sync_legacy_v1_from_output(board)
            return True, f"已提交视频「{name}」Part {part}"

        return False, f"未知 target: {target}"
    except Exception as e:
        return False, f"提交失败：{e}"


# ── 两步循环 ──────────────────────────────────────────────────────────────────

def _run_agent(api_key: str, messages: list[dict], system_prompt: str,
               project_name: str, project_path: str) -> tuple[str, list[dict], list[dict]]:
    """
    两步循环：
    1. 第一次 LLM 调用
    2. 如果有 get_full_prompt action，读取完整提示词后再调一次
    返回 (reply, actions, tool_results)
    """
    result = llm.chat_with_agent(api_key, messages, system_prompt)
    actions = result.get("actions", [])

    # 检查是否有 get_full_prompt
    get_actions = [a for a in actions if a.get("action") == "get_full_prompt"]
    if get_actions:
        # 读取所有请求的完整提示词，拼成补充 context
        fetched = []
        for a in get_actions:
            target = a.get("target")
            name = a.get("name")
            full = _get_full_prompt(project_name, project_path, target, name)
            fetched.append(f"【{target}「{name}」完整提示词】\n{full}")

        # 第二次调用：把完整提示词作为 tool 结果注入
        augmented_messages = messages + [
            {"role": "assistant", "content": result.get("_raw", json.dumps(result, ensure_ascii=False))},
            {"role": "user", "content": "以下是你请求的完整提示词内容：\n\n" + "\n\n".join(fetched) + "\n\n请基于以上内容完成修改操作。"}
        ]
        result2 = llm.chat_with_agent(api_key, augmented_messages, system_prompt)
        actions = result2.get("actions", [])
        reply = result2.get("reply", "")
    else:
        reply = result.get("reply", "")

    tool_results = _execute_actions(project_name, project_path, actions)
    return reply, actions, tool_results


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="缺少 ideaLAB API Key，请先在设置中配置")
    _require_project_dir(req.project_name, req.project_path)
    system_prompt = _build_system_prompt(req.project_name, req.project_path, req.current_scene_key)

    history = req.history[-20:]
    messages = history + [{"role": "user", "content": req.message}]

    reply, actions, tool_results = _run_agent(api_key, messages, system_prompt, req.project_name, req.project_path)

    # has_writes: 告诉前端是否需要 refreshStatus
    has_writes = any(r.get("ok") for r in tool_results)

    return {
        "reply": reply,
        "tool_results": tool_results,   # 工具调用小条
        "has_writes": has_writes,
    }
