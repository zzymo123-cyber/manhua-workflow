import json
import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from api import llm, pipeline as pl
from api.routes.settings import get_api_key

router = APIRouter()


class ChatRequest(BaseModel):
    project_name: str
    message: str
    history: list[dict] = []
    current_scene_key: Optional[str] = None


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


def _build_system_prompt(project_name: str, scene_key: Optional[str]) -> str:
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
    for k, b in pipeline_data.get("storyboards", {}).items():
        draft = b.get("draft_prompt", "")
        vp = b.get("video_parts", [])
        board_summary.append({
            "name": k,
            "title": b.get("script_title", k),
            "board_status": b.get("board_status", "needed"),
            "draft_preview": draft[:100] + ("..." if len(draft) > 100 else ""),
            "video_parts": [{"part": p["part"], "status": p.get("video_status", "needed")} for p in vp],
        })

    # 当前选中场景传完整详情
    scene_context = ""
    if scene_key:
        storyboard = pipeline_data.get("storyboards", {}).get(scene_key, {})
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
故事板状态：{storyboard.get('board_status', 'unknown')}
提示词草稿：{storyboard.get('draft_prompt', '')}
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
        "project": pipeline_data.get("project", project_name),
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

def _get_full_prompt(project_name: str, target: str, name: str) -> str:
    """读取指定资产的完整 draft_prompt"""
    project_dir = pl.get_project_root(project_name)
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
        return data.get("storyboards", {}).get(name, {}).get("draft_prompt", "")
    return ""


# ── 执行 actions ──────────────────────────────────────────────────────────────

def _execute_actions(project_name: str, actions: list[dict]) -> list[dict]:
    """
    执行写操作类 action，跳过 get_full_prompt（由两步循环处理）。
    返回每个 action 的执行结果，供前端显示工具调用小条。
    """
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
                data["storyboards"][name]["draft_prompt"] = value
                ok = True
            elif target == "video_part" and name:
                part_num = action.get("part")
                for p in data.get("storyboards", {}).get(name, {}).get("video_parts", []):
                    if p["part"] == part_num:
                        p["draft_prompt"] = value
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
            if target == "video" and name and field:
                data["storyboards"].setdefault(name, {})[f"video_{field}"] = value
                changed = True
                results.append({"action": act, "name": name, "ok": True,
                                 "label": f"已更新「{name}」{field}={value}"})

        elif act == "generate_prompt":
            # 调用提示词生成路由逻辑（复用现有函数）
            target = action.get("target")
            result_label = _do_generate_prompt(project_name, target, name)
            results.append({"action": act, "target": target, "name": name, "ok": True,
                             "label": result_label})

        elif act == "submit_task":
            target = action.get("target")
            part = action.get("part")
            ok, label = _do_submit_task(project_name, data, target, name, part)
            if ok:
                changed = True
            results.append({"action": act, "target": target, "name": name, "ok": ok, "label": label})

    if changed:
        data["updated_at"] = datetime.datetime.now().isoformat()
        pl.write_pipeline(project_dir, data)

    return results


def _do_generate_prompt(project_name: str, target: str, name: str) -> str:
    """调用 LLM 生成提示词并写入 draft_prompt，返回操作描述"""
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
        req = GenerateRequest(type=target, project_name=project_name, name=name, appearance_seed=seed)
        # generate_prompt_endpoint 是 async，在同步上下文里用 asyncio.run 调用
        result = asyncio.run(prompts_module.generate_prompt_endpoint(req))
        return f"已重新生成「{name}」提示词"
    except Exception as e:
        return f"生成失败：{e}"


def _do_submit_task(project_name: str, data: dict, target: str, name: str, part) -> tuple[bool, str]:
    """提交任务到 Vidu/Wetoken，返回 (成功, 描述)"""
    from api import vidu, wetoken
    project_dir = pl.get_project_root(project_name)
    vidu_key = get_api_key("VIDU_API_KEY")
    wetoken_key = get_api_key("WETOKEN_API_KEY")

    try:
        if target == "character":
            prompt = data.get("assets", {}).get("characters", {}).get(name, {}).get("draft_prompt", "")
            if not prompt:
                return False, f"「{name}」没有提示词，无法提交"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="3:4")
            data["assets"]["characters"][name]["status"] = "submitted"
            data["assets"]["characters"][name]["task_id"] = result["task_id"]
            return True, f"角色「{name}」已提交生成，等待完成"

        elif target == "scene":
            prompt = data.get("assets", {}).get("scenes", {}).get(name, {}).get("draft_prompt", "")
            if not prompt:
                return False, f"「{name}」没有提示词，无法提交"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="16:9")
            data["assets"]["scenes"][name]["status"] = "submitted"
            data["assets"]["scenes"][name]["task_id"] = result["task_id"]
            return True, f"场景「{name}」已提交生成，等待完成"

        elif target == "prop":
            prompt = data.get("assets", {}).get("props", {}).get(name, {}).get("draft_prompt", "")
            if not prompt:
                return False, f"「{name}」没有提示词，无法提交"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="1:1")
            data["assets"]["props"][name]["status"] = "submitted"
            data["assets"]["props"][name]["task_id"] = result["task_id"]
            return True, f"道具「{name}」已提交生成，等待完成"

        elif target == "storyboard":
            prompt = data.get("storyboards", {}).get(name, {}).get("draft_prompt", "")
            if not prompt:
                return False, f"「{name}」没有提示词，无法提交"
            result = vidu.submit_image_task(vidu_key, prompt, [], ratio="16:9")
            data["storyboards"][name]["board_status"] = "submitted"
            data["storyboards"][name]["board_task_id"] = result["task_id"]
            return True, f"故事板「{name}」已提交生成，等待完成"

        elif target == "video_part":
            board = data.get("storyboards", {}).get(name, {})
            prompt = ""
            for p in board.get("video_parts", []):
                if p["part"] == part:
                    prompt = p.get("draft_prompt", p.get("prompt", ""))
            if not prompt:
                return False, f"「{name}」Part {part} 没有提示词"
            duration = board.get("video_duration", 10)
            task_id = wetoken.submit_video_task(wetoken_key, prompt, [], duration=duration, ratio="16:9")
            for p in board.get("video_parts", []):
                if p["part"] == part:
                    p["video_status"] = "submitted"
                    p["video_task_id"] = task_id
            return True, f"已提交视频「{name}」Part {part}"

        return False, f"未知 target: {target}"
    except Exception as e:
        return False, f"提交失败：{e}"


# ── 两步循环 ──────────────────────────────────────────────────────────────────

def _run_agent(api_key: str, messages: list[dict], system_prompt: str,
               project_name: str) -> tuple[str, list[dict], list[dict]]:
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
            full = _get_full_prompt(project_name, target, name)
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

    tool_results = _execute_actions(project_name, actions)
    return reply, actions, tool_results


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    system_prompt = _build_system_prompt(req.project_name, req.current_scene_key)

    history = req.history[-20:]
    messages = history + [{"role": "user", "content": req.message}]

    reply, actions, tool_results = _run_agent(api_key, messages, system_prompt, req.project_name)

    # has_writes: 告诉前端是否需要 refreshStatus
    has_writes = any(r.get("ok") for r in tool_results)

    return {
        "reply": reply,
        "tool_results": tool_results,   # 工具调用小条
        "has_writes": has_writes,
    }
