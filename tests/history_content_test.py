import json
from pathlib import Path

import pytest
from flask import Flask

import backend.routes.history_routes as history_routes
from backend.routes.history_routes import create_history_blueprint
from backend.services.history import HistoryService


def make_history_service(tmp_path: Path) -> HistoryService:
    service = HistoryService.__new__(HistoryService)
    service.history_dir = str(tmp_path)
    service.index_file = str(tmp_path / "index.json")
    service._init_index()
    return service


@pytest.fixture
def history_client(tmp_path, monkeypatch):
    service = make_history_service(tmp_path)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_history_blueprint(), url_prefix="/api")
    monkeypatch.setattr(history_routes, "get_history_service", lambda: service)
    return app.test_client(), service


def test_new_history_record_has_safe_empty_content(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {"raw": "raw", "pages": []})

    assert service.get_record(record_id)["content"] == {
        "titles": [],
        "copywriting": "",
        "tags": [],
        "status": "idle",
    }


def test_get_legacy_record_without_content_returns_compatible_default(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("legacy", {"raw": "raw", "pages": []})
    record_path = Path(service._get_record_path(record_id))
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    stored.pop("content")
    service._atomic_write_json(str(record_path), stored)

    assert service.get_record(record_id)["content"] == {
        "titles": [],
        "copywriting": "",
        "tags": [],
        "status": "idle",
    }


def test_get_legacy_content_without_status_infers_done(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("legacy", {"raw": "raw", "pages": []})
    record_path = Path(service._get_record_path(record_id))
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    stored["content"] = {
        "titles": ["旧标题"],
        "copywriting": "旧正文",
        "tags": ["旧标签"],
    }
    service._atomic_write_json(str(record_path), stored)

    assert service.get_record(record_id)["content"] == {
        "titles": ["旧标题"],
        "copywriting": "旧正文",
        "tags": ["旧标签"],
        "status": "done",
    }


def test_history_api_persists_and_returns_generated_content(history_client):
    client, service = history_client
    record_id = service.create_record("topic", {"raw": "raw", "pages": []})
    content = {
        "titles": ["标题 A", "标题 B"],
        "copywriting": "正文内容",
        "tags": ["标签一", "标签二"],
        "status": "done",
    }

    update_response = client.put(
        f"/api/history/{record_id}",
        json={"content": content},
    )
    assert update_response.status_code == 200
    assert update_response.get_json()["success"] is True

    get_response = client.get(f"/api/history/{record_id}")
    assert get_response.status_code == 200
    assert get_response.get_json()["record"]["content"] == content

    stored = json.loads(
        Path(service._get_record_path(record_id)).read_text(encoding="utf-8")
    )
    assert stored["content"] == content


def test_history_api_supports_partial_content_update(history_client):
    client, service = history_client
    record_id = service.create_record("topic", {"raw": "raw", "pages": []})
    assert service.update_record(
        record_id,
        content={
            "titles": ["保留标题"],
            "copywriting": "保留正文",
            "tags": ["旧标签"],
            "status": "done",
        },
    )

    response = client.put(
        f"/api/history/{record_id}",
        json={"content": {"tags": ["新标签"]}},
    )

    assert response.status_code == 200
    assert service.get_record(record_id)["content"] == {
        "titles": ["保留标题"],
        "copywriting": "保留正文",
        "tags": ["新标签"],
        "status": "done",
    }


@pytest.mark.parametrize(
    "content",
    [
        None,
        [],
        {"titles": "不是列表"},
        {"titles": ["正确", 123]},
        {"copywriting": ["不是字符串"]},
        {"tags": "不是列表"},
        {"tags": ["正确", None]},
        {"status": "completed"},
        {"error": {"message": "不是字符串"}},
    ],
)
def test_history_api_rejects_invalid_content_without_mutating_record(
    history_client,
    content,
):
    client, service = history_client
    record_id = service.create_record("topic", {"raw": "raw", "pages": []})

    response = client.put(
        f"/api/history/{record_id}",
        json={"content": content},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"
    assert service.get_record(record_id)["content"] == {
        "titles": [],
        "copywriting": "",
        "tags": [],
        "status": "idle",
    }
