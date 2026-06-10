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
import math
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

    parsed_versions = {}
    for ver_key, script_dir in version_dirs.items():
        parsed_versions[ver_key] = _parse_scripts(script_dir, scenes)

    if not characters:
        characters = _infer_characters_from_storyboards(parsed_versions)
    if not scenes:
        scenes = _infer_scenes_from_storyboards(parsed_versions)

    source_scenes = parsed_versions.get("v1") or next(iter(parsed_versions.values()), {})

    return {
        "project": project_name,
        "assets": {
            "characters": {name: _make_asset("character", name, seed) for name, seed in characters.items()},
            "scenes": {name: _make_asset("scene", name, seed) for name, seed in scenes.items()},
            "props": {name: _make_asset("prop", name, seed) for name, seed in props.items()},
        },
        "source_scenes": source_scenes,
        "storyboard_route": None,
        "storyboards": {},
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


def _make_asset(category: str, name: str, seed: str) -> dict:
    return {
        "seed": seed,
        "draft_prompt": _make_asset_prompt(category, name, seed),
        "status": "drafted",
        "task_id": None,
        "result_url": None,
    }


def _make_asset_prompt(category: str, name: str, seed: str) -> str:
    description = seed or name
    if category == "character":
        return (
            "请创作一张高完成度的电影级角色设定板。\n"
            f"角色名称：{name}\n"
            f"角色描述：{description}\n"
            "风格方向：电影级风格化写实，真实演员质感，五官和体态在所有角度严格一致。\n"
            "版面结构：横版角色设定板，包含主视觉角色立像、全身多角度转面图、头部研究图、电影感情绪肖像、服装与配件拆解、专业标注信息。\n"
            "画面要求：中性灰背景，干净专业排版，材质真实，服装轮廓清晰，可作为后续故事板和视频生成的共享角色参考图。"
        )
    if category == "scene":
        return (
            "Create a cinematic multi-angle scene reference board of one single physical location.\n"
            f"Scene name: {name}\n"
            f"Scene description: {description}\n"
            "All four panels must show the exact same physical location from different camera positions only.\n"
            "Keep consistent across all panels: same layout, same architecture, same furniture, same lighting, same entrances and key props.\n"
            "Create a clean 2x2 reference grid. No text, no labels.\n"
            "Panels: front wide shot, reverse angle, top-down layout, cinematic medium shot.\n"
            "Use this as a reusable environment reference for storyboard and video generation."
        )
    if category == "prop":
        return (
            "Create a cinematic multi-angle reference board of one single physical object.\n"
            f"Object name: {name}\n"
            f"Object description: {description}\n"
            "All four panels must show the exact same object from different camera positions.\n"
            "Create a clean 2x2 reference grid. No text, no labels.\n"
            "Panels: front master, side profile, top-down, hero close-up detail.\n"
            "Keep shape, material, scale, wear marks, and identifying details consistent across all panels."
        )
    return f"资产名称：{name}\n基础描述：{description}"


def _make_storyboard_plan(ver_key: str, scenes: dict[str, dict]) -> dict[str, dict]:
    planned = {}
    for scene_key, scene in scenes.items():
        boards = _make_v2_boards(scene_key, scene) if ver_key == "v2" else _make_v1_boards(scene_key, scene, ver_key)
        total_pages = len(boards)
        for board in boards:
            board["total_pages"] = total_pages
        first = boards[0] if boards else {}
        planned[scene_key] = {
            **scene,
            "source_scene_key": scene_key,
            "layout": "director_sheet_15s" if ver_key == "v2" else "nine_grid",
            "boards": boards,
            # 兼容旧前端/旧接口：默认指向第一张板。
            "draft_prompt": first.get("draft_prompt", ""),
            "status": first.get("status", "needed"),
            "board_task_id": first.get("board_task_id"),
            "video_parts": first.get("video_parts", []),
        }
    return planned


def _make_v1_boards(scene_key: str, scene: dict, ver_key: str) -> list[dict]:
    duration = _estimate_script_seconds(scene.get("script_segment", ""))
    return [_make_board(
        scene_key=scene_key,
        scene=scene,
        ver_key=ver_key,
        page=1,
        shot_count=9,
        estimated_duration=duration,
        covered_text=scene.get("script_segment", ""),
        layout="nine_grid",
    )]


def _make_v2_boards(scene_key: str, scene: dict) -> list[dict]:
    beats = _split_script_beats(scene.get("script_segment", ""))
    if not beats:
        beats = [""]
    pages: list[list[tuple[str, float]]] = []
    current: list[tuple[str, float]] = []
    current_sec = 0.0
    for beat in beats:
        sec = min(15.0, _estimate_line_seconds(beat))
        would_over_time = current and current_sec + sec > 15.0
        would_over_shots = current and len(current) >= 6
        if would_over_time or would_over_shots:
            pages.append(current)
            current = []
            current_sec = 0.0
        current.append((beat, sec))
        current_sec += sec
    if current:
        pages.append(current)

    boards = []
    for idx, page_beats in enumerate(pages, 1):
        covered_text = "\n".join(beat for beat, _ in page_beats).strip()
        duration = min(15.0, sum(sec for _, sec in page_beats))
        shot_count = min(6, max(5, len(page_beats)))
        boards.append(_make_board(
            scene_key=scene_key,
            scene=scene,
            ver_key="v2",
            page=idx,
            shot_count=shot_count,
            estimated_duration=duration,
            covered_text=covered_text,
            layout="director_sheet_15s",
        ))
    return boards


def _make_board(scene_key: str, scene: dict, ver_key: str, page: int, shot_count: int,
                estimated_duration: float, covered_text: str, layout: str) -> dict:
    board_id = f"{scene_key}_{ver_key}_p{page:02d}"
    prompt = _make_storyboard_prompt(ver_key, scene, board_id, page, shot_count, estimated_duration, covered_text)
    return {
        "board_id": board_id,
        "source_scene_key": scene_key,
        "page": page,
        "total_pages": 1,
        "layout": layout,
        "shot_count": shot_count,
        "estimated_duration": round(estimated_duration, 1),
        "covered_text": covered_text,
        "prompt_seed": prompt,
        "plan": {},
        "draft_prompt": "",
        "status": "planned",
        "board_task_id": None,
        "result_url": None,
        "video_parts": [],
    }


def _make_storyboard_prompt(ver_key: str, scene: dict, board_id: str, page: int,
                            shot_count: int, duration: float, covered_text: str) -> str:
    base = (
        f"分镜板ID：{board_id}\n"
        f"集数：第{scene.get('episode', 1)}集\n"
        f"场景：{scene.get('scene_location') or scene.get('script_title', '')}\n"
        f"人物：{', '.join(scene.get('characters_in_scene', [])) or '无'}\n"
        f"本页剧情：\n{covered_text}\n"
    )
    if ver_key == "v2":
        return (
            base +
            f"版本：v2 专业影视分镜板。请生成黑白铅笔线稿/导演分镜稿，单张总时长不超过15秒。"
            f"本页建议 {shot_count} 个镜头，总时长约 {round(duration, 1)} 秒。"
            "顶部标题栏、上半部分横向分镜格、下半部分包含俯视位置图和全景场景图，页脚标注摘要、镜头数量、总时长和页码。"
        )
    return (
        base +
        "版本：v1 九宫格故事板。请生成 clean 3x3 cinematic storyboard grid，9格连续动作，每格角色位置和朝向明确。"
    )


def _split_script_beats(script_segment: str) -> list[str]:
    return [line.strip() for line in script_segment.splitlines() if line.strip()]


def _estimate_script_seconds(script_segment: str) -> float:
    return sum(_estimate_line_seconds(line) for line in _split_script_beats(script_segment))


def _estimate_line_seconds(line: str) -> float:
    if not line.strip():
        return 0.0
    dialogue_match = re.search(r'[：:](.+)$', line)
    if dialogue_match:
        text = re.sub(r'[（）()【】\[\]\s]', '', dialogue_match.group(1))
        return max(2.0, min(8.0, math.ceil(len(text) / 3)))
    return 3.0


def _infer_characters_from_storyboards(storyboards: dict[str, dict]) -> dict[str, str]:
    characters: dict[str, str] = {}
    for scenes in storyboards.values():
        for scene in scenes.values():
            for name in scene.get("characters_in_scene", []):
                characters.setdefault(name, f"从剧本台词中识别的角色：{name}")
    return characters


def _infer_scenes_from_storyboards(storyboards: dict[str, dict]) -> dict[str, str]:
    scenes: dict[str, str] = {}
    for version_scenes in storyboards.values():
        for scene in version_scenes.values():
            location = scene.get("scene_location")
            if location:
                scenes.setdefault(location, f"从剧本场景标题中识别的场景：{location}")
    return scenes


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
