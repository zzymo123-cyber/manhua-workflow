import json, pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app

client = TestClient(app)


def test_import_project_pipeline_not_found(tmp_path):
    """pipeline.json 不存在时返回 404"""
    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/project/import", json={"project_name": "不存在的项目"})
    assert resp.status_code == 404


def test_import_project_success(tmp_path):
    """pipeline.json 存在时返回其内容"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {"characters": {}}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/project/import", json={"project_name": "测试项目"})
    assert resp.status_code == 200
    assert resp.json()["project"] == "测试项目"
    assert resp.json()["_exists"] is True


def test_get_project_status(tmp_path):
    """GET /api/project/status 返回 pipeline.json 内容"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/status", params={"project_name": "测试项目"})
    assert resp.status_code == 200
    assert resp.json()["project"] == "测试项目"


def test_generate_character_prompt():
    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的角色提示词"), \
         patch("api.routes.prompts.os.environ.get", return_value="test_key"):
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

    char_meta = {"name": "婉瑜", "primary_image": "婉瑜.png",
                 "versions": [{"filename": "婉瑜.png", "prompt": {"optimized": "30多岁，素净外貌段"}}]}
    (project_dir / "characters" / "婉瑜" / "meta.json").write_text(
        json.dumps(char_meta, ensure_ascii=False), encoding="utf-8")

    scene_meta = {"name": "小乐卧室", "primary_image": "小乐卧室.png",
                  "versions": [{"filename": "小乐卧室.png", "prompt": {"optimized": "色调：暖黄色调色调段"}}]}
    (project_dir / "scenes_props" / "小乐卧室" / "meta.json").write_text(
        json.dumps(scene_meta, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的故事板提示词"), \
         patch("api.routes.prompts.os.environ.get", return_value="test_key"), \
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
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "task_abc", "image_url": "https://example.com/img.png"}), \
         patch("api.routes.tasks.vidu.download_image"), \
         patch("api.routes.tasks.os.environ.get", return_value="test_key"), \
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
    assert resp.json()["status"] == "completed"
    # pipeline.json 里状态已更新
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "completed"
    assert updated["assets"]["characters"]["婉瑜"]["task_id"] == "task_abc"


def test_retry_failed_task(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "failed", "task_id": "old_task", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "new_task", "image_url": "https://example.com/img.png"}), \
         patch("api.routes.tasks.vidu.download_image"), \
         patch("api.routes.tasks.os.environ.get", return_value="test_key"), \
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
        json.dumps({"project": "测试项目", "assets": {}, "storyboards": {}}, ensure_ascii=False),
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
    """POST /api/prompts/batch-generate 批量生成提示词"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {"characters": {}, "scenes": {}}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="批量生成的提示词"), \
         patch("api.routes.prompts.os.environ.get", return_value="test_key"), \
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
    """POST /api/tasks/batch-submit 批量提交任务"""
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "task_batch_1", "image_url": "https://example.com/img.png"}), \
         patch("api.routes.tasks.vidu.download_image"), \
         patch("api.routes.tasks.os.environ.get", return_value="test_key"), \
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
    """GET prompt-templates returns defaults when file doesn't exist"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目"})
    assert resp.status_code == 200
    data = resp.json()
    assert "character" in data
    assert len(data["character"]) > 0


def test_get_prompt_templates_with_defaults_flag(tmp_path):
    """GET prompt-templates?defaults=true returns built-in defaults without reading file"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目", "defaults": "true"})
    assert resp.status_code == 200
    assert "character" in resp.json()


def test_put_prompt_templates(tmp_path):
    """PUT prompt-templates saves and can be read back"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        # Save custom template
        resp = client.put("/api/project/prompt-templates",
                          params={"project_name": "测试项目"},
                          json={"character": "自定义角色模板"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Read back
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目"})
        assert resp.status_code == 200
        assert resp.json()["character"] == "自定义角色模板"
