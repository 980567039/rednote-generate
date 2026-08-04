import json
import os
import stat

import pytest

from backend.services import series


def template_payload(name="原创成长系列"):
    return {
        "name": name,
        "description": "长期更新的原创合集",
        "visual_style": "原创扁平插画",
        "palette": "奶油白、雾蓝、浅棕",
        "composition": "留白充足，主体居中",
        "character_bible": "原创短发青年，服装和五官保持一致",
        "copy_tone": "真诚、简洁、有行动建议",
        "prohibited_elements": ["密集文字"],
        "page_structure": {"preset": "standard", "page_count": 5},
        "reference_images": [],
    }


@pytest.fixture
def isolated_series(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "series_templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "series_projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")
    return tmp_path


def test_template_revision_atomic_permissions_and_item_snapshot(isolated_series):
    payload = template_payload()
    payload["prohibited_elements"] = "密集文字、写实摄影；3D 渲染"
    template = series.create_template(payload)
    project = series.create_project(template["id"], ["第一篇"])
    first = project["items"][0]

    updated = series.update_template(template["id"], {"visual_style": "原创水彩插画"})
    appended = series.append_project_items(project["id"], ["第二篇"])
    second = appended["items"][0]

    assert template["revision"] == 1
    assert updated["revision"] == 2
    assert first["template_revision"] == 1
    assert first["template_snapshot"]["visual_style"] == "原创扁平插画"
    assert first["template_snapshot"]["prohibited_elements"] == ["密集文字", "写实摄影", "3D 渲染"]
    assert second["template_revision"] == 2
    assert second["template_snapshot"]["visual_style"] == "原创水彩插画"
    assert stat.S_IMODE(os.stat(series.TEMPLATES_FILE).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(series.PROJECTS_FILE).st_mode) == 0o600


def test_empty_project_has_name_and_supports_unlimited_total_in_small_batches(isolated_series):
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], [], name="我的长期合集")

    assert project["name"] == "我的长期合集"
    assert project["items"] == []
    assert project["item_count"] == 0

    first = [f"主题 {index}" for index in range(10)]
    second = ["  主题   0  ", *[f"主题 {index}" for index in range(10, 19)]]
    series.append_project_items(project["id"], first)
    result = series.append_project_items(project["id"], second)

    saved = series.get_project(project["id"])
    assert len(saved["items"]) == 19
    assert result["duplicates"] == ["主题 0"]
    with pytest.raises(ValueError, match="单次最多"):
        series.append_project_items(project["id"], [str(index) for index in range(11)])
    with pytest.raises(ValueError, match="至少提供"):
        series.append_project_items(project["id"], [])


def test_items_pagination_filter_and_explicit_empty_selection(isolated_series):
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], [f"教程 {index}" for index in range(10)])
    series.append_project_items(project["id"], [f"旅行 {index}" for index in range(5)])

    page = series.list_project_items(project["id"], page=2, page_size=5, query="教程", status="draft")
    assert len(page["items"]) == 5
    assert page["pagination"] == {"page": 2, "page_size": 5, "total": 10, "total_pages": 2}
    assert page["project"]["item_count"] == 15
    assert page["project"]["status_counts"] == {"draft": 15}
    assert series.select_items(series.get_project(project["id"]), []) == []


def test_topic_suggestions_are_five_and_ip_is_opt_in(isolated_series):
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], [])

    original = series.topic_suggestions(project["id"], False)
    opt_in = series.topic_suggestions(project["id"], True)

    assert len(original) == len(opt_in) == 5
    assert all(set(["topic", "reason", "uses_ip", "title", "brief", "ip_related"]) <= set(item) for item in original)
    assert not any(item["uses_ip"] for item in original)
    assert sum(bool(item["uses_ip"]) for item in opt_in) == 1

    series.append_project_items(project["id"], [item["topic"] for item in original])
    next_batch = series.topic_suggestions(project["id"], False)
    assert len(next_batch) == 5
    assert {item["topic"] for item in next_batch}.isdisjoint({item["topic"] for item in original})


def test_prohibited_element_validation_ignores_negative_rule_explanations(isolated_series):
    template = template_payload()
    template["prohibited_elements"] = ["水印", "无关品牌 Logo"]
    created = series.create_template(template)
    pages = [
        {"index": 0, "type": "cover", "content": "封面画面；请勿在画面中生成水印和无关品牌 Logo。"},
        *[
            {"index": index, "type": "content", "content": "角色在海边冒险。"}
            for index in range(1, 4)
        ],
        {"index": 4, "type": "summary", "content": "总结今天的冒险。"},
    ]

    assert series.validate_pages(pages, created) == []
    pages[1]["content"] = "画面角落出现水印。"
    assert series.validate_pages(pages, created) == ["大纲包含系列禁止元素：水印"]


def test_reference_paths_reject_traversal(isolated_series):
    template = series.create_template(template_payload())
    with pytest.raises(ValueError):
        series.reference_path(template["id"], "../secret.png", require_exists=False)


def test_restart_recovers_active_items_to_retryable_failures(isolated_series):
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], ["大纲中断", "生图中断"])
    project["items"][0].update({"status": "outlining", "outline_status": "generating"})
    project["items"][1].update({
        "status": "generating",
        "outline_status": "confirmed",
        "content_status": "completed",
        "image_status": "generating",
    })
    project["status"] = "generating"
    series.save_project(project)

    assert series.recover_interrupted_projects() == 2
    recovered = series.get_project(project["id"])
    assert [item["status"] for item in recovered["items"]] == ["failed", "failed"]
    assert recovered["items"][0]["outline_status"] == "failed"
    assert recovered["items"][1]["outline_status"] == "confirmed"
    assert recovered["items"][1]["image_status"] == "failed"
    assert all("请重试" in item["error"] for item in recovered["items"])
    assert series.recover_interrupted_projects() == 0


def test_character_sheet_mode_can_switch_before_generation(isolated_series):
    template = series.create_template(template_payload("像素角色模板"))
    project = series.create_project(template["id"], [], name="每日角色", content_mode="character_sheet")
    added = series.append_project_items(
        project["id"], ["海贼王角色阵容"], ip_acknowledged=True, content_mode="character_sheet"
    )
    item = added["items"][0]
    assert item["content_mode"] == "character_sheet"
    assert item["template_snapshot"]["page_structure"] == {"preset": "character_sheet", "page_count": 1}
    assert item["progress"]["total"] == 1
    assert series.validate_pages(
        [{"index": 0, "type": "cover", "content": "精细角色设定图"}], item["template_snapshot"]
    ) == []

    saved = series.get_project(project["id"])
    switched = series.update_item(saved, item["id"], {"content_mode": "story"})
    switched_item = series.get_project_item(switched, item["id"])
    assert switched_item["content_mode"] == "story"
    assert switched_item["template_snapshot"]["page_structure"]["page_count"] == 5
    assert switched_item["status"] == "draft"


def test_character_sheet_mode_creates_one_page_per_named_character(isolated_series):
    template = series.create_template(template_payload("像素角色模板"))
    project = series.create_project(
        template["id"], ["海贼王：路飞、索隆、娜美"], content_mode="character_sheet"
    )
    item = project["items"][0]
    assert item["character_names"] == ["路飞", "索隆", "娜美"]
    assert item["template_snapshot"]["page_structure"]["page_count"] == 3
    assert item["progress"]["total"] == 3
    assert series.validate_pages(
        [
            {"index": index, "type": "cover" if index == 0 else "content", "content": f"角色 {index}"}
            for index in range(3)
        ],
        item["template_snapshot"],
    ) == []


def test_delete_project_item_removes_from_collection_preserves_history_and_reindexes(isolated_series):
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], ["第一篇", "第二篇", "第三篇"])
    saved = series.get_project(project["id"])
    saved["items"][1]["status"] = "completed"
    saved["items"][1]["record_id"] = "record_keep_me"
    series.save_project(saved)

    removed = series.delete_project_item(project["id"], project["items"][1]["id"])
    current = series.get_project(project["id"])

    assert removed["record_id"] == "record_keep_me"
    assert [item["topic"] for item in current["items"]] == ["第一篇", "第三篇"]
    assert [item["index"] for item in current["items"]] == [0, 1]
    assert current["topics"] == ["第一篇", "第三篇"]
    assert current["status"] == "draft"


def test_delete_project_item_rejects_active_generation(isolated_series):
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], ["生成中的主题"])
    saved = series.get_project(project["id"])
    saved["items"][0]["status"] = "generating"
    series.save_project(saved)

    with pytest.raises(ValueError, match="正在生成"):
        series.delete_project_item(project["id"], project["items"][0]["id"])
