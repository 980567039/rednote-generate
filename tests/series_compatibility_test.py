"""系列上下文的向后兼容与本地数据安全回归测试。

这些测试刻意只覆盖“没有选择系列”的原有创作流程，以及旧历史记录的
读取/更新行为。系列功能可以在各 API 中增加可选字段，但不能要求自由创作、
旅游攻略或旧历史文件补齐这些字段后才能继续工作。
"""

import json
from pathlib import Path

import pytest
from flask import Flask

import backend.routes.content_routes as content_routes
import backend.routes.image_routes as image_routes
import backend.routes.outline_routes as outline_routes
from backend.routes.content_routes import create_content_blueprint
from backend.routes.image_routes import create_image_blueprint
from backend.routes.outline_routes import create_outline_blueprint
from backend.services.history import HistoryService


EMPTY_SERIES_CONTEXT = {
    "series_id": None,
    "series_template_id": None,
    "series_item_index": None,
    "series_item_title": None,
}


def make_history_service(tmp_path: Path) -> HistoryService:
    service = HistoryService.__new__(HistoryService)
    service.history_dir = str(tmp_path)
    service.index_file = str(tmp_path / "index.json")
    service._init_index()
    return service


def test_legacy_character_record_keeps_marker_fallback(monkeypatch):
    legacy_record = {
        "series_id": "series_legacy",
        "series_template_snapshot": {
            "id": "template_legacy",
            "page_structure": {"preset": "character_sheet", "page_count": 1},
        },
        "series_context_snapshot": "内容方向：精细角色图（单张）",
    }

    class FakeHistoryService:
        def get_record(self, record_id):
            assert record_id == "record_legacy"
            return legacy_record

    monkeypatch.setattr(
        image_routes,
        "get_history_service",
        lambda: FakeHistoryService(),
    )

    context = image_routes._series_context_for_request({}, "record_legacy")

    assert context["content_mode"] == "character_sheet"
    assert "内容方向：精细角色图" in context["series_context"]


def test_legacy_character_snapshot_recovers_structured_mode():
    """没有 content_mode 的旧条目仍应走角色图而不是故事分镜。"""
    from backend.routes import series_routes

    snapshot = {
        "id": "template_legacy",
        "page_structure": {"preset": "character_sheet", "page_count": 1},
    }
    project = {"id": "series_legacy", "template_id": snapshot["id"]}
    item = {
        "id": "item_legacy",
        "topic": "孤独摇滚：后藤一里",
        "template_snapshot": snapshot,
        "series_context_snapshot": "",
    }

    context = series_routes._context(project, item)

    assert context["content_mode"] == "character_sheet"
    assert "精细角色图" in context["series_context"]


def test_series_route_rebuilds_stale_context_when_explicit_mode_conflicts():
    """系列生成链路不能复用与条目模式相反的旧冻结上下文。"""
    from backend.routes import series_routes

    snapshot = {
        "id": "template_legacy",
        "name": "旧合集",
        "page_structure": {"preset": "standard", "page_count": 5},
        "visual_style": "普通插画",
        "palette": "自然色",
        "composition": "3:4 竖版",
        "character_bible": "角色保持一致",
        "copy_tone": "简洁",
    }
    project = {"id": "series_legacy", "template_id": snapshot["id"]}
    item = {
        "id": "item_legacy",
        "topic": "故事主题",
        "content_mode": "story",
        "template_snapshot": snapshot,
        "series_context_snapshot": "内容方向：精细角色图（单张）",
    }

    context = series_routes._context(project, item)

    assert context["content_mode"] == "story"
    assert "内容方向：精细角色图" not in context["series_context"]
    assert "内容方向：剧情小故事" in context["series_context"]


def test_explicit_story_mode_rebuilds_stale_character_context(monkeypatch):
    """显式故事请求不能再次携带旧角色合集规则。"""
    legacy_record = {
        "series_id": "series_legacy",
        "series_template_snapshot": {
            "id": "template_legacy",
            "name": "旧合集",
            "page_structure": {"preset": "character_sheet", "page_count": 1},
        },
        "series_content_mode": "character_sheet",
        "series_context_snapshot": "内容方向：精细角色图（单张）",
    }

    class FakeHistoryService:
        def get_record(self, record_id):
            return legacy_record

    monkeypatch.setattr(image_routes, "get_history_service", lambda: FakeHistoryService())

    context = image_routes._series_context_for_request(
        {"content_mode": "story"},
        "record_legacy",
        "故事主题",
    )

    assert context["content_mode"] == "story"
    assert "内容方向：精细角色图" not in context["series_context"]
    assert "剧情小故事" in context["series_context"]


def test_legacy_record_without_template_drops_conflicting_context(monkeypatch):
    """无模板快照的最旧记录也不能把角色规则带进显式故事重绘。"""
    legacy_record = {
        "series_id": "series_legacy",
        "series_context_snapshot": "内容方向：精细角色图（单张）",
        "series_content_mode": "character_sheet",
    }

    class FakeHistoryService:
        def get_record(self, record_id):
            return legacy_record

    monkeypatch.setattr(image_routes, "get_history_service", lambda: FakeHistoryService())

    context = image_routes._series_context_for_request(
        {"content_mode": "story"},
        "record_legacy",
        "故事主题",
    )

    assert context["content_mode"] == "story"
    assert context["series_context"] == ""


def test_project_payload_drops_conflicting_frozen_context():
    """项目条目读取路径和图片路由使用同一套冻结上下文校验。"""
    from backend.services import series

    original_get_project = series.get_project
    original_get_template = series.get_template
    snapshot = {
        "id": "template_legacy",
        "page_structure": {"preset": "standard", "page_count": 5},
    }
    project = {
        "id": "series_legacy",
        "template_id": snapshot["id"],
        "items": [{
            "id": "item_legacy",
            "topic": "故事主题",
            "content_mode": "story",
            "template_snapshot": snapshot,
            "series_context_snapshot": "内容方向：精细角色图（单张）",
        }],
    }
    try:
        series.get_project = lambda project_id: project  # type: ignore[assignment]
        series.get_template = lambda template_id: snapshot  # type: ignore[assignment]
        context = series.series_context_from_payload({
            "series_project_id": "series_legacy",
            "series_item_id": "item_legacy",
        })
    finally:
        series.get_project = original_get_project  # type: ignore[assignment]
        series.get_template = original_get_template  # type: ignore[assignment]

    assert context["content_mode"] == "story"
    assert "内容方向：精细角色图" not in context["series_context"]


def test_legacy_character_history_context_is_restored_for_content_route(monkeypatch):
    captured = {}
    snapshot = {
        "id": "template_legacy",
        "name": "旧合集",
        "page_structure": {"preset": "character_sheet", "page_count": 1},
    }

    class FakeHistory:
        def get_record(self, record_id):
            return {
                "series_id": "series_legacy",
                "series_template_snapshot": snapshot,
                "series_context_snapshot": "",
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
        json={"topic": "孤独摇滚：后藤一里", "outline": "角色大纲", "record_id": "record_legacy"},
    )

    assert response.status_code == 200
    assert captured["content_mode"] == "character_sheet"
    assert "精细角色图" in captured["series_context"]


@pytest.mark.parametrize(
    "topic",
    [
        "使用 Codex 之前和之后的我，做成夸张的前后对比",
        (
            "生成北京故宫一日旅游攻略。\n\n"
            "【旅行条件】游玩时长：一天；同行人群：朋友；"
            "旅行偏好：拍照出片、少走回头路。\n\n"
            "请优先给出少折返的路线，并提醒开放时间以官方信息为准。"
        ),
    ],
    ids=["free-creation", "travel-guide"],
)
def test_outline_without_series_preserves_existing_topic(monkeypatch, topic):
    captured = {}

    class FakeOutlineService:
        def generate_outline(self, received_topic, images=None, **series_context):
            captured["topic"] = received_topic
            captured["images"] = images
            captured["series_context"] = series_context
            return {
                "success": True,
                "outline": "[封面]\n兼容性测试",
                "pages": [{"index": 0, "type": "cover", "content": "兼容性测试"}],
            }

    monkeypatch.setattr(
        outline_routes,
        "get_outline_service",
        lambda: FakeOutlineService(),
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_outline_blueprint(), url_prefix="/api")

    response = app.test_client().post(
        "/api/outline",
        json={"topic": topic, **EMPTY_SERIES_CONTEXT},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert captured["topic"] == topic
    assert captured["images"] in (None, [])
    assert all(value is None for value in captured["series_context"].values())


@pytest.mark.parametrize(
    "topic",
    [
        "一篇自由创作的主题",
        "北京颐和园旅游攻略｜一天｜朋友｜拍照出片、少走回头路",
    ],
    ids=["free-creation", "travel-guide"],
)
def test_content_without_series_preserves_existing_inputs(monkeypatch, topic):
    outline = "[封面]\n原有大纲内容"
    captured = {}

    class FakeContentService:
        def generate_content(
            self,
            received_topic,
            received_outline,
            **series_context,
        ):
            captured["topic"] = received_topic
            captured["outline"] = received_outline
            captured["series_context"] = series_context
            return {
                "success": True,
                "titles": ["兼容标题"],
                "copywriting": "兼容正文",
                "tags": ["兼容标签"],
            }

    monkeypatch.setattr(
        content_routes,
        "get_content_service",
        lambda: FakeContentService(),
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_content_blueprint(), url_prefix="/api")

    response = app.test_client().post(
        "/api/content",
        json={
            "topic": topic,
            "outline": outline,
            **EMPTY_SERIES_CONTEXT,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert captured["topic"] == topic
    assert captured["outline"] == outline
    assert all(value is None for value in captured["series_context"].values())


def test_image_generation_without_series_preserves_existing_inputs(monkeypatch):
    pages = [{"index": 0, "type": "cover", "content": "自由创作封面"}]
    captured = {}

    class FakeImageService:
        def prepare_generation(
            self,
            received_pages,
            task_id=None,
            record_id=None,
            force=False,
            **series_context,
        ):
            captured["prepared_pages"] = received_pages
            captured["prepare_series_context"] = series_context
            return {
                "task_id": "task_series_compat",
                "record_id": record_id,
                "cached": False,
                "reused": False,
            }

        def generate_images(
            self,
            received_pages,
            task_id,
            full_outline,
            user_images=None,
            user_topic="",
            record_id=None,
            force=False,
            prepared=False,
            cached=False,
            **series_context,
        ):
            captured["generated_pages"] = received_pages
            captured["full_outline"] = full_outline
            captured["user_topic"] = user_topic
            captured["generate_series_context"] = series_context
            yield {
                "event": "accepted",
                "data": {
                    "task_id": task_id,
                    "record_id": record_id,
                    "status": "queued",
                },
            }
            yield {
                "event": "finish",
                "data": {
                    "success": True,
                    "task_id": task_id,
                    "images": ["0.png"],
                    "total": 1,
                    "completed": 1,
                    "failed": 0,
                    "failed_indices": [],
                },
            }

    monkeypatch.setattr(
        image_routes,
        "get_image_service",
        lambda: FakeImageService(),
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_image_blueprint(), url_prefix="/api")

    response = app.test_client().post(
        "/api/generate",
        json={
            "pages": pages,
            "full_outline": "自由创作完整大纲",
            "user_topic": "自由创作主题",
            **EMPTY_SERIES_CONTEXT,
        },
    )

    assert response.status_code == 200
    assert "event: finish" in response.get_data(as_text=True)
    assert captured["prepared_pages"] == pages
    assert captured["generated_pages"] == pages
    assert captured["full_outline"] == "自由创作完整大纲"
    assert captured["user_topic"] == "自由创作主题"
    assert all(value is None for value in captured["prepare_series_context"].values())
    assert all(value is None for value in captured["generate_series_context"].values())


def test_legacy_history_without_series_fields_remains_readable(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "旧版自由创作",
        {
            "raw": "旧版大纲",
            "pages": [{"index": 0, "type": "cover", "content": "旧版封面"}],
        },
    )
    record_path = Path(service._get_record_path(record_id))
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    stored.pop("content", None)
    for field in EMPTY_SERIES_CONTEXT:
        stored.pop(field, None)
    service._atomic_write_json(str(record_path), stored)

    record = service.get_record(record_id)

    assert record is not None
    assert record["title"] == "旧版自由创作"
    assert record["outline"] == stored["outline"]
    assert record["images"] == stored["images"]
    assert record["content"] == {
        "titles": [],
        "copywriting": "",
        "tags": [],
        "status": "idle",
    }
    assert all(record.get(field) is None for field in EMPTY_SERIES_CONTEXT)


def test_updating_legacy_content_preserves_existing_series_metadata(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("系列单篇", {"raw": "大纲", "pages": []})
    record_path = Path(service._get_record_path(record_id))
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    stored.update(
        {
            "series_id": "series-001",
            "series_template_id": "template-001",
            "series_item_index": 2,
            "series_item_title": "第二篇",
        }
    )
    service._atomic_write_json(str(record_path), stored)

    assert service.update_record(
        record_id,
        content={
            "titles": ["新标题"],
            "copywriting": "新正文",
            "tags": ["新标签"],
            "status": "done",
        },
    )
    updated = service.get_record(record_id)

    assert updated is not None
    assert {
        field: updated.get(field) for field in EMPTY_SERIES_CONTEXT
    } == {
        "series_id": "series-001",
        "series_template_id": "template-001",
        "series_item_index": 2,
        "series_item_title": "第二篇",
    }
