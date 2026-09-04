from flask import Flask

import backend.routes.content_routes as content_routes
import backend.routes.series_routes as series_routes
from backend.routes.content_routes import create_content_blueprint
from backend.routes.series_routes import create_series_blueprint
from backend.services import series

from tests.series_service_test import template_payload


def make_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_series_blueprint(), url_prefix="/api")
    return app.test_client()


def test_long_term_project_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")

    class FakeSuggestionService:
        def generate_series_topic_suggestions(self, series_context, existing_topics, allow_third_party_ip):
            assert "系列硬约束" in series_context
            assert existing_topics == ["第一篇", "第二篇"]
            return [{
                "topic": f"候选主题 {index + 1}",
                "reason": "覆盖不同剧情方向",
                "uses_ip": allow_third_party_ip and index == 0,
            } for index in range(5)]

    monkeypatch.setattr(series_routes, "get_content_service", lambda: FakeSuggestionService())
    client = make_client()

    template_response = client.post("/api/series/templates", json=template_payload())
    assert template_response.status_code == 201
    template = template_response.get_json()["template"]

    project_response = client.post(
        "/api/series/projects",
        json={"template_id": template["id"], "topics": [], "name": "长期原创合集"},
    )
    assert project_response.status_code == 201
    project = project_response.get_json()["project"]
    assert project["name"] == "长期原创合集"

    append = client.post(
        f"/api/series/projects/{project['id']}/items",
        json={"topics": ["第一篇", "第二篇"], "topic_source": "system"},
    )
    assert append.status_code == 201
    assert len(append.get_json()["items"]) == 2
    assert append.get_json()["items"][0]["topic_source"] == "system"

    items = client.get(f"/api/series/projects/{project['id']}/items?page=1&page_size=1")
    assert items.status_code == 200
    assert len(items.get_json()["items"]) == 1
    assert items.get_json()["pagination"]["total"] == 2

    suggestions = client.post(
        f"/api/series/projects/{project['id']}/topic-suggestions",
        json={"allow_third_party_ip": True},
    )
    assert suggestions.status_code == 200
    assert len(suggestions.get_json()["suggestions"]) == 5
    assert any(item["uses_ip"] for item in suggestions.get_json()["suggestions"])
    assert suggestions.get_json()["source"] == "model"


def test_content_route_restores_frozen_context_from_history(monkeypatch):
    captured = {}
    snapshot = {**template_payload("旧模板"), "id": "template_old", "revision": 1}

    class FakeHistory:
        def get_record(self, record_id):
            return {
                "series_id": "series_1",
                "series_project_id": "series_1",
                "series_item_id": "item_1",
                "series_item_index": 0,
                "series_item_title": "旧主题",
                "series_template_snapshot": snapshot,
                "series_context_snapshot": "冻结规则：旧版原创水彩",
            }

    class FakeContent:
        def generate_content(self, topic, outline, **kwargs):
            captured.update(kwargs)
            return {"success": True, "titles": ["标题"], "copywriting": "正文", "tags": ["标签"]}

    monkeypatch.setattr(content_routes, "get_history_service", lambda: FakeHistory())
    monkeypatch.setattr(content_routes, "get_content_service", lambda: FakeContent())
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_content_blueprint(), url_prefix="/api")

    response = app.test_client().post(
        "/api/content",
        json={"topic": "旧主题", "outline": "旧大纲", "record_id": "record_1"},
    )
    assert response.status_code == 200
    assert captured["series_context"] == "冻结规则：旧版原创水彩"
    assert captured["series_template"]["revision"] == 1
    assert captured["series_item_id"] == "item_1"


def test_outline_is_background_write_locked_and_empty_confirm_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")

    class HeldThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(series_routes.threading, "Thread", HeldThread)
    client = make_client()
    template = client.post("/api/series/templates", json=template_payload()).get_json()["template"]
    project = client.post(
        "/api/series/projects",
        json={"template_id": template["id"], "topics": ["第一篇"]},
    ).get_json()["project"]
    item = project["items"][0]

    queued = client.post(f"/api/series/projects/{project['id']}/items/{item['id']}/outline", json={})
    assert queued.status_code == 202
    assert queued.get_json()["item"]["status"] == "queued"
    blocked = client.put(
        f"/api/series/projects/{project['id']}/items/{item['id']}",
        json={"outline": "不应写入"},
    )
    assert blocked.status_code == 409

    with series_routes._active_lock:
        series_routes._active_projects.discard(project["id"])
    saved = series.get_project(project["id"])
    saved_item = series.get_project_item(saved, item["id"])
    saved_item.update({
        "status": "outline_ready",
        "outline_status": "ready",
        "outline": "已生成大纲",
        "pages": [
            {"index": index, "type": page_type, "content": f"第 {index + 1} 页"}
            for index, page_type in enumerate(["cover", "content", "content", "content", "summary"])
        ],
    })
    series.save_project(saved)

    empty_confirm = client.post(
        f"/api/series/projects/{project['id']}/confirm",
        json={"item_ids": []},
    )
    assert empty_confirm.status_code == 200
    assert empty_confirm.get_json()["items"] == []
    assert series.get_project_item(series.get_project(project["id"]), item["id"])["outline_status"] == "ready"


def test_background_outline_worker_finishes_selected_items_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], ["第一篇", "第二篇"])
    calls = []

    class FakeOutlineService:
        def generate_outline(self, topic, images=None, **context):
            calls.append(topic)
            page_types = ["cover", "content", "content", "content", "summary"]
            return {
                "success": True,
                "outline": f"{topic} 大纲",
                "pages": [
                    {"index": index, "type": page_type, "content": f"{topic} 第 {index + 1} 页"}
                    for index, page_type in enumerate(page_types)
                ],
            }

    monkeypatch.setattr(series_routes, "get_outline_service", lambda: FakeOutlineService())
    item_ids = [item["id"] for item in project["items"]]
    series_routes._run_outline_generation(project["id"], item_ids)

    saved = series.get_project(project["id"])
    assert calls == ["第一篇", "第二篇"]
    assert [item["status"] for item in saved["items"]] == ["outline_ready", "outline_ready"]


def test_item_confirm_exposes_confirmed_state_and_flat_pagination(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")
    template = series.create_template(template_payload())
    project = series.create_project(template["id"], ["第一篇"])
    item = project["items"][0]
    stored = series.get_project(project["id"])
    stored_item = series.get_project_item(stored, item["id"])
    stored_item.update({
        "status": "outline_ready",
        "outline_status": "ready",
        "outline": "完整大纲",
        "pages": [
            {"index": index, "type": page_type, "content": f"第 {index + 1} 页"}
            for index, page_type in enumerate(["cover", "content", "content", "content", "summary"])
        ],
    })
    series.save_project(stored)
    client = make_client()

    confirmed = client.post(
        f"/api/series/projects/{project['id']}/items/{item['id']}/confirm",
        json={"confirm": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["item"]["status"] == "confirmed"
    assert confirmed.get_json()["item"]["outline_status"] == "confirmed"
    assert confirmed.get_json()["project"]["status"] == "confirmed"

    listed = client.get(f"/api/series/projects/{project['id']}/items?page=1&page_size=10")
    assert listed.status_code == 200
    assert listed.get_json()["total"] == 1
    assert listed.get_json()["total_pages"] == 1


def test_delete_item_route_removes_item_and_keeps_history_link(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")
    client = make_client()
    template = client.post("/api/series/templates", json=template_payload()).get_json()["template"]
    project = client.post(
        "/api/series/projects",
        json={"template_id": template["id"], "topics": ["保留主题", "移除主题"]},
    ).get_json()["project"]
    saved = series.get_project(project["id"])
    saved["items"][1]["status"] = "completed"
    saved["items"][1]["record_id"] = "record_keep_me"
    series.save_project(saved)

    response = client.delete(f"/api/series/projects/{project['id']}/items/{saved['items'][1]['id']}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["deleted_item"]["record_id"] == "record_keep_me"
    assert [item["topic"] for item in payload["project"]["items"]] == ["保留主题"]
    assert payload["message"] == "子主题已从合集移除；对应历史成品仍保留。"


def test_delete_item_route_rejects_active_item(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")
    client = make_client()
    template = client.post("/api/series/templates", json=template_payload()).get_json()["template"]
    project = client.post(
        "/api/series/projects",
        json={"template_id": template["id"], "topics": ["生成中的主题"]},
    ).get_json()["project"]
    saved = series.get_project(project["id"])
    saved["items"][0]["status"] = "generating"
    series.save_project(saved)

    response = client.delete(f"/api/series/projects/{project['id']}/items/{saved['items'][0]['id']}")

    assert response.status_code == 409
    assert "正在生成" in response.get_json()["error"]["detail"]


def test_character_sheet_outline_is_deterministic_per_character(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(series, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(series, "SERIES_ROOT", tmp_path / "series")
    template = series.create_template(template_payload("像素角色模板"))
    project = series.create_project(template["id"], ["海贼王：路飞、索隆、娜美"], content_mode="character_sheet")

    # 不应调用文本大纲模型：角色图模式是确定性单页流程。
    def should_not_call(*args, **kwargs):
        raise AssertionError("character_sheet 不应请求故事大纲模型")

    monkeypatch.setattr(series_routes, "get_outline_service", should_not_call)
    series_routes._run_outline_generation(project["id"], [project["items"][0]["id"]])
    saved = series.get_project(project["id"])
    item = saved["items"][0]
    assert item["outline_status"] == "ready"
    assert item["status"] == "outline_ready"
    assert len(item["pages"]) == 3
    assert [page["type"] for page in item["pages"]] == ["cover", "content", "content"]
    assert "路飞" in item["pages"][0]["content"]
    assert "索隆" in item["pages"][1]["content"]
    assert "娜美" in item["pages"][2]["content"]
