import json
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, check_env, get_configured_port
from api.pipeline import ProjectFileWriteError

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "service": "manhua-workflow"}


def test_get_configured_port_accepts_valid_port(monkeypatch):
    monkeypatch.setenv("MANHUA_PORT", "8010")

    assert get_configured_port() == 8010


def test_get_configured_port_rejects_invalid_port(monkeypatch):
    monkeypatch.setenv("MANHUA_PORT", "abc")

    try:
        get_configured_port()
    except ValueError as exc:
        assert "1-65535" in str(exc)
    else:
        raise AssertionError("Expected invalid MANHUA_PORT to raise ValueError")


def test_get_configured_port_rejects_out_of_range_port(monkeypatch):
    monkeypatch.setenv("MANHUA_PORT", "70000")

    try:
        get_configured_port()
    except ValueError as exc:
        assert "1-65535" in str(exc)
    else:
        raise AssertionError("Expected out-of-range MANHUA_PORT to raise ValueError")


def test_check_env_reads_saved_settings(monkeypatch):
    for key in ("VIDU_API_KEY", "WETOKEN_API_KEY", "IDEALAB_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    from api.routes.settings import write_settings

    write_settings({
        "vidu_api_key": "vidu-test",
        "wetoken_api_key": "wetoken-test",
        "idealab_api_key": "idealab-test",
    })

    assert check_env() == []


def test_write_settings_replaces_atomically():
    from api.routes import settings
    from api.routes.settings import read_settings, write_settings

    write_settings({"vidu_api_key": "vidu-test"})

    assert read_settings()["vidu_api_key"] == "vidu-test"
    assert not settings.SETTINGS_PATH.with_suffix(".tmp").exists()


def test_get_settings_requires_complete_github_config():
    from api.routes.settings import write_settings

    write_settings({
        "gh_token": "github-secret-token",
        "gh_owner": "comic-owner",
    })

    resp = client.get("/api/settings")

    assert resp.status_code == 200
    assert resp.json()["_has_gh"] is False

    write_settings({
        "gh_token": "github-secret-token",
        "gh_owner": "comic-owner",
        "gh_repo": "comic-assets",
    })

    resp = client.get("/api/settings")

    assert resp.status_code == 200
    data = resp.json()
    assert data["_has_gh"] is True
    assert data["gh_token"].endswith("oken")
    assert data["gh_token"].startswith("*")
    assert data["gh_owner"] == "comic-owner"
    assert data["gh_repo"] == "comic-assets"


def test_update_settings_saves_github_config():
    resp = client.put("/api/settings", json={
        "gh_token": "github-secret-token",
        "gh_owner": "comic-owner",
        "gh_repo": "comic-assets",
    })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = client.get("/api/settings")

    assert resp.status_code == 200
    data = resp.json()
    assert data["_has_gh"] is True
    assert data["gh_owner"] == "comic-owner"
    assert data["gh_repo"] == "comic-assets"


def test_update_settings_can_clear_saved_config():
    from api.routes.settings import write_settings

    write_settings({
        "vidu_api_key": "vidu-test",
        "wetoken_api_key": "wetoken-test",
        "idealab_api_key": "idealab-test",
        "gh_token": "github-secret-token",
        "gh_owner": "comic-owner",
        "gh_repo": "comic-assets",
    })

    resp = client.put("/api/settings", json={
        "vidu_api_key": "",
        "wetoken_api_key": "",
        "idealab_api_key": "",
        "gh_token": "",
        "gh_owner": "",
        "gh_repo": "",
    })

    assert resp.status_code == 200

    resp = client.get("/api/settings")

    assert resp.status_code == 200
    data = resp.json()
    assert data["_has_vidu"] is False
    assert data["_has_wetoken"] is False
    assert data["_has_idealab"] is False
    assert data["_has_gh"] is False
    assert data["gh_owner"] == ""
    assert data["gh_repo"] == ""


def test_list_recent_skips_malformed_entries(tmp_path):
    from api.routes.settings import write_settings

    project_dir = tmp_path / "有效项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(
        json.dumps({"project": "有效项目", "assets": {}, "storyboards": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    write_settings({
        "recent_projects": [
            "broken",
            {"name": "缺路径"},
            {"name": "不存在", "path": str(tmp_path / "missing")},
            {"name": "有效项目", "path": str(project_dir)},
        ]
    })

    resp = client.get("/api/project/list-recent")

    assert resp.status_code == 200
    assert resp.json()["projects"] == [{"name": "有效项目", "path": str(project_dir)}]


def test_import_project_recovers_from_malformed_recent_projects(tmp_path):
    from api.routes.settings import read_settings, write_settings

    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(
        json.dumps({"project": "测试项目", "assets": {}, "storyboards": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    write_settings({"recent_projects": ["broken", {"path": str(project_dir)}]})

    resp = client.post("/api/project/import", json={"project_path": str(project_dir)})

    assert resp.status_code == 200
    recent = read_settings()["recent_projects"]
    assert recent == [{"name": "测试项目", "path": str(project_dir)}]


def test_import_project_ignores_recent_write_failure(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.settings.write_settings", side_effect=OSError("磁盘已满")):
        resp = client.post("/api/project/import", json={"project_path": str(project_dir)})

    assert resp.status_code == 200
    assert resp.json()["project"] == "测试项目"
    assert resp.json()["_exists"] is True


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


def test_import_project_invalid_pipeline_returns_clear_400(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text("{bad json", encoding="utf-8")

    resp = client.post("/api/project/import", json={"project_path": str(project_dir)})

    assert resp.status_code == 400
    assert "pipeline.json 不是有效 JSON" in resp.json()["detail"]


def _write_minimal_input_dir(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "character_visuals.md").write_text("## 婉瑜\n30多岁，素净", encoding="utf-8")
    (input_dir / "scene_props_visuals.md").write_text("### 卧室\n普通卧室", encoding="utf-8")
    (input_dir / "script").mkdir(exist_ok=True)
    (input_dir / "script" / "ep01.md").write_text("## 场景1：内 · 卧室 · 夜\n**婉瑜**：你好", encoding="utf-8")


def test_parse_project_trims_project_name(tmp_path):
    from api.routes.settings import read_settings

    input_dir = tmp_path / "输入目录"
    _write_minimal_input_dir(input_dir)

    resp = client.post("/api/project/parse", json={
        "input_dir": str(input_dir),
        "project_name": "  测试项目  ",
    })

    assert resp.status_code == 200
    assert resp.json()["project_name"] == "测试项目"
    assert resp.json()["input_dir"] == str(input_dir.resolve())
    parsed = json.loads((input_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert parsed["project"] == "测试项目"
    assert read_settings()["recent_projects"][0] == {
        "name": "测试项目",
        "path": str(input_dir.resolve()),
    }


def test_parse_project_ignores_recent_write_failure(tmp_path):
    input_dir = tmp_path / "输入目录"
    _write_minimal_input_dir(input_dir)

    with patch("api.routes.settings.write_settings", side_effect=OSError("磁盘已满")):
        resp = client.post("/api/project/parse", json={
            "input_dir": str(input_dir),
            "project_name": "测试项目",
        })

    assert resp.status_code == 200
    assert resp.json()["project_name"] == "测试项目"
    assert (input_dir / "pipeline.json").exists()


def test_parse_project_rejects_blank_project_name(tmp_path):
    input_dir = tmp_path / "输入目录"
    _write_minimal_input_dir(input_dir)

    resp = client.post("/api/project/parse", json={
        "input_dir": str(input_dir),
        "project_name": "   ",
    })

    assert resp.status_code == 400
    assert "项目名称不能为空" in resp.json()["detail"]
    assert not (input_dir / "pipeline.json").exists()


def test_parse_project_requires_script_directory(tmp_path):
    input_dir = tmp_path / "输入目录"
    input_dir.mkdir()
    (input_dir / "character_visuals.md").write_text("## 婉瑜\n30多岁，素净", encoding="utf-8")
    (input_dir / "scene_props_visuals.md").write_text("### 卧室\n普通卧室", encoding="utf-8")
    (input_dir / "script").write_text("not a directory", encoding="utf-8")

    resp = client.post("/api/project/parse", json={
        "input_dir": str(input_dir),
        "project_name": "测试项目",
    })

    assert resp.status_code == 400
    assert "script/" in resp.json()["detail"]
    assert not (input_dir / "pipeline.json").exists()


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


def test_get_project_status_accepts_project_path(tmp_path):
    """GET /api/project/status accepts an explicit project_path."""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    resp = client.get("/api/project/status", params={"project_path": str(project_dir)})

    assert resp.status_code == 200
    assert resp.json()["project"] == "测试项目"


def test_generate_character_prompt(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
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
        "assets": {
            "characters": {"婉瑜": {"status": "completed"}},
            "scenes": {"小乐卧室": {"status": "completed"}},
            "props": {},
        },
        "storyboards": {"E01-S1-卧室": {"board_status": "needed"}},
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


def test_generate_character_prompt_accepts_project_path(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="生成的角色提示词"), \
         patch("api.routes.prompts.get_api_key", return_value="test_key"):
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "appearance_seed": "30多岁，素净",
        })

    assert resp.status_code == 200
    assert resp.json()["prompt"] == "生成的角色提示词"

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["draft_prompt"] == "生成的角色提示词"


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
    # pipeline.json 里状态已更新，后台 poller 完成后才会变 completed
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "submitted"
    assert updated["assets"]["characters"]["婉瑜"]["task_id"] == "task_abc"


def test_submit_character_task_accepts_project_path(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "task_path", "image_url": "https://example.com/img.png"}), \
         patch("api.routes.tasks.vidu.download_image"), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "prompt": "完整角色提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task_path"

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "submitted"


def test_submit_character_clears_previous_error(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "failed", "seed": "描述", "error": "上一次失败"}},
            "scenes": {},
            "props": {},
        },
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "task_retry"}), \
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
    assert asset["task_id"] == "task_retry"
    assert "error" not in asset


def test_submit_character_requires_existing_asset(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "prompt": "完整角色提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "未找到角色" in resp.json()["detail"]


def test_submit_character_rejects_blank_prompt_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task") as submit_image, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "prompt": "   ",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "提示词不能为空" in resp.json()["detail"]
    submit_image.assert_not_called()


def test_submit_task_requires_name_for_asset_type(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_path": str(project_dir),
            "prompt": "完整角色提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "缺少角色名称" in resp.json()["detail"]


def test_submit_storyboard_requires_reference_files(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "completed"}}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": ["characters/婉瑜/婉瑜.png"],
        })

    assert resp.status_code == 400
    assert "缺少参考图" in resp.json()["detail"]
    assert "characters/婉瑜/婉瑜.png" in resp.json()["detail"]


def test_submit_storyboard_requires_existing_scene_key(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "未找到故事板" in resp.json()["detail"]


def test_submit_storyboard_requires_completed_declared_references_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "needed"}},
            "scenes": {"卧室": {"status": "completed"}},
            "props": {},
        },
        "storyboards": {
            "E01-S1": {
                "board_status": "needed",
                "characters_in_scene": ["婉瑜"],
                "scene_location": "卧室",
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task") as submit_image, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "前置参考未完成" in resp.json()["detail"]
    assert "角色「婉瑜」未完成" in resp.json()["detail"]
    submit_image.assert_not_called()


def test_submit_storyboard_adds_declared_reference_images(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    char_image = project_dir / "characters" / "婉瑜" / "婉瑜.png"
    char_image.write_bytes(b"fake-char")
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "completed"}},
            "scenes": {},
            "props": {},
        },
        "storyboards": {
            "E01-S1": {
                "board_status": "needed",
                "characters_in_scene": ["婉瑜"],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "board_task"}) as submit_image, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    submit_image.assert_called_once()
    assert submit_image.call_args.args[2] == [str(char_image)]


def test_submit_storyboard_clears_previous_board_error(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "failed", "board_error": "上一次失败"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.vidu.submit_image_task", return_value={"task_id": "board_retry"}), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    board = updated["storyboards"]["E01-S1"]
    assert board["board_status"] == "submitted"
    assert board["board_task_id"] == "board_retry"
    assert "board_error" not in board


def test_submit_video_requires_part(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"video_parts": []}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "视频提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "缺少视频分段 part" in resp.json()["detail"]


def test_submit_video_clears_previous_output_and_errors(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "storyboards" / "E01-S1").mkdir(parents=True)
    (project_dir / "storyboards" / "E01-S1" / "E01-S1.png").write_bytes(b"fake-board")
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{
                    "part": 1,
                    "video_status": "failed",
                    "video_task_id": "old_task",
                    "video_url": "https://example.com/old.mp4",
                    "local_path": "videos/old.mp4",
                    "video_error": "上一次失败",
                    "video_download_error": "上一次下载失败",
                }],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task", return_value="video_retry"), \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    part = updated["storyboards"]["E01-S1"]["video_parts"][0]
    assert part["video_status"] == "submitted"
    assert part["video_task_id"] == "video_retry"
    assert "video_error" not in part
    assert "video_download_error" not in part
    assert "video_url" not in part
    assert "local_path" not in part


def test_submit_video_uses_storyboard_video_params_when_omitted(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "storyboards" / "E01-S1").mkdir(parents=True)
    board_image = project_dir / "storyboards" / "E01-S1" / "E01-S1.png"
    board_image.write_bytes(b"fake-image")
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_duration": 6,
                "video_ratio": "9:16",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task", return_value="video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": ["storyboards/E01-S1/E01-S1.png"],
        })

    assert resp.status_code == 200
    submit_video.assert_called_once()
    assert submit_video.call_args.kwargs["duration"] == 6
    assert submit_video.call_args.kwargs["ratio"] == "9:16"


def test_submit_video_requires_completed_storyboard(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "needed",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "故事板尚未完成" in resp.json()["detail"]
    submit_video.assert_not_called()


def test_submit_video_requires_existing_video_part_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 2,
            "prompt": "视频提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "未找到视频分段" in resp.json()["detail"]
    submit_video.assert_not_called()

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["storyboards"]["E01-S1"]["video_parts"] == [{"part": 1, "video_status": "needed"}]


def test_submit_video_requires_storyboard_reference_image_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "缺少参考图" in resp.json()["detail"]
    assert "storyboards/E01-S1/E01-S1.png" in resp.json()["detail"]
    submit_video.assert_not_called()


def test_submit_video_adds_declared_and_storyboard_reference_images(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    (project_dir / "storyboards" / "E01-S1").mkdir(parents=True)
    char_image = project_dir / "characters" / "婉瑜" / "婉瑜.png"
    board_image = project_dir / "storyboards" / "E01-S1" / "E01-S1.png"
    char_image.write_bytes(b"fake-char")
    board_image.write_bytes(b"fake-board")
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "completed"}}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "characters_in_scene": ["婉瑜"],
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task", return_value="video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": [],
        })

    assert resp.status_code == 200
    submit_video.assert_called_once()
    assert submit_video.call_args.args[2] == [str(char_image), str(board_image)]


def test_submit_video_rejects_blank_prompt_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": " \n\t ",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "提示词不能为空" in resp.json()["detail"]
    submit_video.assert_not_called()


def test_submit_video_rejects_invalid_duration_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": [],
            "duration": 0,
        })

    assert resp.status_code == 400
    assert "视频时长" in resp.json()["detail"]
    submit_video.assert_not_called()


def test_submit_video_rejects_invalid_ratio_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{"part": 1, "video_status": "needed"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.wetoken.submit_video_task") as submit_video, \
         patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": [],
            "ratio": "wide",
        })

    assert resp.status_code == 400
    assert "视频比例" in resp.json()["detail"]
    submit_video.assert_not_called()


def test_submit_task_rejects_reference_path_escape(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not a project asset")
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "completed"}}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": ["../secret.png"],
        })

    assert resp.status_code == 403
    assert "项目目录外" in resp.json()["detail"]


def test_submit_task_rejects_absolute_reference_path(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not a project asset")
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": [str(secret)],
        })

    assert resp.status_code == 403
    assert "项目目录外" in resp.json()["detail"]


def test_submit_task_rejects_windows_absolute_reference_path(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"):
        resp = client.post("/api/tasks/submit", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "prompt": "故事板提示词",
            "image_paths": ["C:\\Users\\Public\\secret.png"],
        })

    assert resp.status_code == 403
    assert "项目目录外" in resp.json()["detail"]


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
        json.dumps({"project": "测试项目", "assets": {}, "storyboards": {}}, ensure_ascii=False),
        encoding="utf-8"
    )
    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "当前有2个场景", "actions": [], "_raw": "{}"}), \
         patch("api.routes.chat.pl.VIDU_STUDIO_ROOT", tmp_path), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_name": "测试项目",
            "message": "有多少场景？",
            "history": [],
        })
    assert resp.status_code == 200
    assert resp.json()["reply"] == "当前有2个场景"
    assert resp.json()["tool_results"] == []
    assert resp.json()["has_writes"] == False


def test_chat_accepts_project_path(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(
        json.dumps({"project": "测试项目", "assets": {}, "storyboards": {}}, ensure_ascii=False),
        encoding="utf-8"
    )

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "当前有2个场景", "actions": [], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "有多少场景？",
            "history": [],
        })

    assert resp.status_code == 200
    assert resp.json()["reply"] == "当前有2个场景"


def test_chat_requires_idealab_key(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text(
        json.dumps({"project": "测试项目", "assets": {}, "storyboards": {}}, ensure_ascii=False),
        encoding="utf-8"
    )

    with patch("api.routes.chat.get_api_key", return_value=""):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "有多少场景？",
            "history": [],
        })

    assert resp.status_code == 400
    assert "ideaLAB API Key" in resp.json()["detail"]


def test_chat_rejects_missing_project(tmp_path):
    missing_project = tmp_path / "不存在"

    with patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(missing_project),
            "message": "有多少场景？",
            "history": [],
        })

    assert resp.status_code == 404
    assert "项目不存在" in resp.json()["detail"]


def test_chat_update_param_does_not_create_missing_storyboard(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {"E01-S1": {"video_parts": []}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "update_param", "target": "video", "name": "不存在", "field": "duration", "value": 12}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "改视频时长",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "不存在" not in updated["storyboards"]


def test_chat_update_param_updates_existing_storyboard(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {"E01-S1": {"video_parts": []}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "update_param", "target": "video", "name": "E01-S1", "field": "duration", "value": 12}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "改视频时长",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is True
    assert data["tool_results"][0]["ok"] is True
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["storyboards"]["E01-S1"]["video_duration"] == 12


def test_chat_update_param_rejects_invalid_video_duration(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {"E01-S1": {"video_parts": []}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "update_param", "target": "video", "name": "E01-S1", "field": "duration", "value": "abc"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "改视频时长",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    assert "视频时长" in data["tool_results"][0]["label"]
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "video_duration" not in updated["storyboards"]["E01-S1"]


def test_chat_update_param_rejects_fractional_video_duration(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {"E01-S1": {"video_parts": []}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "update_param", "target": "video", "name": "E01-S1", "field": "duration", "value": 6.5}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "改视频时长",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    assert "视频时长" in data["tool_results"][0]["label"]
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "video_duration" not in updated["storyboards"]["E01-S1"]


def test_chat_update_param_rejects_invalid_video_ratio(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {"E01-S1": {"video_parts": []}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "update_param", "target": "video", "name": "E01-S1", "field": "ratio", "value": "wide"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "改视频比例",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    assert "视频比例" in data["tool_results"][0]["label"]
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "video_ratio" not in updated["storyboards"]["E01-S1"]


def test_chat_submit_video_uses_updated_ratio(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "storyboards" / "E01-S1").mkdir(parents=True)
    (project_dir / "storyboards" / "E01-S1" / "E01-S1.png").write_bytes(b"fake-board")
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {
            "E01-S1": {
                "board_status": "completed",
                "video_parts": [{"part": 1, "video_status": "needed", "draft_prompt": "视频提示词"}],
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "update_param", "target": "video", "name": "E01-S1", "field": "ratio", "value": "9:16"},
                   {"action": "submit_task", "target": "video_part", "name": "E01-S1", "part": 1},
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.wetoken.submit_video_task", return_value="video_task") as submit_video:
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "竖屏提交第一段",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is True
    submit_video.assert_called_once()
    assert submit_video.call_args.kwargs["ratio"] == "9:16"
    assert submit_video.call_args.kwargs["project_dir"] == project_dir
    assert submit_video.call_args.args[2] == [str(project_dir / "storyboards" / "E01-S1" / "E01-S1.png")]

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    board = updated["storyboards"]["E01-S1"]
    assert board["video_ratio"] == "9:16"
    assert board["video_parts"][0]["video_status"] == "submitted"
    assert board["video_parts"][0]["video_task_id"] == "video_task"


def test_chat_submit_storyboard_requires_completed_references(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "needed"}},
            "scenes": {"卧室": {"status": "completed"}},
            "props": {},
        },
        "storyboards": {
            "E01-S1": {
                "draft_prompt": "故事板提示词",
                "characters_in_scene": ["婉瑜"],
                "scene_location": "卧室",
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "submit_task", "target": "storyboard", "name": "E01-S1"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.vidu.submit_image_task") as submit_image:
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "提交故事板",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    assert "前置参考未完成" in data["tool_results"][0]["label"]
    assert "角色「婉瑜」未完成" in data["tool_results"][0]["label"]
    submit_image.assert_not_called()


def test_chat_submit_storyboard_sends_reference_images(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    (project_dir / "scenes_props" / "卧室").mkdir(parents=True)
    char_image = project_dir / "characters" / "婉瑜" / "婉瑜.png"
    scene_image = project_dir / "scenes_props" / "卧室" / "卧室.png"
    char_image.write_bytes(b"fake-char")
    scene_image.write_bytes(b"fake-scene")
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "completed"}},
            "scenes": {"卧室": {"status": "completed"}},
            "props": {},
        },
        "storyboards": {
            "E01-S1": {
                "draft_prompt": "故事板提示词",
                "characters_in_scene": ["婉瑜"],
                "scene_location": "卧室",
            },
        },
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "submit_task", "target": "storyboard", "name": "E01-S1"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.vidu.submit_image_task", return_value={"task_id": "board_task"}) as submit_image:
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "提交故事板",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is True
    submit_image.assert_called_once()
    assert submit_image.call_args.args[2] == [str(char_image), str(scene_image)]

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["storyboards"]["E01-S1"]["board_status"] == "submitted"
    assert updated["storyboards"]["E01-S1"]["board_task_id"] == "board_task"


def test_chat_submit_character_requires_vidu_key_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "needed", "draft_prompt": "角色提示词"}},
            "scenes": {},
            "props": {},
        },
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    def key_for(name):
        return "idealab-key" if name == "IDEALAB_API_KEY" else ""

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "submit_task", "target": "character", "name": "婉瑜"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", side_effect=key_for), \
         patch("api.vidu.submit_image_task") as submit_image:
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "提交婉瑜",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    assert "Vidu API Key" in data["tool_results"][0]["label"]
    submit_image.assert_not_called()

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "needed"


def test_chat_submit_character_rejects_blank_prompt_without_remote_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "needed", "draft_prompt": "   "}},
            "scenes": {},
            "props": {},
        },
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "submit_task", "target": "character", "name": "婉瑜"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.vidu.submit_image_task") as submit_image:
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "提交婉瑜",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    assert "没有提示词" in data["tool_results"][0]["label"]
    submit_image.assert_not_called()

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["status"] == "needed"


def test_chat_submit_character_clears_previous_error(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {
                "婉瑜": {
                    "status": "failed",
                    "draft_prompt": "角色提示词",
                    "task_id": "old_task",
                    "error": "上一次失败",
                },
            },
            "scenes": {},
            "props": {},
        },
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "submit_task", "target": "character", "name": "婉瑜"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.vidu.submit_image_task", return_value={"task_id": "new_task"}):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "重新提交婉瑜",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is True
    assert data["tool_results"][0]["ok"] is True

    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    asset = updated["assets"]["characters"]["婉瑜"]
    assert asset["status"] == "submitted"
    assert asset["task_id"] == "new_task"
    assert "error" not in asset


def test_chat_summary_tolerates_video_part_without_part_number(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {},
        "storyboards": {"E01-S1": {"video_parts": [{"video_status": "needed"}]}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "当前有1个场景", "actions": [], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "有多少场景？",
            "history": [],
        })

    assert resp.status_code == 200
    assert resp.json()["reply"] == "当前有1个场景"


def test_chat_generate_prompt_action_updates_draft(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "30多岁"}}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "generate_prompt", "target": "character", "name": "婉瑜"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt", return_value="生成的角色提示词"):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "重新生成婉瑜",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is True
    assert data["tool_results"][0]["ok"] is True
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert updated["assets"]["characters"]["婉瑜"]["draft_prompt"] == "生成的角色提示词"


def test_chat_generate_prompt_action_reports_missing_asset_without_write(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {"characters": {}}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "generate_prompt", "target": "character", "name": "不存在"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "重新生成不存在",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    generate.assert_not_called()


def test_chat_generate_prompt_action_reports_llm_error_without_write(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "30多岁"}}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.chat.llm.chat_with_agent",
               return_value={"reply": "已处理", "actions": [
                   {"action": "generate_prompt", "target": "character", "name": "婉瑜"}
               ], "_raw": "{}"}), \
         patch("api.routes.chat.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt", side_effect=Exception("网络失败")):
        resp = client.post("/api/chat", json={
            "project_path": str(project_dir),
            "message": "重新生成婉瑜",
            "history": [],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["has_writes"] is False
    assert data["tool_results"][0]["ok"] is False
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    assert "draft_prompt" not in updated["assets"]["characters"]["婉瑜"]


def test_batch_generate_prompts(tmp_path):
    """POST /api/prompts/batch-generate 批量生成提示词"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "needed", "seed": "素净"}},
            "scenes": {"卧室": {"status": "needed", "seed": "暖色调"}},
            "props": {},
        },
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.llm.generate_prompt", return_value="批量生成的提示词"), \
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


def test_batch_generate_prompts_requires_idealab_key(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {"characters": {}}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value=""), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/batch-generate", json={
            "project_path": str(project_dir),
            "items": [{"type": "character", "name": "婉瑜", "appearance_seed": "素净"}],
        })

    assert resp.status_code == 400
    assert "ideaLAB API Key" in resp.json()["detail"]
    generate.assert_not_called()


def test_batch_generate_prompts_rejects_missing_project(tmp_path):
    missing_project = tmp_path / "不存在"

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/batch-generate", json={
            "project_path": str(missing_project),
            "items": [{"type": "character", "name": "婉瑜", "appearance_seed": "素净"}],
        })

    assert resp.status_code == 404
    assert "项目不存在" in resp.json()["detail"]
    generate.assert_not_called()


def test_batch_generate_prompts_reports_item_http_error_detail(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {"characters": {}}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/batch-generate", json={
            "project_path": str(project_dir),
            "items": [{"type": "character", "name": "不存在", "appearance_seed": "素净"}],
        })

    assert resp.status_code == 200
    assert resp.json()["results"] == [{"name": "不存在", "ok": False, "error": "未找到角色: 不存在"}]
    generate.assert_not_called()


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


def test_batch_submit_tasks_rejects_missing_project(tmp_path):
    missing_project = tmp_path / "不存在"

    with patch("api.routes.tasks.vidu.submit_image_task") as submit_image:
        resp = client.post("/api/tasks/batch-submit", json={
            "project_path": str(missing_project),
            "items": [
                {"type": "character", "name": "婉瑜", "prompt": "提示词", "image_paths": []},
            ],
        })

    assert resp.status_code == 404
    assert "项目不存在" in resp.json()["detail"]
    submit_image.assert_not_called()


def test_batch_submit_tasks_reports_item_http_error_detail(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value=""):
        resp = client.post("/api/tasks/batch-submit", json={
            "project_path": str(project_dir),
            "items": [
                {"type": "character", "name": "婉瑜", "prompt": "提示词", "image_paths": []},
            ],
        })

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["ok"] is False
    assert "Vidu API Key" in results[0]["error"]


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


def test_get_prompt_templates_rejects_non_project_path(tmp_path):
    non_project_dir = tmp_path / "普通目录"
    non_project_dir.mkdir()

    resp = client.get("/api/project/prompt-templates", params={"project_path": str(non_project_dir)})

    assert resp.status_code == 404
    assert "项目不存在" in resp.json()["detail"]


def test_get_prompt_templates_invalid_json_returns_clear_400(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    (project_dir / "prompt_templates.json").write_text("{bad json", encoding="utf-8")

    resp = client.get("/api/project/prompt-templates", params={"project_path": str(project_dir)})

    assert resp.status_code == 400
    assert "prompt_templates.json 不是有效 JSON" in resp.json()["detail"]


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


def test_prompt_templates_accept_project_path(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    resp = client.put("/api/project/prompt-templates",
                      params={"project_path": str(project_dir)},
                      json={"character": "路径模板"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = client.get("/api/project/prompt-templates", params={"project_path": str(project_dir)})
    assert resp.status_code == 200
    assert resp.json()["character"] == "路径模板"


def test_put_prompt_templates_rejects_non_project_path(tmp_path):
    non_project_dir = tmp_path / "普通目录"
    non_project_dir.mkdir()

    resp = client.put("/api/project/prompt-templates",
                      params={"project_path": str(non_project_dir)},
                      json={"character": "不应写入"})

    assert resp.status_code == 404
    assert not (non_project_dir / "prompt_templates.json").exists()


def test_put_prompt_templates_write_error_returns_clear_500(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.write_prompt_templates",
               side_effect=ProjectFileWriteError(project_dir / "prompt_templates.json", "无法写入 prompt_templates.json: 磁盘已满")):
        resp = client.put("/api/project/prompt-templates",
                          params={"project_path": str(project_dir)},
                          json={"character": "不应写入"})

    assert resp.status_code == 500
    assert "无法写入 prompt_templates.json" in resp.json()["detail"]


def _write_minimal_pipeline(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    pipeline_data = {"project": project_dir.name, "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")


def test_asset_file_rejects_path_escape(tmp_path):
    """GET /api/asset-file must not serve files outside the project directory."""
    project_dir = tmp_path / "项目"
    _write_minimal_pipeline(project_dir)
    secret = tmp_path / "secret.txt"
    secret.write_text("do not expose", encoding="utf-8")

    resp = client.get("/api/asset-file", params={
        "project_path": str(project_dir),
        "file_path": "../secret.txt",
    })

    assert resp.status_code == 403


def test_asset_file_rejects_non_project_root(tmp_path):
    """GET /api/asset-file must require a Manhua project directory."""
    non_project_dir = tmp_path / "普通目录"
    non_project_dir.mkdir()
    (non_project_dir / "secret.txt").write_text("do not expose", encoding="utf-8")

    resp = client.get("/api/asset-file", params={
        "project_path": str(non_project_dir),
        "file_path": "secret.txt",
    })

    assert resp.status_code == 404
    assert "项目不存在" in resp.json()["detail"]


def test_asset_file_preview_returns_placeholder_for_missing_file(tmp_path):
    project_dir = tmp_path / "项目"
    _write_minimal_pipeline(project_dir)

    resp = client.get("/api/asset-file", params={
        "project_path": str(project_dir),
        "file_path": "characters/婉瑜/婉瑜.png",
        "preview": "true",
    })

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "本地文件缺失" in resp.text


def test_asset_file_missing_without_preview_returns_404(tmp_path):
    project_dir = tmp_path / "项目"
    _write_minimal_pipeline(project_dir)

    resp = client.get("/api/asset-file", params={
        "project_path": str(project_dir),
        "file_path": "characters/婉瑜/婉瑜.png",
    })

    assert resp.status_code == 404


def test_submit_character_requires_vidu_key(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {}
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value=""), \
         patch("api.routes.tasks.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.post("/api/tasks/submit", json={
            "type": "character",
            "project_name": "测试项目",
            "name": "婉瑜",
            "prompt": "完整角色提示词",
            "image_paths": [],
        })

    assert resp.status_code == 400
    assert "Vidu API Key" in resp.json()["detail"]


def test_generate_prompt_requires_idealab_key():
    with patch("api.routes.prompts.get_api_key", return_value=""):
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "name": "婉瑜",
            "appearance_seed": "30多岁",
            "project_name": "测试项目",
        })

    assert resp.status_code == 400
    assert "ideaLAB API Key" in resp.json()["detail"]


def test_generate_prompt_rejects_missing_project(tmp_path):
    missing_project = tmp_path / "不存在"

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "project_path": str(missing_project),
            "name": "婉瑜",
            "appearance_seed": "30多岁",
        })

    assert resp.status_code == 404
    assert "项目不存在" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_prompt_invalid_pipeline_returns_400_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    (project_dir / "pipeline.json").write_text("{bad json", encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "appearance_seed": "30多岁",
        })

    assert resp.status_code == 400
    assert "pipeline.json 不是有效 JSON" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_prompt_rejects_missing_asset_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "不存在",
            "appearance_seed": "30多岁",
        })

    assert resp.status_code == 400
    assert "未找到角色" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_prompt_rejects_missing_storyboard_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "characters": [],
            "scene_location": "",
            "script_segment": "台词",
        })

    assert resp.status_code == 400
    assert "未找到故事板" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_storyboard_prompt_requires_completed_character_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "needed"}},
            "scenes": {},
            "props": {},
        },
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "characters": ["婉瑜"],
            "scene_location": "",
            "script_segment": "台词",
        })

    assert resp.status_code == 400
    assert "角色「婉瑜」未完成" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_storyboard_prompt_requires_completed_scene_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {
            "characters": {"婉瑜": {"status": "completed"}},
            "scenes": {"卧室": {"status": "needed"}},
            "props": {},
        },
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    char_meta = {"name": "婉瑜", "primary_image": "婉瑜.png",
                 "versions": [{"filename": "婉瑜.png", "prompt": {"optimized": "角色外貌段"}}]}
    (project_dir / "characters" / "婉瑜" / "meta.json").write_text(
        json.dumps(char_meta, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "characters": ["婉瑜"],
            "scene_location": "卧室",
            "script_segment": "台词",
        })

    assert resp.status_code == 400
    assert "场景/道具「卧室」未完成" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_video_prompt_requires_completed_storyboard_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "script_segment": "台词",
        })

    assert resp.status_code == 400
    assert "故事板尚未完成" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_video_prompt_requires_panels_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "completed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "script_segment": "台词",
        })

    assert resp.status_code == 400
    assert "缺少故事板 panels" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_video_prompt_saves_parts_from_completed_storyboard(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "storyboards" / "E01-S1").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "completed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    meta = {
        "name": "E01-S1",
        "primary_image": "E01-S1.png",
        "versions": [{
            "filename": "E01-S1.png",
            "prompt": {"optimized": "暖色电影感"},
            "panels": [{"index": 1, "shot": "近景", "action": "婉瑜转身"}],
        }],
    }
    (project_dir / "storyboards" / "E01-S1" / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt",
               return_value="---PART1---\nc1,4s,第一段\n---PART2---\nc2,5s,第二段"):
        resp = client.post("/api/prompts/generate", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "script_segment": "台词",
        })

    assert resp.status_code == 200
    updated = json.loads((project_dir / "pipeline.json").read_text(encoding="utf-8"))
    parts = updated["storyboards"]["E01-S1"]["video_parts"]
    assert [p["part"] for p in parts] == [1, 2]
    assert [p["duration"] for p in parts] == [4, 5]


def test_generate_storyboard_prompt_invalid_character_meta_returns_400_without_llm_call(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "completed"}}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "needed"}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")
    (project_dir / "characters" / "婉瑜" / "meta.json").write_text("{bad json", encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt") as generate:
        resp = client.post("/api/prompts/generate", json={
            "type": "storyboard",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "characters": ["婉瑜"],
            "scene_location": "",
            "script_segment": "台词",
        })

    assert resp.status_code == 400
    assert "meta.json 不是有效 JSON" in resp.json()["detail"]
    generate.assert_not_called()


def test_generate_prompt_returns_classified_idealab_error(tmp_path):
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {"婉瑜": {"status": "needed", "seed": "描述"}}, "scenes": {}, "props": {}},
        "storyboards": {},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.prompts.get_api_key", return_value="test_key"), \
         patch("api.routes.prompts.llm.generate_prompt", side_effect=Exception("ideaLAB 网络请求失败，请检查网络连接或代理设置。")):
        resp = client.post("/api/prompts/generate", json={
            "type": "character",
            "project_path": str(project_dir),
            "name": "婉瑜",
            "appearance_seed": "30多岁",
        })

    assert resp.status_code == 502
    assert "ideaLAB API 错误" in resp.json()["detail"]
    assert "网络请求失败" in resp.json()["detail"]


def test_submit_video_returns_classified_wetoken_error(tmp_path):
    project_dir = tmp_path / "测试项目"
    (project_dir / "storyboards" / "E01-S1").mkdir(parents=True)
    board_image = project_dir / "storyboards" / "E01-S1" / "E01-S1.png"
    board_image.write_bytes(b"fake-image")
    pipeline_data = {
        "project": "测试项目",
        "assets": {"characters": {}, "scenes": {}, "props": {}},
        "storyboards": {"E01-S1": {"board_status": "completed", "video_parts": [{"part": 1, "video_status": "needed"}]}},
    }
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.tasks.get_api_key", return_value="test_key"), \
         patch("api.routes.tasks.wetoken.submit_video_task", side_effect=Exception("Wetoken 额度不足或达到使用限制，请检查账户额度。")):
        resp = client.post("/api/tasks/submit", json={
            "type": "video",
            "project_path": str(project_dir),
            "scene_key": "E01-S1",
            "part": 1,
            "prompt": "视频提示词",
            "image_paths": ["storyboards/E01-S1/E01-S1.png"],
        })

    assert resp.status_code == 502
    assert "Wetoken API 错误" in resp.json()["detail"]
    assert "额度不足" in resp.json()["detail"]
