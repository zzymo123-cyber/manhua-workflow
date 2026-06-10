"""
从剧本标准输入目录解析生成 pipeline.json 数据结构。

目录结构：
  {input_dir}/
    character_visuals.md   — 角色外貌（## 角色名 分段）
    scene_props_visuals.md — 场景与道具（## 场景名 / ## 道具名 分段）
    characters.md          — 角色表（可选，用于补充）
    overview.md            — 全剧概览（可选）
    script_v1/             — v1 版本场景拆分
      ep01.md, ep02.md ...
    script_v2/             — v2 版本场景拆分（可选）
      ep01.md, ep02.md ...
    script/                — 兼容旧格式，等同于 script_v1

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

    # 发现所有版本目录：script_v1, script_v2, ... 或兼容旧格式 script/
    version_dirs = _find_version_dirs(root)

    storyboards = {}
    for ver_key, script_dir in version_dirs.items():
        storyboards[ver_key] = _parse_scripts(script_dir, scenes)

    return {
        "project": project_name,
        "assets": {
            "characters": {name: _make_asset(seed) for name, seed in characters.items()},
            "scenes": {name: _make_asset(seed) for name, seed in scenes.items()},
            "props": {name: _make_asset(seed) for name, seed in props.items()},
        },
        "storyboards": storyboards,
    }


def _find_version_dirs(root: Path) -> dict[str, Path]:
    """
    返回 {ver_key: Path} 有序字典。
    优先找 script_v1, script_v2, ... 目录；
    若无则 fallback 到 script/ 作为 v1。
    """
    result = {}
    # 找所有 script_vN 目录
    for d in sorted(root.iterdir()):
        if d.is_dir() and re.match(r'^script_v\d+$', d.name):
            ver_key = d.name[len("script_"):]  # "v1", "v2", ...
            result[ver_key] = d
    # 兼容旧 script/ 目录
    if not result and (root / "script").is_dir():
        result["v1"] = root / "script"
    return result


def _make_asset(seed: str) -> dict:
    return {
        "seed": seed,
        "draft_prompt": "",
        "status": "needed",
        "task_id": None,
        "result_url": None,
    }


def _parse_h2_sections(text: str) -> dict[str, str]:
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
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return _parse_h2_sections(text)


def _parse_scene_props_visuals(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not path.exists():
        return {}, {}
    text = path.read_text(encoding="utf-8")

    scenes: dict[str, str] = {}
    props: dict[str, str] = {}

    prop_marker = re.search(r'^##\s*关键道具', text, re.MULTILINE)
    if prop_marker:
        scene_text = text[:prop_marker.start()]
        prop_text = text[prop_marker.start():]
    else:
        scene_text = text
        prop_text = ""

    scenes = _parse_h3_sections(scene_text)

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
    遍历 script 目录下的 ep*.md，按场次生成场景 dict。
    key 格式：s{ep:02d}_{scene_num:02d}，如 s01_01
    """
    if not script_dir.exists():
        return {}

    storyboards: dict[str, dict] = {}

    scene_header_re = re.compile(
        r'^##\s*场景([一二三四五六七八九十百\d]+)[：:]\s*[内外]?\s*[··]?\s*(.+?)\s*[··]\s*(.+)$'
    )
    dialogue_re = re.compile(r'\*\*([^*]+)\*\*')

    ep_files = sorted(script_dir.glob("ep*.md"))

    for ep_file in ep_files:
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

            chars_in_scene = []
            seen = set()
            for line in body_lines:
                for m in dialogue_re.finditer(line):
                    name = m.group(1).strip()
                    if name not in seen and name not in ("vo", "VO", "旁白"):
                        seen.add(name)
                        chars_in_scene.append(name)

            matched_location = _match_location(location, known_scenes)

            storyboards[key] = {
                "episode": ep,
                "scene_num": scene_num,
                "script_title": f"第{ep}集·场景{scene_num}·{location}",
                "characters_in_scene": chars_in_scene,
                "scene_location": matched_location,
                "script_segment": script_segment,
                "draft_prompt": "",
                "status": "needed",
                "board_task_id": None,
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
    if location in known_scenes:
        return location
    for key in known_scenes:
        key_short = key.split("·")[-1].strip() if "·" in key else key
        if key_short in location or location in key_short or location in key:
            return key
    return location


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15}


def _cn_to_int(s: str) -> int:
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s, 0)
