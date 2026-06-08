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

            storyboards[key] = {
                "episode": ep,
                "scene_num": scene_num,
                "script_title": f"第{ep}集·场景{scene_num}·{location}",
                "characters_in_scene": chars_in_scene,
                "scene_location": matched_location,
                "script_segment": script_segment,
                "board_status": "needed",
                "draft_prompt": "",
                "video_parts": [],
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
