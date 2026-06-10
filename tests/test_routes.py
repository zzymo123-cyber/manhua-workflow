import json, pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app

client = TestClient(app)


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


def test_generate_storyboard_prompt(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    (project_dir / "scenes_props" / "小乐卧室").mkdir(parents=True)

    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1-卧室": {
                "episode": 1, "scene_num": 1,
                "script_title": "第1集·场景1·卧室",
                "characters_in_scene": ["婉瑜"],
                "scene_location": "小乐卧室",
                "script_segment": "妈妈，爸爸藏在衣柜里30天了",
                "dependency_stale": False, "stale_reasons": [],
                "draft_prompt": "",
                "board_status": "needed",
                "board_task_id": None,
                "video_parts": [],
            }
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

    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的故事板提示词"), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_name": "测试项目",
            "scene_key": "E01-S1-卧室",
            "characters": ["婉瑜"],
            "scene_location": "小乐卧室",
            "script_segment": "妈妈，爸爸藏在衣柜里30天了",
        })
    assert resp.status_code == 200
    assert resp.json()["prompt"] == "生成的故事板提示词"


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
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "submitted"
    assert updated["assets"]["characters"]["婉瑜"]["task_id"] == "task_abc"


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
