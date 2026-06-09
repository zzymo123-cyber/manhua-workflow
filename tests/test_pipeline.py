import json, os, tempfile, pytest
from pathlib import Path

# 将 manhua-workflow 加入路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.pipeline import (
    PipelineReadError, ProjectFileReadError, ProjectFileWriteError,
    get_project_root, read_pipeline, write_pipeline,
    get_meta, write_meta, get_asset_image_path,
    read_prompt_templates, write_prompt_templates, get_prompt_template_defaults
)


@pytest.fixture
def tmp_project(tmp_path):
    """创建临时项目目录结构"""
    project_dir = tmp_path / "vidu_studio" / "测试项目"
    (project_dir / "characters" / "婉瑜").mkdir(parents=True)
    (project_dir / "scenes_props" / "小乐卧室").mkdir(parents=True)
    (project_dir / "storyboards" / "E01-S1-卧室").mkdir(parents=True)
    return project_dir


def test_write_and_read_pipeline(tmp_project):
    data = {"project": "测试项目", "assets": {"characters": {}}}
    write_pipeline(tmp_project, data)
    result = read_pipeline(tmp_project)
    assert result["project"] == "测试项目"


def test_atomic_write_no_partial_read(tmp_project):
    """写入不应产生损坏的中间状态"""
    data = {"project": "测试项目", "x": "a" * 10000}
    write_pipeline(tmp_project, data)
    result = read_pipeline(tmp_project)
    assert result["x"] == "a" * 10000


def test_write_pipeline_failure_removes_tmp_and_preserves_existing(tmp_project):
    write_pipeline(tmp_project, {"project": "测试项目"})

    with pytest.raises(ProjectFileWriteError) as exc:
        write_pipeline(tmp_project, {"bad": object()})

    assert "无法写入 pipeline.json" in str(exc.value)
    assert not (tmp_project / "pipeline.tmp").exists()
    assert read_pipeline(tmp_project)["project"] == "测试项目"


def test_read_pipeline_invalid_json_raises_clear_error(tmp_project):
    (tmp_project / "pipeline.json").write_text("{bad json", encoding="utf-8")

    with pytest.raises(PipelineReadError) as exc:
        read_pipeline(tmp_project)

    assert "pipeline.json 不是有效 JSON" in str(exc.value)
    assert str(tmp_project / "pipeline.json") in str(exc.value)


def test_get_meta_not_exist_returns_none(tmp_project):
    result = get_meta(tmp_project, "characters", "不存在的角色")
    assert result is None


def test_write_and_read_meta(tmp_project):
    data = {"name": "婉瑜", "primary_image": "婉瑜.png", "versions": []}
    write_meta(tmp_project, "characters", "婉瑜", data)
    result = get_meta(tmp_project, "characters", "婉瑜")
    assert result["name"] == "婉瑜"


def test_write_meta_failure_removes_tmp(tmp_project):
    with pytest.raises(ProjectFileWriteError):
        write_meta(tmp_project, "characters", "婉瑜", {"bad": object()})

    assert not (tmp_project / "characters" / "婉瑜" / "meta.tmp").exists()


def test_get_meta_invalid_json_raises_clear_error(tmp_project):
    meta_path = tmp_project / "characters" / "婉瑜" / "meta.json"
    meta_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ProjectFileReadError) as exc:
        get_meta(tmp_project, "characters", "婉瑜")

    assert "meta.json 不是有效 JSON" in str(exc.value)
    assert str(meta_path) in str(exc.value)


def test_get_asset_image_path(tmp_project):
    path = get_asset_image_path(tmp_project, "characters", "婉瑜", "婉瑜.png")
    assert str(path).endswith("婉瑜.png")
    assert "characters" in str(path)


def test_read_prompt_templates_not_exist_returns_defaults(tmp_project):
    """When prompt_templates.json doesn't exist, return built-in defaults"""
    result = read_prompt_templates(tmp_project)
    assert "character" in result
    assert "scene" in result
    assert result["character"]  # non-empty string


def test_write_and_read_prompt_templates(tmp_project):
    data = {"character": "custom char prompt", "scene": "custom scene prompt"}
    write_prompt_templates(tmp_project, data)
    result = read_prompt_templates(tmp_project)
    assert result["character"] == "custom char prompt"
    assert result["scene"] == "custom scene prompt"


def test_write_prompt_templates_failure_removes_tmp_and_preserves_existing(tmp_project):
    write_prompt_templates(tmp_project, {"character": "custom char prompt"})

    with pytest.raises(ProjectFileWriteError):
        write_prompt_templates(tmp_project, {"bad": object()})

    assert not (tmp_project / "prompt_templates.tmp").exists()
    assert read_prompt_templates(tmp_project)["character"] == "custom char prompt"


def test_read_prompt_templates_invalid_json_raises_clear_error(tmp_project):
    template_path = tmp_project / "prompt_templates.json"
    template_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ProjectFileReadError) as exc:
        read_prompt_templates(tmp_project)

    assert "prompt_templates.json 不是有效 JSON" in str(exc.value)
    assert str(template_path) in str(exc.value)


def test_get_prompt_template_defaults_returns_all_keys():
    defaults = get_prompt_template_defaults()
    assert set(defaults.keys()) == {
        "character",
        "scene",
        "prop",
        "storyboard",
        "storyboard_v2",
        "video",
        "video_v2",
    }
    assert all(defaults.values())  # all non-empty


def test_read_prompt_templates_merges_new_defaults_for_existing_template_file(tmp_project):
    write_prompt_templates(tmp_project, {"storyboard": "custom storyboard prompt"})

    templates = read_prompt_templates(tmp_project)

    assert templates["storyboard"] == "custom storyboard prompt"
    assert "storyboard_v2" in templates
    assert "video_v2" in templates
