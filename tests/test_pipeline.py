import json, os, tempfile, pytest
from pathlib import Path

# 将 manhua-workflow 加入路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.pipeline import (
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


def test_get_meta_not_exist_returns_none(tmp_project):
    result = get_meta(tmp_project, "characters", "不存在的角色")
    assert result is None


def test_write_and_read_meta(tmp_project):
    data = {"name": "婉瑜", "primary_image": "婉瑜.png", "versions": []}
    write_meta(tmp_project, "characters", "婉瑜", data)
    result = get_meta(tmp_project, "characters", "婉瑜")
    assert result["name"] == "婉瑜"


def test_get_asset_image_path(tmp_project):
    path = get_asset_image_path(tmp_project, "characters", "婉瑜", "婉瑜.png")
    assert str(path).endswith("婉瑜.png")
    assert "characters" in str(path)


def test_read_prompt_templates_not_exist_returns_defaults(tmp_project):
    """When prompt_templates.json doesn't exist, return built-in defaults"""
    result = read_prompt_templates(tmp_project)
    assert "character" in result
    assert "scene" in result
    # 内置默认值是 string（不是 dict 变体格式）
    assert isinstance(result["character"], str)
    assert result["character"]  # non-empty


def test_write_and_read_prompt_templates(tmp_project):
    data = {"character": "custom char prompt", "scene": "custom scene prompt"}
    write_prompt_templates(tmp_project, data)
    result = read_prompt_templates(tmp_project)
    # 写入什么读出什么
    assert result["character"] == "custom char prompt"
    assert result["scene"] == "custom scene prompt"


def test_get_prompt_template_defaults_returns_all_keys():
    defaults = get_prompt_template_defaults()
    assert set(defaults.keys()) == {
        "character", "scene", "prop",
        "storyboard_v1", "storyboard_v2",
        "video_v1", "video_v2",
    }
    # 内置默认值是 string
    assert all(isinstance(v, str) and v for v in defaults.values())
    assert "3x3" in defaults["storyboard_v1"]
    assert "5-6" in defaults["storyboard_v2"]
    assert "16:9" in defaults["video_v1"]
    assert "横屏" in defaults["video_v1"]
    assert "9:16" in defaults["video_v2"]
    assert "竖屏" in defaults["video_v2"]
    assert "不要假设一定是9格" in defaults["video_v2"]
