import json, pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import main as app_main
from api.routes import settings as settings_route
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_route, "SETTINGS_PATH", tmp_path / "settings.json")


def _make_pipeline(name="测试项目"):
    return {
        "project": name,
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {}
    }


def _make_pipeline_with_character(name="婉瑜", seed="描述"):
    return {
        "project": "测试项目",
        "assets": {
            "characters": {
                name: {
                    "seed": seed,
                    "draft_prompt": "",
                    "status": "needed",
                    "task_id": None,
                    "result_url": None,
                }
            },
            "scenes": {},
            "props": {},
        },
        "storyboards": {}
    }


def test_import_project_pipeline_not_found(tmp_path):
    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/project/import", json={"project_name": "不存在的项目"})
    assert resp.status_code == 404


def test_import_project_success(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/project/import", json={"project_name": "测试项目"})
    assert resp.status_code == 200
    assert resp.json()["project"] == "测试项目"
    assert resp.json()["_exists"] is True


def test_get_project_status(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/status", params={"project_name": "测试项目"})
    assert resp.status_code == 200
    assert resp.json()["project"] == "测试项目"


def test_get_project_status_uses_settings_keys(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    client.put("/api/settings", json={
        "vidu_api_key": "vidu-secret",
        "wetoken_api_key": "wetoken-secret",
        "idealab_api_key": "idealab-secret",
    })

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path), \
         patch.dict("os.environ", {
             "VIDU_API_KEY": "",
             "WETOKEN_API_KEY": "",
             "IDEALAB_API_KEY": "",
         }, clear=False):
        resp = client.get("/api/project/status", params={"project_name": "测试项目"})
    assert resp.status_code == 200
    assert "_warnings" not in resp.json()


def test_list_project_documents(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(json.dumps(_make_pipeline(), ensure_ascii=False), encoding="utf-8")
    (project_dir / "overview.md").write_text("overview", encoding="utf-8")
    script_dir = project_dir / "script"
    script_dir.mkdir()
    (script_dir / "ep01.md").write_text("ep01", encoding="utf-8")
    asset_dir = project_dir / "characters" / "婉瑜"
    asset_dir.mkdir(parents=True)
    (asset_dir / "meta.json").write_text("{}", encoding="utf-8")
    (project_dir / "scenes_props").mkdir()
    (project_dir / "videos").mkdir()

    resp = client.get("/api/project/documents", params={"project_path": str(project_dir)})

    assert resp.status_code == 200
    paths = [doc["path"] for doc in resp.json()["documents"]]
    kinds = {doc["path"]: doc["kind"] for doc in resp.json()["documents"]}
    assert "." in paths
    assert "characters" in paths
    assert "scenes_props" in paths
    assert "videos" in paths
    assert kinds["characters"] == "folder"
    assert "overview.md" in paths
    assert "script/ep01.md" in paths
    assert "characters/婉瑜/meta.json" not in paths


def test_open_project_document_allows_asset_folder(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(json.dumps(_make_pipeline(), ensure_ascii=False), encoding="utf-8")
    (project_dir / "characters").mkdir()

    with patch("api.routes.project.subprocess.Popen") as popen_mock:
        resp = client.post("/api/project/open-document", json={
            "project_path": str(project_dir),
            "file_path": "characters",
        })

    assert resp.status_code == 200
    assert popen_mock.call_args.args[0] == ["open", str(project_dir / "characters")]


def test_open_project_document_rejects_path_escape(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(json.dumps(_make_pipeline(), ensure_ascii=False), encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    resp = client.post("/api/project/open-document", json={
        "project_path": str(project_dir),
        "file_path": "../outside.md",
    })

    assert resp.status_code == 400


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_get_port_uses_manhua_port(monkeypatch):
    monkeypatch.setenv("MANHUA_PORT", "8010")
    monkeypatch.setenv("PORT", "9000")
    assert app_main.get_port() == 8010


def test_get_port_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("MANHUA_PORT", "70000")
    monkeypatch.delenv("PORT", raising=False)
    with pytest.raises(RuntimeError):
        app_main.get_port()


def test_parse_project_allows_missing_visual_docs(tmp_path):
    project_dir = tmp_path / "新项目"
    script_dir = project_dir / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "ep01.md").write_text(
        "## 场景1：内 · 客厅 · 夜\n\n**阿明**（紧张）：我们走。\n**林雪**：等一下。",
        encoding="utf-8",
    )

    resp = client.post("/api/project/parse", json={
        "input_dir": str(project_dir),
        "project_name": "新项目",
    })

    assert resp.status_code == 200
    data = resp.json()["pipeline"]
    assert set(data["assets"]["characters"]) == {"阿明", "林雪"}
    assert set(data["assets"]["scenes"]) == {"客厅"}
    assert (project_dir / "pipeline.json").exists()


def test_script_import_then_single_route_storyboard_video_flow(tmp_path):
    project_dir = tmp_path / "单路线项目"
    script_dir = project_dir / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "ep01.md").write_text(
        "## 场景1：内 · 客厅 · 夜\n\n**阿明**（紧张）：我们走。\n**林雪**：等一下。",
        encoding="utf-8",
    )

    parse_resp = client.post("/api/project/parse", json={
        "input_dir": str(project_dir),
        "project_name": "单路线项目",
    })
    assert parse_resp.status_code == 200

    data = parse_resp.json()["pipeline"]
    assert set(data["source_scenes"]) == {"s01_01"}
    assert set(data["assets"]["characters"]) == {"阿明", "林雪"}
    assert set(data["assets"]["scenes"]) == {"客厅"}
    assert data["assets"]["characters"]["阿明"]["status"] == "drafted"
    assert data["assets"]["characters"]["阿明"]["draft_prompt"]
    assert "角色设定板" in data["assets"]["characters"]["阿明"]["draft_prompt"]
    assert "multi-angle scene reference board" in data["assets"]["scenes"]["客厅"]["draft_prompt"]
    assert data["storyboard_route"] is None
    assert data["storyboards"] == {}

    resp = client.post("/api/prompts/select-storyboard-route", json={
        "project_path": str(project_dir),
        "board_version": "v2",
    })
    assert resp.status_code == 200
    data = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert data["storyboard_route"] == "v2"
    assert set(data["storyboards"]) == {"v2"}
    assert set(data["storyboards"]["v2"]) == {"s01_01"}
    scene = data["storyboards"]["v2"]["s01_01"]
    assert scene["status"] == "unplanned"
    assert scene["boards"] == []

    llm_outputs = [
        json.dumps({"core_event": "出门被拦", "emotion_beats": ["紧张", "阻止"]}, ensure_ascii=False),
        json.dumps({"boards": [{
            "covered_text": "**阿明**（紧张）：我们走。\n**林雪**：等一下。",
            "shot_count": 5,
            "estimated_duration": 7,
            "prompt_seed": "v2 planned seed",
            "plan": {"beats": ["走", "拦"]},
            "asset_refs": {"characters": ["阿明", "林雪"], "scene": "客厅", "props": []},
        }]}, ensure_ascii=False),
        "v2 storyboard prompt",
        "---PART1---\nc1,6s,v2 video",
    ]

    with patch("api.routes.prompts.llm.generate_prompt", side_effect=llm_outputs), \
         patch("api.routes.prompts.get_api_key", return_value="fake_llm_key"), \
         patch("api.routes.tasks.vidu.submit_image_task",
               return_value={"task_id": "board_v2"}), \
         patch("api.routes.tasks.wetoken.submit_video_task",
               return_value="video_v2"), \
         patch("api.routes.tasks.get_api_key", return_value="fake_task_key"):
        resp = client.post("/api/prompts/analyze-scene", json={
            "project_path": str(project_dir),
            "scene_key": "s01_01",
        })
        assert resp.status_code == 200

        resp = client.post("/api/prompts/plan-storyboards", json={
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
        })
        assert resp.status_code == 200
        planned = resp.json()["boards"][0]
        assert planned["status"] == "planned"
        assert planned["draft_prompt"] == ""
        assert planned["prompt_seed"] == "v2 planned seed"
        assert planned["asset_refs"] == {"characters": ["阿明", "林雪"], "scene": "客厅", "props": []}

        resp = client.post("/api/prompts/lock-storyboard-plan", json={
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
        })
        assert resp.status_code == 200

        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "characters": scene["characters_in_scene"],
            "scene_location": scene["scene_location"],
            "script_segment": scene["script_segment"],
        })
        assert resp.status_code == 200

        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "prompt": "v2 storyboard prompt",
            "image_paths": [],
        })
        assert resp.status_code == 200

        resp = client.post("/api/prompts/generate", json={
            "type": "video",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "script_segment": scene["script_segment"],
            "panels": [{"index": 1, "shot": "wide", "action": "走"}],
        })
        assert resp.status_code == 200

        updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
        part = updated["storyboards"]["v2"]["s01_01"]["video_parts"][0]
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "part": part["part"],
            "prompt": part["prompt"],
            "duration": part["duration"],
            "image_paths": [],
        })
        assert resp.status_code == 200

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert set(updated["assets"]["characters"]) == {"阿明", "林雪"}
    assert updated["storyboards"]["v2"]["s01_01"]["board_task_id"] == "board_v2"
    assert updated["storyboards"]["v2"]["s01_01"]["boards"][0]["board_task_id"] == "board_v2"
    assert updated["storyboards"]["v2"]["s01_01"]["video_parts"][0]["video_task_id"] == "video_v2"
    assert updated["storyboards"]["v2"]["s01_01"]["boards"][0]["video_parts"][0]["video_task_id"] == "video_v2"


def test_plan_v2_storyboard_pages_after_route_selection(tmp_path):
    project_dir = tmp_path / "长场景项目"
    script_dir = project_dir / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "ep01.md").write_text(
        """## 场景1：内 · 客厅 · 夜

阿明推门进入，停在门口。
**林雪**（压低声音）：你终于来了。
阿明看向桌上的手机。
**阿明**：这是谁的？
林雪后退半步，避开他的视线。
手机忽然震动，屏幕亮起。
阿明伸手去拿。
林雪抢先按住手机。
**林雪**：别看。
两人僵持，门外传来脚步声。
阿明回头看向门口。
林雪把手机藏到身后。
**阿明**：外面是谁？
脚步声停在门外。
门把手缓慢转动。
""",
        encoding="utf-8",
    )

    resp = client.post("/api/project/parse", json={
        "input_dir": str(project_dir),
        "project_name": "长场景项目",
    })
    assert resp.status_code == 200

    data = resp.json()["pipeline"]
    assert data["storyboards"] == {}

    analysis = json.dumps({"core_event": "手机秘密引发对峙"}, ensure_ascii=False)
    plan = json.dumps({"boards": [
        {
            "covered_text": "阿明推门进入，停在门口。\n**林雪**（压低声音）：你终于来了。",
            "shot_count": 5,
            "estimated_duration": 8,
            "prompt_seed": "第一页规划",
            "plan": {"shots": ["1", "2", "3", "4", "5", "6"]},
        },
        {"covered_text": "阿明看向桌上的手机。\n**阿明**：这是谁的？", "shot_count": 5, "estimated_duration": 7, "prompt_seed": "第二页规划"},
    ]}, ensure_ascii=False)
    with patch("api.routes.prompts.llm.generate_prompt", side_effect=[analysis, plan]) as generate_mock, \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/select-storyboard-route", json={
            "project_path": str(project_dir),
            "board_version": "v2",
        })
        assert resp.status_code == 200
        resp = client.post("/api/prompts/analyze-scene", json={
            "project_path": str(project_dir),
            "scene_key": "s01_01",
        })
        assert resp.status_code == 200
        resp = client.post("/api/prompts/plan-storyboards", json={
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
        })
        assert resp.status_code == 200

    plan_system = generate_mock.call_args_list[1].args[1]
    assert "15 秒以内" in plan_system
    assert "5-6 个镜头" in plan_system
    assert "九宫格" not in plan_system
    assert "3x3" not in plan_system

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    v2_boards = updated["storyboards"]["v2"]["s01_01"]["boards"]
    assert len(v2_boards) == 2
    assert all(board["layout"] == "director_sheet_15s" for board in v2_boards)
    assert all(5 <= board["shot_count"] <= 6 for board in v2_boards)
    assert v2_boards[0]["shot_count"] == 6
    assert all(board["status"] == "planned" for board in v2_boards)
    assert all(board["draft_prompt"] == "" for board in v2_boards)
    assert [board["prompt_seed"] for board in v2_boards] == ["第一页规划", "第二页规划"]


def test_plan_v1_uses_nine_grid_route_without_v2_rules(tmp_path):
    project_dir = tmp_path / "九宫格项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "九宫格项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "source_scenes": {
            "s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·卧室",
                "characters_in_scene": ["婉瑜", "小乐"],
                "scene_location": "卧室",
                "script_segment": "小乐说爸爸藏在衣柜里，婉瑜愣住。",
                "scene_analysis": {"core_event": "衣柜秘密被说出"},
            }
        },
        "storyboard_route": "v1",
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    plan = json.dumps({"boards": [{
        "covered_text": "小乐说爸爸藏在衣柜里，婉瑜愣住。",
        "shot_count": 9,
        "estimated_duration": 30,
        "prompt_seed": "九宫格规划",
    }]}, ensure_ascii=False)

    with patch("api.routes.prompts.llm.generate_prompt", return_value=plan) as generate_mock, \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/plan-storyboards", json={
            "project_path": str(project_dir),
            "board_version": "v1",
            "scene_key": "s01_01",
        })
    assert resp.status_code == 200

    plan_system = generate_mock.call_args.args[1]
    assert "3x3 九宫格" in plan_system
    assert "9 格压缩" in plan_system
    assert "15 秒" not in plan_system
    assert "5-6" not in plan_system

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    v1_boards = updated["storyboards"]["v1"]["s01_01"]["boards"]
    assert len(v1_boards) == 1
    assert v1_boards[0]["layout"] == "nine_grid"
    assert v1_boards[0]["shot_count"] == 9
    assert v1_boards[0]["status"] == "planned"
    assert v1_boards[0]["prompt_seed"] == "九宫格规划"


def test_replanning_archives_existing_board_outputs(tmp_path):
    project_dir = tmp_path / "返修规划项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "返修规划项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "source_scenes": {
            "s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "**阿明**：测试。",
                "scene_analysis": {"core_event": "测试"},
            }
        },
        "storyboard_route": "v2",
        "storyboards": {
            "v2": {"s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "**阿明**：测试。",
                "scene_analysis": {"core_event": "测试"},
                "boards": [{
                    "board_id": "s01_01_v2_p01",
                    "covered_text": "旧文本",
                    "prompt_seed": "旧规划",
                    "draft_prompt": "旧最终提示词",
                    "status": "completed",
                    "board_task_id": "old_task",
                    "result_url": "storyboards/v2/s01_01/s01_01_v2_p01.png",
                    "video_parts": [{"part": 1, "draft_prompt": "旧视频"}],
                }],
            }},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    plan = json.dumps({"boards": [{
        "covered_text": "**阿明**：测试。",
        "shot_count": 5,
        "estimated_duration": 6,
        "prompt_seed": "新规划",
    }]}, ensure_ascii=False)

    with patch("api.routes.prompts.llm.generate_prompt", return_value=plan), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/plan-storyboards", json={
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
        })

    assert resp.status_code == 200
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    scene = updated["storyboards"]["v2"]["s01_01"]
    assert scene["archived_boards"][0]["reason"] == "replan"
    assert scene["archived_boards"][0]["boards"][0]["draft_prompt"] == "旧最终提示词"
    assert scene["boards"][0]["prompt_seed"] == "新规划"
    assert scene["boards"][0]["draft_prompt"] == ""
    assert scene["boards"][0]["status"] == "planned"


def test_plan_storyboards_does_not_overwrite_when_llm_returns_invalid_json(tmp_path):
    project_dir = tmp_path / "规划失败项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "规划失败项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "source_scenes": {
            "s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "**阿明**：测试。",
                "scene_analysis": {"core_event": "测试"},
            }
        },
        "storyboard_route": "v2",
        "storyboards": {
            "v2": {"s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "**阿明**：测试。",
                "scene_analysis": {"core_event": "测试"},
                "boards": [{
                    "board_id": "s01_01_v2_p01",
                    "covered_text": "旧文本",
                    "prompt_seed": "旧规划",
                    "draft_prompt": "",
                    "status": "planned",
                    "video_parts": [],
                }],
            }},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value='{"boards":[{"covered_text":"截断'), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/plan-storyboards", json={
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
        })

    assert resp.status_code == 502
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    boards = updated["storyboards"]["v2"]["s01_01"]["boards"]
    assert len(boards) == 1
    assert boards[0]["covered_text"] == "旧文本"
    assert boards[0]["prompt_seed"] == "旧规划"


def test_plan_v2_falls_back_to_per_split_planning(tmp_path):
    project_dir = tmp_path / "逐页规划项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "逐页规划项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "source_scenes": {
            "s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "第一段。\n第二段。",
                "scene_analysis": {"core_event": "测试", "v2_15s_split": ["第一段", "第二段"]},
            }
        },
        "storyboard_route": "v2",
        "storyboards": {
            "v2": {"s01_01": {
                "episode": 1,
                "scene_num": 1,
                "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "第一段。\n第二段。",
                "scene_analysis": {"core_event": "测试", "v2_15s_split": ["第一段", "第二段"]},
                "boards": [],
            }},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    page_1 = json.dumps({
        "covered_text": "第一段。",
        "shot_count": 5,
        "estimated_duration": 10,
        "prompt_seed": "第一页",
        "plan": {"shots": ["1", "2", "3", "4", "5"]},
    }, ensure_ascii=False)
    page_2 = json.dumps({
        "covered_text": "第二段。",
        "shot_count": 5,
        "estimated_duration": 10,
        "prompt_seed": "第二页",
        "plan": {"shots": ["1", "2", "3", "4", "5", "6"]},
    }, ensure_ascii=False)

    with patch("api.routes.prompts.llm.generate_prompt", side_effect=['{"boards":[{"covered_text":"截断', page_1, page_2]), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/plan-storyboards", json={
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
        })

    assert resp.status_code == 200
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    boards = updated["storyboards"]["v2"]["s01_01"]["boards"]
    assert [b["prompt_seed"] for b in boards] == ["第一页", "第二页"]
    assert [b["shot_count"] for b in boards] == [5, 6]


def test_parse_project_dry_run_does_not_write_pipeline(tmp_path):
    project_dir = tmp_path / "预览项目"
    script_dir = project_dir / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "ep01.md").write_text(
        "## 场景1：内 · 客厅 · 夜\n\n**阿明**：测试。",
        encoding="utf-8",
    )

    resp = client.post("/api/project/parse", json={
        "input_dir": str(project_dir),
        "project_name": "预览项目",
        "dry_run": True,
    })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["dry_run"] is True
    assert not (project_dir / "pipeline.json").exists()


def test_generate_character_prompt(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline_with_character()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的角色提示词"), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "name": "婉瑜",
            "appearance_seed": "30多岁，素净，棉质家居服",
            "project_name": "测试项目",
        })
    assert resp.status_code == 200
    assert resp.json()["prompt"] == "生成的角色提示词"


def test_generate_scene_prompt_forbids_people(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    pipeline_data["assets"]["scenes"]["客厅"] = {
        "seed": "开放式客厅，餐厅相连，暖光",
        "draft_prompt": "",
        "status": "needed",
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的场景提示词") as gen_mock, \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/generate", json={
            "type": "scene",
            "name": "客厅",
            "appearance_seed": "开放式客厅，餐厅相连，暖光",
            "project_path": str(project_dir),
        })

    assert resp.status_code == 200
    system_prompt = gen_mock.call_args.args[1]
    assert "no people" in system_prompt.lower()
    assert "禁止出现任何人物" in system_prompt


def test_generate_storyboard_prompt(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    (project_dir / "scenes_props" / "小乐卧室").mkdir(parents=True)
    (project_dir / "scenes_props" / "故事书").mkdir(parents=True)

    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v1": {"E01-S1-卧室": {
                "episode": 1, "scene_num": 1,
                "script_title": "第1集·场景1·卧室",
                "characters_in_scene": ["婉瑜"],
                "scene_location": "小乐卧室",
                "script_segment": "妈妈，爸爸藏在衣柜里30天了",
                "draft_prompt": "",
                "status": "locked",
                "board_task_id": None,
                "video_parts": [],
                "boards": [{
                    "board_id": "E01-S1-卧室_v1_p01",
                    "covered_text": "妈妈，爸爸藏在衣柜里30天了",
                    "prompt_seed": "锁定规划种子",
                    "plan": {"shots": 9},
                    "asset_refs": {"characters": ["婉瑜"], "scene": "小乐卧室", "props": ["故事书"]},
                    "draft_prompt": "",
                    "status": "locked",
                    "video_parts": [],
                }],
            }}
        }
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    char_meta = {"name": "婉瑜", "primary_image": "婉瑜.png",
                 "versions": [{"filename": "婉瑜.png", "prompt": {"optimized": "30多岁，素净外貌段"}}]}
    (project_dir / "characters" / "婉瑜" / "meta.json").write_text(
        json.dumps(char_meta, ensure_ascii=False), encoding="utf-8")

    scene_meta = {"name": "小乐卧室", "primary_image": "小乐卧室.png",
                  "versions": [{"filename": "小乐卧室.png", "prompt": {"optimized": "色调：暖黄色调色调段"}}]}
    (project_dir / "scenes_props" / "小乐卧室" / "meta.json").write_text(
        json.dumps(scene_meta, ensure_ascii=False), encoding="utf-8")

    prop_meta = {"name": "故事书", "primary_image": "故事书.png",
                 "versions": [{"filename": "故事书.png", "prompt": {"optimized": "旧绘本，硬壳封面"}}]}
    (project_dir / "scenes_props" / "故事书" / "meta.json").write_text(
        json.dumps(prop_meta, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的故事板提示词") as gen_mock, \
         patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_name": "测试项目",
            "board_version": "v1",
            "scene_key": "E01-S1-卧室",
            "board_id": "E01-S1-卧室_v1_p01",
            "characters": ["婉瑜"],
            "scene_location": "小乐卧室",
            "script_segment": "妈妈，爸爸藏在衣柜里30天了",
        })
    assert resp.status_code == 200
    assert resp.json()["prompt"] == "生成的故事板提示词"
    user_message = gen_mock.call_args.args[2]
    assert "锁定资产引用" in user_message
    assert "婉瑜" in user_message
    assert "素净外貌段" in user_message
    assert "小乐卧室" in user_message
    assert "暖黄色调色调段" in user_message
    assert "故事书" in user_message
    assert "旧绘本，硬壳封面" in user_message


def test_generate_storyboard_prompt_uses_version_specific_template(tmp_path):
    seen_systems = []

    def fake_generate(api_key, system, user_message):
        seen_systems.append(system)
        return "ok"

    with patch("api.routes.prompts.llm.generate_prompt", side_effect=fake_generate), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        for version in ("v1", "v2"):
            project_dir = tmp_path / f"测试项目-{version}"
            project_dir.mkdir()
            pipeline_data = {
                "project": f"测试项目-{version}",
                "assets": {"characters": {}, "scenes": {}, "props": {}},
                "storyboard_route": version,
                "storyboards": {
                    version: {"s01_01": {
                "episode": 1, "scene_num": 1, "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"], "scene_location": "客厅",
                "script_segment": "**阿明**：测试。", "draft_prompt": "",
                "status": "locked", "board_task_id": None, "video_parts": [],
                "boards": [{"board_id": f"s01_01_{version}_p01", "covered_text": "**阿明**：测试。", "prompt_seed": f"{version} seed", "status": "locked", "draft_prompt": "", "video_parts": []}],
            }},
                },
            }
            (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
            resp = client.post("/api/prompts/generate", json={
                "type": "storyboard",
                "project_path": str(project_dir),
                "board_version": version,
                "scene_key": "s01_01",
                "board_id": f"s01_01_{version}_p01",
                "characters": ["阿明"],
                "scene_location": "客厅",
                "script_segment": "**阿明**：测试。",
            })
            assert resp.status_code == 200

    assert "3x3" in seen_systems[0]
    assert "共9格" in seen_systems[0]
    assert "5-6" in seen_systems[1]
    assert "单张总时长不超过15秒" in seen_systems[1]
    assert "3x3" not in seen_systems[1]


def test_generate_video_prompt_uses_v2_template(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v2": {"s01_01": {
                "episode": 1, "scene_num": 1, "script_title": "第1集·场景1·客厅",
                "characters_in_scene": ["阿明"], "scene_location": "客厅",
                "script_segment": "**阿明**：测试。", "draft_prompt": "",
                "status": "completed", "board_task_id": "board_v2", "video_parts": [],
            }},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    seen_systems = []

    def fake_generate(api_key, system, user_message):
        seen_systems.append(system)
        return "---PART1---\nc1,2.5s,测试\nc2,12.0s,测试"

    with patch("api.routes.prompts.llm.generate_prompt", side_effect=fake_generate), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/generate", json={
            "type": "video",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "script_segment": "**阿明**：测试。",
            "panels": [{"index": 1, "timecode": "0.0-2.5s", "shot": "中景", "action": "走"}],
        })

    assert resp.status_code == 200
    assert "5-6 个镜头" in seen_systems[0]
    assert "不要假设一定是9格" in seen_systems[0]
    assert "9:16" in seen_systems[0]
    assert "竖屏" in seen_systems[0]
    assert "无 BGM" in seen_systems[0]
    assert "无字幕" in seen_systems[0]
    assert "no BGM" in resp.json()["prompt"]
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    part = updated["storyboards"]["v2"]["s01_01"]["video_parts"][0]
    assert part["duration"] == 15
    assert "no BGM" in part["draft_prompt"]
    assert "no subtitles" in part["draft_prompt"]


def test_submit_v2_video_uses_vertical_ratio_and_infers_references(tmp_path):
    project_dir = tmp_path / "视频项目"
    (project_dir / "characters" / "阿明").mkdir(parents=True)
    (project_dir / "scenes_props" / "客厅").mkdir(parents=True)
    (project_dir / "storyboards" / "v2" / "s01_01").mkdir(parents=True)
    (project_dir / "characters" / "阿明" / "阿明.png").write_bytes(b"char")
    (project_dir / "scenes_props" / "客厅" / "客厅.png").write_bytes(b"scene")
    (project_dir / "storyboards" / "v2" / "s01_01" / "s01_01_v2_p01.png").write_bytes(b"board")
    pipeline_data = {
        "project": "视频项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v2": {"s01_01": {
                "characters_in_scene": ["阿明"], "scene_location": "客厅",
                "status": "completed", "video_parts": [{
                    "part": 1, "draft_prompt": "视频提示词", "prompt": "视频提示词",
                    "duration": 15, "video_status": "drafted",
                }],
                "boards": [{
                    "board_id": "s01_01_v2_p01", "status": "completed",
                    "result_url": "storyboards/v2/s01_01/s01_01_v2_p01.png",
                    "video_parts": [{
                        "part": 1, "draft_prompt": "视频提示词", "prompt": "视频提示词",
                        "duration": 15, "video_status": "drafted",
                    }],
                }],
            }},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task", return_value="video_task") as submit_mock, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "board_id": "s01_01_v2_p01",
            "part": 1,
            "prompt": "视频提示词",
            "duration": 15,
        })

    assert resp.status_code == 200
    _, _, image_paths = submit_mock.call_args.args
    assert submit_mock.call_args.kwargs["ratio"] == "9:16"
    submitted_prompt = submit_mock.call_args.args[1]
    assert "无 BGM" in submitted_prompt
    assert "无字幕" in submitted_prompt
    rel_paths = {str(Path(p).relative_to(project_dir)) for p in image_paths}
    assert rel_paths == {
        "characters/阿明/阿明.png",
        "scenes_props/客厅/客厅.png",
        "storyboards/v2/s01_01/s01_01_v2_p01.png",
    }
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    part = updated["storyboards"]["v2"]["s01_01"]["boards"][0]["video_parts"][0]
    assert "无 BGM" in part["draft_prompt"]
    assert "无字幕" in part["prompt"]


def test_submit_storyboard_uses_board_asset_refs(tmp_path):
    project_dir = tmp_path / "故事板资产引用项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    (project_dir / "scenes_props" / "小乐卧室").mkdir(parents=True)
    (project_dir / "scenes_props" / "故事书").mkdir(parents=True)
    (project_dir / "characters" / "婉瑜" / "婉瑜.png").write_bytes(b"char")
    (project_dir / "scenes_props" / "小乐卧室" / "小乐卧室.png").write_bytes(b"scene")
    (project_dir / "scenes_props" / "故事书" / "故事书.png").write_bytes(b"prop")
    pipeline_data = {
        "project": "故事板资产引用项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboard_route": "v2",
        "storyboards": {
            "v2": {"s01_01": {
                "characters_in_scene": ["其他人"],
                "scene_location": "其他场景",
                "boards": [{
                    "board_id": "s01_01_v2_p01",
                    "covered_text": "测试",
                    "draft_prompt": "最终提示词",
                    "status": "drafted",
                    "asset_refs": {"characters": ["婉瑜"], "scene": "小乐卧室", "props": ["故事书"]},
                    "video_parts": [],
                }],
            }},
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "board_task"}) as submit_mock, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "board_id": "s01_01_v2_p01",
            "prompt": "最终提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    image_paths = submit_mock.call_args.args[2]
    rel_paths = {str(Path(p).relative_to(project_dir)) for p in image_paths}
    assert rel_paths == {
        "characters/婉瑜/婉瑜.png",
        "scenes_props/小乐卧室/小乐卧室.png",
        "scenes_props/故事书/故事书.png",
    }


def test_submit_video_returns_clear_502_when_wetoken_fails(tmp_path):
    project_dir = tmp_path / "视频失败项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "视频失败项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"v2": {"s01_01": {
            "characters_in_scene": [], "scene_location": "",
            "status": "completed", "video_parts": [{
                "part": 1, "draft_prompt": "视频提示词", "prompt": "视频提示词",
                "duration": 15, "video_status": "drafted",
            }],
            "boards": [{
                "board_id": "s01_01_v2_p01", "status": "completed",
                "video_parts": [{
                    "part": 1, "draft_prompt": "视频提示词", "prompt": "视频提示词",
                    "duration": 15, "video_status": "drafted",
                }],
            }],
        }}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task", side_effect=Exception("素材超时")), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "board_version": "v2",
            "scene_key": "s01_01",
            "board_id": "s01_01_v2_p01",
            "part": 1,
            "prompt": "视频提示词",
            "duration": 15,
        })

    assert resp.status_code == 502
    assert "Wetoken API 错误" in resp.json()["detail"]


def test_submit_v1_video_uses_horizontal_ratio(tmp_path):
    project_dir = tmp_path / "横屏项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "横屏项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"v1": {"s01_01": {
            "characters_in_scene": [], "scene_location": "",
            "status": "completed", "video_parts": [],
        }}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task", return_value="video_task") as submit_mock, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "board_version": "v1",
            "scene_key": "s01_01",
            "part": 1,
            "prompt": "视频提示词",
            "duration": 10,
        })

    assert resp.status_code == 200
    assert submit_mock.call_args.kwargs["ratio"] == "16:9"


def test_submit_character_task(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = _make_pipeline_with_character()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "task_abc"}), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"), \
         patch("api.routes.tasks.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_name": "测试项目",
            "name": "婉瑜",
            "prompt": "完整角色提示词",
            "image_paths": [],
        })
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task_abc"
    assert resp.json()["status"] == "submitted"
    # pipeline.json 里状态已更新（flat 格式）
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    asset = updated["assets"]["characters"]["婉瑜"]
    assert asset["status"] == "submitted"
    assert asset["task_id"] == "task_abc"
    assert asset["submitted_at"]
    assert asset["last_checked_at"] is None
    assert asset["status_message"] == "已提交，等待生成结果"


def test_resubmit_character_archives_existing_asset_after_submit_success(tmp_path):
    project_dir = tmp_path / "测试项目"
    old_file = project_dir / "characters" / "婉瑜" / "婉瑜.png"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old image")
    pipeline_data = _make_pipeline_with_character()
    pipeline_data["assets"]["characters"]["婉瑜"].update({
        "status": "completed",
        "draft_prompt": "完整角色提示词",
        "result_url": "characters/婉瑜/婉瑜.png",
        "completed_at": "2026-01-01T00:00:00",
    })
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "new_task"}), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "prompt": "完整角色提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    asset = updated["assets"]["characters"]["婉瑜"]
    assert asset["status"] == "submitted"
    assert asset["task_id"] == "new_task"
    assert asset["result_url"] is None
    assert "completed_at" not in asset
    archived_path = asset["archived_results"][0]["path"]
    assert archived_path.startswith("_archived_resubmissions/")
    assert (project_dir / archived_path).read_bytes() == b"old image"
    assert not old_file.exists()


def test_failed_resubmit_keeps_existing_character_asset(tmp_path):
    project_dir = tmp_path / "测试项目"
    old_file = project_dir / "characters" / "婉瑜" / "婉瑜.png"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old image")
    pipeline_data = _make_pipeline_with_character()
    pipeline_data["assets"]["characters"]["婉瑜"].update({
        "status": "completed",
        "draft_prompt": "完整角色提示词",
        "result_url": "characters/婉瑜/婉瑜.png",
        "completed_at": "2026-01-01T00:00:00",
    })
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", side_effect=Exception("提交失败")), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "prompt": "完整角色提示词",
            "image_paths": [],
        })

    assert resp.status_code == 502
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    asset = updated["assets"]["characters"]["婉瑜"]
    assert asset["status"] == "completed"
    assert asset["result_url"] == "characters/婉瑜/婉瑜.png"
    assert old_file.read_bytes() == b"old image"
    assert not (project_dir / "_archived_resubmissions").exists()


def test_submit_scene_task_forces_empty_location_prompt(tmp_path):
    project_dir = tmp_path / "场景项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline("场景项目")
    pipeline_data["assets"]["scenes"]["客厅"] = {
        "seed": "客厅里有人站在窗边",
        "draft_prompt": "Create a living room with a person near the window.",
        "status": "drafted",
        "task_id": None,
        "result_url": None,
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "scene_task"}) as submit_mock, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "scene",
            "project_path": str(project_dir),
            "name": "客厅",
            "prompt": pipeline_data["assets"]["scenes"]["客厅"]["draft_prompt"],
            "image_paths": [],
        })

    assert resp.status_code == 200
    submitted_prompt = submit_mock.call_args.args[1]
    assert "STRICT EMPTY LOCATION REQUIREMENT" in submitted_prompt
    assert "zero people" in submitted_prompt
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "纯场景空镜参考图" in updated["assets"]["scenes"]["客厅"]["draft_prompt"]


def test_retry_failed_task(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = _make_pipeline_with_character()
    pipeline_data["assets"]["characters"]["婉瑜"]["status"] = "failed"
    pipeline_data["assets"]["characters"]["婉瑜"]["task_id"] = "old_task"
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "new_task"}), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"), \
         patch("api.routes.tasks.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/tasks/old_task/retry", json={
            "type": "character",
            "project_name": "测试项目",
            "name": "婉瑜",
            "prompt": "提示词",
            "image_paths": [],
        })
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "new_task"


def test_chat_returns_reply(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(
        json.dumps(_make_pipeline(), ensure_ascii=False),
        encoding="utf-8"
    )
    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "当前有2个场景", "actions": [], "_raw": "{}"}), \
         patch("api.routes.chat.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/chat", json={
            "project_name": "测试项目",
            "message": "有多少场景？",
            "history": [],
        })
    assert resp.status_code == 200
    assert resp.json()["reply"] == "当前有2个场景"
    assert resp.json()["tool_results"] == []
    assert resp.json()["has_writes"] == False


def test_chat_updates_versioned_board_prompt(tmp_path):
    project_dir = tmp_path / "助手项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "助手项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v2": {
                "s01_01": {
                    "episode": 1,
                    "scene_num": 1,
                    "script_title": "第1集·场景1·客厅",
                    "characters_in_scene": [],
                    "scene_location": "客厅",
                    "script_segment": "测试",
                    "boards": [
                        {
                            "board_id": "s01_01_v2_p01",
                            "page": 1,
                            "total_pages": 2,
                            "layout": "director_sheet_15s",
                            "shot_count": 5,
                            "estimated_duration": 12,
                            "covered_text": "第一页",
                            "draft_prompt": "旧提示词",
                            "status": "drafted",
                            "board_task_id": None,
                            "video_parts": [],
                        },
                        {
                            "board_id": "s01_01_v2_p02",
                            "page": 2,
                            "total_pages": 2,
                            "layout": "director_sheet_15s",
                            "shot_count": 5,
                            "estimated_duration": 10,
                            "covered_text": "第二页",
                            "draft_prompt": "第二页提示词",
                            "status": "drafted",
                            "board_task_id": None,
                            "video_parts": [],
                        },
                    ],
                }
            }
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={
                   "reply": "已修改",
                   "actions": [{
                       "action": "update_draft_prompt",
                       "target": "storyboard",
                       "name": "s01_01",
                       "board_version": "v2",
                       "board_id": "s01_01_v2_p02",
                       "value": "新提示词",
                   }],
                   "_raw": "{}",
               }), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_name": str(project_dir),
            "message": "修改v2第二张故事板",
            "history": [],
            "current_scene_key": "s01_01",
            "active_board_version": "v2",
        })

    assert resp.status_code == 200
    assert resp.json()["has_writes"] is True
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    boards = updated["storyboards"]["v2"]["s01_01"]["boards"]
    assert boards[0]["draft_prompt"] == "旧提示词"
    assert boards[1]["draft_prompt"] == "新提示词"
    assert boards[1]["status"] == "drafted"


def test_chat_submits_versioned_board_task(tmp_path):
    project_dir = tmp_path / "助手提交项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "助手提交项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v2": {
                "s01_01": {
                    "episode": 1,
                    "scene_num": 1,
                    "script_title": "第1集·场景1·客厅",
                    "characters_in_scene": [],
                    "scene_location": "客厅",
                    "script_segment": "测试",
                    "boards": [{
                        "board_id": "s01_01_v2_p01",
                        "page": 1,
                        "total_pages": 1,
                        "layout": "director_sheet_15s",
                        "shot_count": 5,
                        "estimated_duration": 12,
                        "covered_text": "第一页",
                        "draft_prompt": "故事板提示词",
                        "status": "drafted",
                        "board_task_id": None,
                        "video_parts": [],
                    }],
                }
            }
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={
                   "reply": "已提交",
                   "actions": [{
                       "action": "submit_task",
                       "target": "storyboard",
                       "name": "s01_01",
                       "board_version": "v2",
                       "board_id": "s01_01_v2_p01",
                   }],
                   "_raw": "{}",
               }), \
         patch("api.vidu.submit_image_task", return_value={"task_id": "chat_board_task"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_name": str(project_dir),
            "message": "提交v2第一张故事板",
            "history": [],
            "current_scene_key": "s01_01",
            "active_board_version": "v2",
        })

    assert resp.status_code == 200
    assert resp.json()["has_writes"] is True
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    board = updated["storyboards"]["v2"]["s01_01"]["boards"][0]
    assert board["status"] == "submitted"
    assert board["board_task_id"] == "chat_board_task"


def test_chat_submits_v2_video_with_vertical_ratio_and_references(tmp_path):
    project_dir = tmp_path / "助手视频项目"
    (project_dir / "characters" / "阿明").mkdir(parents=True)
    (project_dir / "scenes_props" / "客厅").mkdir(parents=True)
    (project_dir / "storyboards" / "v2" / "s01_01").mkdir(parents=True)
    (project_dir / "characters" / "阿明" / "阿明.png").write_bytes(b"char")
    (project_dir / "scenes_props" / "客厅" / "客厅.png").write_bytes(b"scene")
    (project_dir / "storyboards" / "v2" / "s01_01" / "s01_01_v2_p01.png").write_bytes(b"board")
    pipeline_data = {
        "project": "助手视频项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "v2": {
                "s01_01": {
                    "characters_in_scene": ["阿明"],
                    "scene_location": "客厅",
                    "boards": [{
                        "board_id": "s01_01_v2_p01",
                        "status": "completed",
                        "result_url": "storyboards/v2/s01_01/s01_01_v2_p01.png",
                        "video_parts": [{
                            "part": 1,
                            "draft_prompt": "视频提示词",
                            "prompt": "视频提示词",
                            "duration": 15,
                            "video_status": "drafted",
                        }],
                    }],
                }
            }
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={
                   "reply": "已提交",
                   "actions": [{
                       "action": "submit_task",
                       "target": "video_part",
                       "name": "s01_01",
                       "board_version": "v2",
                       "board_id": "s01_01_v2_p01",
                       "part": 1,
                   }],
                   "_raw": "{}",
               }), \
         patch("api.routes.chat.wetoken.submit_video_task", return_value="chat_video_task") as submit_mock, \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_name": str(project_dir),
            "message": "提交v2视频",
            "history": [],
            "current_scene_key": "s01_01",
            "active_board_version": "v2",
        })

    assert resp.status_code == 200
    assert resp.json()["has_writes"] is True
    _, _, image_paths = submit_mock.call_args.args
    assert submit_mock.call_args.kwargs["ratio"] == "9:16"
    rel_paths = {str(Path(p).relative_to(project_dir)) for p in image_paths}
    assert rel_paths == {
        "characters/阿明/阿明.png",
        "scenes_props/客厅/客厅.png",
        "storyboards/v2/s01_01/s01_01_v2_p01.png",
    }
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    part = updated["storyboards"]["v2"]["s01_01"]["boards"][0]["video_parts"][0]
    assert part["video_status"] == "submitted"
    assert part["video_task_id"] == "chat_video_task"
    assert part["ratio"] == "9:16"


def test_batch_generate_prompts(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt_async", return_value="批量生成的提示词"), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/prompts/batch-generate", json={
            "project_name": "测试项目",
            "items": [
                {"type": "character", "name": "婉瑜", "appearance_seed": "素净"},
                {"type": "scene", "name": "卧室", "appearance_seed": "暖色调"},
            ]
        })
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert results[0]["name"] == "婉瑜"
    assert results[1]["name"] == "卧室"


def test_batch_submit_tasks(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = _make_pipeline_with_character()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task_async", return_value={"task_id": "task_batch_1"}), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"), \
         patch("api.routes.tasks.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/tasks/batch-submit", json={
            "project_name": "测试项目",
            "items": [
                {"type": "character", "name": "婉瑜", "prompt": "提示词", "image_paths": []},
            ]
        })
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert results[0]["task_id"] == "task_batch_1"


def test_get_prompt_templates_defaults(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目"})
    assert resp.status_code == 200
    data = resp.json()
    assert "character" in data
    # 内置默认值是 string
    assert isinstance(data["character"], str)


def test_get_prompt_templates_with_defaults_flag(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目", "defaults": "true"})
    assert resp.status_code == 200
    assert "character" in resp.json()


def test_put_prompt_templates(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = _make_pipeline()
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        # Save custom template (flat string → auto-wraps to variant format)
        resp = client.put("/api/project/prompt-templates",
                          json={"project_name": "测试项目", "updates": {"character": "自定义角色模板"}})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Read back - should be plain string
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目"})
        assert resp.status_code == 200
        char_template = resp.json()["character"]
        assert char_template == "自定义角色模板"


def test_settings_support_deepseek_provider():
    resp = client.put("/api/settings", json={
        "llm_provider": "deepseek",
        "deepseek_api_key": "ds-secret",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_model": "deepseek-v4-flash",
    })
    assert resp.status_code == 200

    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] == "deepseek"
    assert data["_has_deepseek"] is True
    assert data["deepseek_api_key"].endswith("cret")
    assert data["deepseek_base_url"] == "https://api.deepseek.com"
    assert data["deepseek_model"] == "deepseek-v4-flash"
