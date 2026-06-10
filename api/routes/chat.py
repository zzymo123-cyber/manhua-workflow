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
        board_versions = []
        for bv in b.get("board_versions", []):
            draft = bv.get("draft_prompt", "")
            vp_summary = []
            for vp in bv.get("video_parts", []):
                vp_summary.append({
                    "part": vp["part"],
                    "status": vp.get("video_status", "needed"),
                })
            board_versions.append({
                "id": bv["id"],
                "status": bv.get("status", "needed"),
                "template_variant": bv.get("template_variant", "default"),
                "draft_preview": draft[:80] + ("..." if len(draft) > 80 else ""),
                "video_parts": vp_summary,
            })
        board_summary.append({
            "name": k,
            "title": b.get("script_title", k),
            "selected_board_version": b.get("selected_board_version"),
            "board_versions": board_versions,
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
故事板版本：{json.dumps(storyboard.get('board_versions', []), ensure_ascii=False)}
selected_board_version：{storyboard.get('selected_board_version')}
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
- 故事板支持多版本（board_versions），每个版本内嵌套 video_parts
- video_parts 为扁平模型（每个分段只有一份，无版本概念）

{summary}
{submitted_hint}{scene_context}
你可以查询进度、修改提示词草稿、生成提示词、提交任务、选定故事板版本、添加故事板版本。
所有写操作通过 actions 数组返回，纯查询时 actions 为空数组。

【可用 action 列表】

读取完整提示词（当需要在原有基础上修改时，先用此 action 获取全文）：
{{"action":"get_full_prompt","target":"character|scene|prop","name":"名称"}}
{{"action":"get_full_prompt","target":"storyboard","name":"场景key","version_id":0}}
{{"action":"get_full_prompt","target":"video_part","name":"场景key","part":1,"version_id":0}}

修改草稿提示词：
{{"action":"update_draft_prompt","target":"character|scene|prop","name":"名称","value":"完整新提示词"}}
{{"action":"update_draft_prompt","target":"storyboard","name":"场景key","version_id":0,"value":"完整新提示词"}}
{{"action":"update_draft_prompt","target":"video_part","name":"场景key","part":1,"version_id":0,"value":"完整新提示词"}}

重新生成提示词（调 LLM 重新生成，自动写入草稿）：
{{"action":"generate_prompt","target":"character|scene|prop","name":"名称","template_variant":"default"}}

提交任务到生成队列：
{{"action":"submit_task","target":"character|scene|prop","name":"名称"}}
{{"action":"submit_task","target":"storyboard","name":"场景key","version_id":0}}
{{"action":"submit_task","target":"video_part","name":"场景key","part":1,"version_id":0}}

选定故事板版本（只能选定已完成的版本）：
{{"action":"select_version","target":"storyboard","name":"场景key","version_id":0}}

添加故事板版本：
{{"action":"add_version","target":"storyboard","name":"场景key","template_variant":"default"}}

【重要规则】
- 需要修改某个资产的提示词时，必须先用 get_full_prompt 获取完整内容，再基于原文修改
- get_full_prompt 是中间步骤，不要告诉用户"我去读取一下"，直接在内部处理
- submit_task 会消耗 API 配额，直接执行，不需要再次确认
- 角色/场景/道具无版本概念，不需要指定 version_id
- 故事板的 version_id 指向 board_versions 中的版本编号
- 返回合法 JSON，不能有其他内容：{{"reply":"...","actions":[...]}}"""


# ── 读取完整提示词 ─────────────────────────────────────────────────────────────

def _find_board_version(board: dict, version_id: int) -> dict | None:
    for bv in board.get("board_versions", []):
        if bv.get("id") == version_id:
            return bv
    return None


def _get_full_prompt(project_name: str, target: str, name: str, version_id: int = 0) -> str:
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
        board = data.get("storyboards", {}).get(name, {})
        bv = _find_board_version(board, version_id)
        return bv.get("draft_prompt", "") if bv else ""
    elif target == "video_part":
        board = data.get("storyboards", {}).get(name, {})
        bv = _find_board_version(board, version_id)
        if bv:
            for vp in bv.get("video_parts", []):
                if vp.get("part") == version_id:  # part number passed as version_id for video_part
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
            ok = False
            if target in ("character", "scene", "prop"):
                cat_map = {"character": "characters", "scene": "scenes", "prop": "props"}
                asset = data.get("assets", {}).get(cat_map[target], {}).get(name)
                if asset:
                    asset["draft_prompt"] = value
                    asset["status"] = "drafted"
                    ok = True
            elif target == "storyboard":
                board = data.get("storyboards", {}).get(name)
                if board:
                    bv = _find_board_version(board, version_id)
                    if bv:
                        bv["draft_prompt"] = value
                        bv["status"] = "drafted"
                        ok = True
            elif target == "video_part":
                part = action.get("part")
                board = data.get("storyboards", {}).get(name)
                if board:
                    bv = _find_board_version(board, version_id)
                    if bv:
                        for vp in bv.get("video_parts", []):
                            if vp.get("part") == part:
                                vp["draft_prompt"] = value
                                vp["video_status"] = "drafted"
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
            part = action.get("part")
            ok, label = _do_submit_task(project_name, data, target, name, version_id, part)
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
                      version_id: int, part=None) -> tuple[bool, str]:
    """提交任务到 Vidu/Wetoken，返回 (成功, 描述)"""
    from api import vidu, wetoken
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
                asset["status"] = "submitted"
                asset["task_id"] = result["task_id"]
                return True, f"道具「{name}」已提交"

        elif target == "storyboard":
            board = data.get("storyboards", {}).get(name, {})
            bv = _find_board_version(board, version_id)
            if bv:
                prompt = bv.get("draft_prompt", "")
                if not prompt:
                    return False, f"故事板「{name}」v{version_id} 没有提示词"
                result = vidu.submit_image_task(vidu_key, prompt, [], ratio="16:9")
                bv["status"] = "submitted"
                bv["board_task_id"] = result["task_id"]
                return True, f"故事板「{name}」v{version_id} 已提交"

        elif target == "video_part":
            board = data.get("storyboards", {}).get(name, {})
            bv = _find_board_version(board, version_id)
            if bv:
                for vp in bv.get("video_parts", []):
                    if vp.get("part") == part:
                        duration = vp.get("duration") or 10
                        prompt = vp.get("draft_prompt", vp.get("prompt", ""))
                        if not prompt:
                            return False, f"「{name}」Part {part} 没有提示词"
                        task_id = wetoken.submit_video_task(wetoken_key, prompt, [], duration=duration, ratio="16:9")
                        vp["video_status"] = "submitted"
                        vp["video_task_id"] = task_id
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
            full = _get_full_prompt(project_name, target, name, version_id)
            fetched.append(f"【{target}「{name}」v{version_id} 完整提示词】\n{full}")

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

    has_writes = any(r.get("ok") for r in tool_results)

    return {
        "reply": reply,
        "tool_results": tool_results,
        "has_writes": has_writes,
    }
