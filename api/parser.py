"""
从剧本标准输入目录解析生成 pipeline.json 数据结构。

目录结构：
  {input_dir}/
    character_visuals.md   — 角色外貌（## 角色名 分段）
    scene_props_visuals.md — 场景与道具（## 场景名 / ## 道具名 分段）
    characters.md          — 角色表（可选，用于补充）
    overview.md            — 全剧概览（可选）
    script/
      ep01.md, ep02.md ... — 每集剧本

场景标题格式：## 场景N：内/外 · 地点名 · 时间
台词格式：**角色名**（状态）：台词
"""

import re
from pathlib import Path


def parse_input_dir(input_dir: str | Path, project_name: str) -> dict:
    """
    读取输入目录，返回 pipeline.json 数据结构（dict）。
    不写文件，由调用方决定保存位置。
    """
    root = Path(input_dir)

    characters = _parse_character_visuals(root / "character_visuals.md")
    scenes, props = _parse_scene_props_visuals(root / "scene_props_visuals.md")
    storyboards = _parse_scripts(root / "script", scenes)
    inferred_characters, inferred_scenes, inferred_props = _infer_assets_from_storyboards(storyboards)

    for name, seed in inferred_characters.items():
        characters.setdefault(name, seed)
    for name, seed in inferred_scenes.items():
        scenes.setdefault(name, seed)
    for name, seed in inferred_props.items():
        props.setdefault(name, seed)

    return {
        "project": project_name,
        "assets": {
            "characters": {name: {"seed": seed, "status": "needed"} for name, seed in characters.items()},
            "scenes": {name: {"seed": seed, "status": "needed"} for name, seed in scenes.items()},
            "props": {name: {"seed": seed, "status": "needed"} for name, seed in props.items()},
        },
        "storyboards": storyboards,
    }


def _parse_h2_sections(text: str) -> dict[str, str]:
    """把 markdown 按 ## 标题分段，返回 {标题: 内容} dict"""
    sections = {}
    current_title = None
    current_lines = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _parse_h3_sections(text: str) -> dict[str, str]:
    """把 markdown 按 ### 标题分段，返回 {标题: 内容} dict"""
    sections = {}
    current_title = None
    current_lines = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[4:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _parse_character_visuals(path: Path) -> dict[str, str]:
    """返回 {角色名: 外貌描述文本}"""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return _parse_h2_sections(text)


def _parse_scene_props_visuals(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """
    返回 (scenes, props)。
    文件里有 ## 场景 和 ## 关键道具 两大块，## 关键道具 下的 ### 是道具。
    场景用 ## 分段，道具用 ### 分段（在"关键道具"section之后）。
    """
    if not path.exists():
        return {}, {}
    text = path.read_text(encoding="utf-8")

    scenes: dict[str, str] = {}
    props: dict[str, str] = {}

    # 以 --- 分隔的两大块：场景 和 关键道具
    # 简单策略：先找 "## 关键道具" 的位置，之前是场景，之后是道具
    prop_marker = re.search(r'^##\s*关键道具', text, re.MULTILINE)
    if prop_marker:
        scene_text = text[:prop_marker.start()]
        prop_text = text[prop_marker.start():]
    else:
        scene_text = text
        prop_text = ""

    # 解析场景（用 ### 分段）
    scenes = _parse_h3_sections(scene_text)

    # 解析道具（用 ### 分段）
    if prop_text:
        current_title = None
        current_lines = []
        for line in prop_text.splitlines():
            if line.startswith("### "):
                if current_title is not None:
                    props[current_title] = "\n".join(current_lines).strip()
                current_title = line[4:].strip()
                current_lines = []
            elif current_title is not None:
                current_lines.append(line)
        if current_title is not None:
            props[current_title] = "\n".join(current_lines).strip()

    return scenes, props


def _parse_scripts(script_dir: Path, known_scenes: dict[str, str]) -> dict[str, dict]:
    """
    遍历 script/*.md，按场次生成 storyboards dict。
    key 格式：s{ep:02d}_{scene_num:02d}，如 s01_01
    """
    if not script_dir.exists():
        return {}

    storyboards: dict[str, dict] = {}

    # 场景标题正则：## 场景N：内/外 · 地点名 · 时间
    scene_header_re = re.compile(
        r'^##\s*场景([一二三四五六七八九十百\d]+)[：:]\s*[内外]?\s*[··]?\s*(.+?)\s*[··]\s*(.+)$'
    )
    # 台词正则：**角色名**（可选状态）：台词  或  **角色名**（vo）：...
    dialogue_re = re.compile(r'\*\*([^*]+)\*\*')

    ep_files = sorted(script_dir.glob("ep*.md"))

    for ep_file in ep_files:
        # 从文件名提取集数
        ep_match = re.search(r'ep(\d+)', ep_file.stem)
        if not ep_match:
            continue
        ep_num = int(ep_match.group(1))

        text = ep_file.read_text(encoding="utf-8")
        lines = text.splitlines()

        current_scene_num = None
        current_location = None
        current_time = None
        current_lines = []

        def _flush_scene(scene_num, location, time_str, body_lines, ep):
            if scene_num is None:
                return
            key = f"s{ep:02d}_{scene_num:02d}"
            script_segment = "\n".join(body_lines).strip()

            # 提取本场出现的角色名（去掉 VO、旁白等非角色）
            chars_in_scene = []
            seen = set()
            for line in body_lines:
                for m in dialogue_re.finditer(line):
                    name = m.group(1).strip()
                    if name not in seen and name not in ("vo", "VO", "旁白"):
                        seen.add(name)
                        chars_in_scene.append(name)

            # 地点名匹配已知场景（优先精确，其次包含）
            matched_location = _match_location(location, known_scenes)
            props_in_scene = _extract_explicit_props(script_segment)
            story_summary = _summarize_script_segment(script_segment)
            conflict_summary = _summarize_conflict(script_segment, chars_in_scene, matched_location)
            v2_pages = _build_initial_shot_plan_pages(
                ep=ep,
                scene_num=scene_num,
                scene_location=matched_location,
                scene_time=time_str or "",
                characters=chars_in_scene,
                props=props_in_scene,
                script_segment=script_segment,
            )
            first_shot_plan = v2_pages[0]["shot_plan"]

            storyboards[key] = {
                "episode": ep,
                "scene_num": scene_num,
                "script_title": f"第{ep}集·场景{scene_num}·{location}",
                "characters_in_scene": chars_in_scene,
                "scene_location": matched_location,
                "scene_time": time_str or "",
                "props_in_scene": props_in_scene,
                "story_summary": story_summary,
                "conflict_summary": conflict_summary,
                "script_segment": script_segment,
                "shot_plan": first_shot_plan,
                "board_status": "needed",
                "draft_prompt": "",
                "video_parts": [],
                "board_versions": {
                    "v1": {
                        "draft_prompt": "",
                        "board_status": "needed",
                        "video_parts": [],
                        "outputs": [{
                            "id": "v1_main",
                            "label": "v1 主图",
                            "page": 1,
                            "draft_prompt": "",
                            "board_status": "needed",
                            "shot_plan": first_shot_plan,
                            "video_parts": [],
                        }],
                    },
                    "v2": {
                        "outputs": v2_pages,
                        "pages": v2_pages,
                    },
                    "v3": {"outputs": []},
                    "v4": {"outputs": []},
                },
            }

        for line in lines:
            m = scene_header_re.match(line)
            if m:
                _flush_scene(current_scene_num, current_location, current_time, current_lines, ep_num)
                raw_num = m.group(1)
                current_scene_num = _cn_to_int(raw_num)
                current_location = m.group(2).strip()
                current_time = m.group(3).strip()
                current_lines = []
            elif current_scene_num is not None:
                current_lines.append(line)

        _flush_scene(current_scene_num, current_location, current_time, current_lines, ep_num)

    return storyboards


def _infer_assets_from_storyboards(storyboards: dict[str, dict]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    characters: dict[str, str] = {}
    scenes: dict[str, str] = {}
    props: dict[str, str] = {}

    for board in storyboards.values():
        title = board.get("script_title", "")
        segment = board.get("script_segment", "")
        scene = board.get("scene_location", "")
        if scene:
            scenes.setdefault(scene, _inferred_scene_seed(scene, title, segment))

        for name in board.get("characters_in_scene", []):
            characters.setdefault(name, _inferred_character_seed(name, title, segment))

        for prop in _extract_explicit_props(segment):
            props.setdefault(prop, _inferred_prop_seed(prop, title, segment))

    return characters, scenes, props


def _inferred_character_seed(name: str, title: str, segment: str) -> str:
    sample = _first_matching_line(segment, name)
    suffix = f"参考剧本片段：{sample}" if sample else f"出现于：{title}"
    return f"从剧本自动识别的角色「{name}」。缺少角色外貌文档，请补充外貌、年龄、服装和气质。{suffix}"


def _inferred_scene_seed(name: str, title: str, segment: str) -> str:
    sample = _first_content_line(segment)
    suffix = f"参考剧情：{sample}" if sample else title
    return f"从剧本场景标题自动识别的场景「{name}」。缺少场景视觉文档，请补充空间结构、时代、光线和关键陈设。{suffix}"


def _inferred_prop_seed(name: str, title: str, segment: str) -> str:
    sample = _first_matching_line(segment, name)
    suffix = f"参考剧本片段：{sample}" if sample else f"出现于：{title}"
    return f"从剧本道具标记自动识别的道具「{name}」。缺少道具视觉文档，请补充材质、尺寸、颜色和使用方式。{suffix}"


def _first_matching_line(text: str, needle: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if needle in line:
            return line[:120]
    return ""


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def _extract_explicit_props(text: str) -> list[str]:
    props: list[str] = []
    seen = set()
    for line in text.splitlines():
        for match in re.finditer(r'(?:道具|关键道具)\s*[：:]\s*([^。；;\n]+)', line):
            raw = match.group(1)
            for item in re.split(r'[、,，/]+', raw):
                name = _clean_prop_name(item)
                if name and name not in seen:
                    seen.add(name)
                    props.append(name)
    return props


def _clean_prop_name(value: str) -> str:
    name = re.sub(r'[\s。；;：:]+$', '', value.strip())
    name = re.sub(r'^[“"《<]+|[”"》>]+$', '', name)
    if not name or len(name) > 24:
        return ""
    if name in {"无", "没有", "暂无"}:
        return ""
    return name


def _summarize_script_segment(text: str, max_len: int = 140) -> str:
    cleaned = _clean_script_text(text)
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 1] + "…"


def _summarize_conflict(text: str, characters: list[str], scene_location: str) -> str:
    cleaned = _clean_script_text(text)
    if not cleaned:
        return "本场冲突/主题待补充"
    lead = "、".join(characters[:3]) if characters else "角色"
    location = scene_location or "当前场景"
    return f"{lead}在{location}围绕“{cleaned[:48]}”展开行动或信息推进"


def _clean_script_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\*\*([^*]+)\*\*", r"\1", text)).strip()


def _clean_script_line(line: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\*\*([^*]+)\*\*", r"\1", line)).strip()


def _build_initial_shot_plan(
    ep: int,
    scene_num: int,
    scene_location: str,
    scene_time: str,
    characters: list[str],
    props: list[str],
    script_segment: str,
) -> dict:
    lines = [_clean_script_line(line) for line in script_segment.splitlines() if _clean_script_line(line)]
    if not lines:
        lines = [f"{'、'.join(characters) or '角色'}在{scene_location or '场景'}内行动。"]

    return _build_shot_plan_from_lines(
        ep=ep,
        scene_num=scene_num,
        scene_location=scene_location,
        scene_time=scene_time,
        characters=characters,
        props=props,
        lines=lines[:6],
        page_index=1,
        page_total=1,
        remaining_lines=lines[6:],
    )


def _build_initial_shot_plan_pages(
    ep: int,
    scene_num: int,
    scene_location: str,
    scene_time: str,
    characters: list[str],
    props: list[str],
    script_segment: str,
) -> list[dict]:
    lines = [_clean_script_line(line) for line in script_segment.splitlines() if _clean_script_line(line)]
    if not lines:
        lines = [f"{'、'.join(characters) or '角色'}在{scene_location or '场景'}内行动。"]

    chunks = [lines[i:i + 6] for i in range(0, len(lines), 6)] or [lines]
    page_total = len(chunks)
    pages = []
    for index, chunk in enumerate(chunks, 1):
        remaining = [line for later in chunks[index:] for line in later]
        pages.append({
            "id": f"v2_p{index}",
            "label": f"v2 P{index}",
            "page": index,
            "draft_prompt": "",
            "board_status": "needed",
            "video_parts": [],
            "shot_plan": _build_shot_plan_from_lines(
                ep=ep,
                scene_num=scene_num,
                scene_location=scene_location,
                scene_time=scene_time,
                characters=characters,
                props=props,
                lines=chunk,
                page_index=index,
                page_total=page_total,
                remaining_lines=remaining,
            ),
        })
    return pages


def _build_shot_plan_from_lines(
    ep: int,
    scene_num: int,
    scene_location: str,
    scene_time: str,
    characters: list[str],
    props: list[str],
    lines: list[str],
    page_index: int,
    page_total: int,
    remaining_lines: list[str],
) -> dict:
    selected = lines[:6]
    shot_count = max(1, min(6, len(selected)))
    base_duration = 15 // shot_count
    durations = [max(2, base_duration) for _ in range(shot_count)]
    while sum(durations) > 15:
        for idx in range(len(durations) - 1, -1, -1):
            if durations[idx] > 2 and sum(durations) > 15:
                durations[idx] -= 1

    shot_types = ["全景", "中景", "近景", "中景", "特写", "全景"]
    camera_positions = ["正面", "侧面", "过肩", "俯拍", "正面", "背面"]
    shots = []
    cursor = 0.0
    for index, (line, duration) in enumerate(zip(selected, durations), 1):
        start = cursor
        cursor += duration
        shots.append({
            "index": index,
            "timecode": f"{start:.1f}-{cursor:.1f}s",
            "duration": duration,
            "shot": shot_types[index - 1],
            "camera": camera_positions[index - 1],
            "action": line,
            "dialogue": _extract_dialogue_text(line) or "无",
        })

    return {
        "mode": "v2",
        "episode": ep,
        "scene_num": scene_num,
        "scene_location": scene_location,
        "scene_time": scene_time,
        "characters": characters,
        "props": props,
        "page_index": page_index,
        "page_total": page_total,
        "continues_next": bool(remaining_lines),
        "remaining_story": " ".join(remaining_lines),
        "total_duration": sum(durations),
        "shots": shots,
    }


def _extract_dialogue_text(line: str) -> str:
    if "：" in line:
        return line.split("：", 1)[1].strip()
    if ":" in line:
        return line.split(":", 1)[1].strip()
    return ""


def _match_location(location: str, known_scenes: dict[str, str]) -> str:
    """
    把剧本里的地点名匹配到 scene_props_visuals 里的场景名。
    精确匹配 > 包含匹配 > 返回原始地点名。
    """
    if location in known_scenes:
        return location
    # 包含匹配：known_scenes 的 key 包含 location 的任意片段
    for key in known_scenes:
        # 去掉"婉瑜家·"前缀后匹配
        key_short = key.split("·")[-1].strip() if "·" in key else key
        if key_short in location or location in key_short or location in key:
            return key
    return location


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15}


def _cn_to_int(s: str) -> int:
    """把中文数字或阿拉伯数字转为 int"""
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s, 0)
