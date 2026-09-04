import io
from pathlib import Path

import pytest

from flask import Flask
from PIL import Image

import backend.routes.history_routes as history_routes
from backend.routes.history_routes import create_history_blueprint
from backend.services.history import (
    HistoryPageDeletionConflictError,
    HistoryService,
)


def make_history_service(tmp_path: Path) -> HistoryService:
    service = HistoryService.__new__(HistoryService)
    service.history_dir = str(tmp_path)
    service.index_file = str(tmp_path / "index.json")
    service._init_index()
    service._ensure_lock()
    return service


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(output, format="PNG")
    return output.getvalue()


def test_append_pattern_page_is_atomic_and_idempotent(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "系列角色",
        {
            "raw": "[封面]\n角色",
            "pages": [{"index": 0, "type": "cover", "content": "角色"}],
        },
        task_id="task_pattern",
    )
    task_dir = tmp_path / "task_pattern"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    service.update_record(
        record_id,
        images={"task_id": "task_pattern", "generated": ["0.png"]},
        status="completed",
        thumbnail="0.png",
    )

    first = service.append_pattern_image(record_id, "req-1", png_bytes(), 0, 104, 104, 40)
    service.update_record(record_id, content={"status": "done"})
    second = service.append_pattern_image(record_id, "req-1", b"invalid", 0, 104, 104, 40)
    record = service.get_record(record_id)

    assert first["appended"] is True
    assert second["appended"] is False
    assert len(record["outline"]["pages"]) == 2
    assert record["outline"]["pages"][-1]["type"] == "pattern"
    assert len(record["images"]["generated"]) == 2
    assert record["images"]["generated"][-1].startswith("pattern_")
    assert (task_dir / record["images"]["generated"][-1]).read_bytes() == png_bytes()


def test_append_pattern_page_saves_visual_outputs_without_extra_page(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "系列角色",
        {"pages": [{"index": 0, "type": "cover", "content": "角色"}]},
        task_id="task_pattern",
    )
    task_dir = tmp_path / "task_pattern"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    service.update_record(record_id, images={"task_id": "task_pattern", "generated": ["0.png"]}, status="completed")

    result = service.append_pattern_image(
        record_id,
        "req-effects",
        png_bytes(),
        0,
        104,
        104,
        40,
        beads_data=png_bytes(),
        ironed_data=png_bytes(),
    )
    record = service.get_record(record_id)
    page = record["outline"]["pages"][-1]
    outputs = page["pattern"]["outputs"]

    assert result["appended"] is True
    assert set(outputs) == {"beads", "ironed"}
    assert len(record["outline"]["pages"]) == 2
    assert len(record["images"]["generated"]) == 2
    assert all((task_dir / filename).is_file() for filename in outputs.values())

    duplicate = service.append_pattern_image(
        record_id,
        "req-effects",
        b"invalid",
        0,
        104,
        104,
        40,
    )
    assert duplicate["appended"] is False
    assert duplicate["outputs"] == outputs


def test_append_pattern_page_backfills_outputs_for_legacy_request(tmp_path):
    """A first append from an older client may have only the grid master.

    Retrying the same request with the two visual exports must attach them to
    the existing page instead of creating a duplicate page or orphan files.
    """
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "旧客户端记录",
        {"pages": [{"index": 0, "type": "cover", "content": "角色"}]},
        task_id="task_pattern",
    )
    task_dir = tmp_path / "task_pattern"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    service.update_record(record_id, images={"task_id": "task_pattern", "generated": ["0.png"]}, status="completed")

    first = service.append_pattern_image(record_id, "legacy-request", png_bytes(), 0, 104, 104, 40)
    second = service.append_pattern_image(
        record_id,
        "legacy-request",
        png_bytes(),
        0,
        104,
        104,
        40,
        beads_data=png_bytes(),
        ironed_data=png_bytes(),
    )
    record = service.get_record(record_id)
    page = record["outline"]["pages"][1]
    outputs = page["pattern"]["outputs"]

    assert first["appended"] is True
    assert second["appended"] is False
    assert second["page_index"] == 1
    assert set(outputs) == {"beads", "ironed"}
    assert second["outputs"] == outputs
    assert len(record["outline"]["pages"]) == 2
    assert len(record["images"]["generated"]) == 2
    assert all((task_dir / filename).is_file() for filename in outputs.values())


def test_append_pattern_page_rejects_inconsistent_history(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "坏数据",
        {"pages": [{"index": 0, "type": "cover", "content": "角色"}]},
        task_id="task_pattern",
    )
    (tmp_path / "task_pattern").mkdir()
    service.update_record(record_id, images={"task_id": "task_pattern", "generated": []})

    try:
        service.append_pattern_image(record_id, "req-1", png_bytes(), 0, 104, 104, 40)
    except ValueError as exc:
        assert "页面和图片数量" in str(exc)
    else:
        raise AssertionError("页面与图片数量不一致时不应追加图纸")


def test_append_pattern_page_rejects_unknown_or_pattern_source(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "系列角色",
        {
            "pages": [
                {"index": 0, "type": "cover", "content": "角色"},
                {"index": 1, "type": "pattern", "content": "图纸"},
            ]
        },
        task_id="task_pattern",
    )
    task_dir = tmp_path / "task_pattern"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    (task_dir / "pattern-existing.png").write_bytes(png_bytes())
    service.update_record(
        record_id,
        images={"task_id": "task_pattern", "generated": ["0.png", "pattern-existing.png"]},
        status="completed",
    )

    for source_index in (1, 2):
        try:
            service.append_pattern_image(record_id, f"req-{source_index}", png_bytes(), source_index, 104, 104, 40)
        except ValueError as exc:
            assert "来源图片索引" in str(exc)
        else:
            raise AssertionError("来源图片索引无效时不应追加图纸")


def test_pattern_page_route_requires_explicit_upload_and_is_idempotent(tmp_path, monkeypatch):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "系列角色",
        {"pages": [{"index": 0, "type": "cover", "content": "角色"}]},
        task_id="task_pattern",
    )
    task_dir = tmp_path / "task_pattern"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    service.update_record(record_id, images={"task_id": "task_pattern", "generated": ["0.png"]}, status="completed")
    monkeypatch.setattr(history_routes, "get_history_service", lambda: service)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_history_blueprint(), url_prefix="/api")
    client = app.test_client()
    response = client.post(
        f"/api/history/{record_id}/pattern-pages",
        data={
            "request_id": "route-1",
            "source_image_index": "0",
            "columns": "104",
            "rows": "104",
            "used_colors": "40",
            "pattern": (io.BytesIO(png_bytes()), "master.png"),
            "beads": (io.BytesIO(png_bytes()), "beads.png"),
            "ironed": (io.BytesIO(png_bytes()), "ironed.png"),
        },
        content_type="multipart/form-data",
    )
    duplicate = client.post(
        f"/api/history/{record_id}/pattern-pages",
        data={
            "request_id": "route-1",
            "pattern": (io.BytesIO(b"not-read"), "master.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["appended"] is True
    assert set(response.get_json()["outputs"]) == {"beads", "ironed"}
    assert duplicate.status_code == 200
    assert duplicate.get_json()["appended"] is False


def test_delete_pattern_page_removes_master_and_visual_outputs(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "系列角色",
        {
            "raw": "封面\n\n<page>\n\n内容",
            "pages": [
                {"index": 0, "type": "cover", "content": "封面"},
                {"index": 1, "type": "content", "content": "内容"},
            ],
        },
        task_id="task_delete",
    )
    task_dir = tmp_path / "task_delete"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    (task_dir / "1.png").write_bytes(png_bytes())
    service.update_record(
        record_id,
        images={"task_id": "task_delete", "generated": ["0.png", "1.png"]},
        status="completed",
        thumbnail="0.png",
    )
    appended = service.append_pattern_image(
        record_id,
        "delete-request",
        png_bytes(),
        1,
        104,
        104,
        12,
        beads_data=png_bytes(),
        ironed_data=png_bytes(),
    )
    record_before = service.get_record(record_id)
    pattern_page = record_before["outline"]["pages"][2]
    master = record_before["images"]["generated"][2]
    outputs = pattern_page["pattern"]["outputs"]
    assert all((task_dir / filename).is_file() for filename in [master, *outputs.values()])

    result = service.delete_page(record_id, 2)
    record_after = service.get_record(record_id)

    assert result["deleted_type"] == "pattern"
    assert len(record_after["outline"]["pages"]) == 2
    assert record_after["images"]["generated"] == ["0.png", "1.png"]
    assert "pattern_requests" not in record_after["images"]
    assert all(not (task_dir / filename).exists() for filename in [master, *outputs.values()])
    assert (task_dir / "0.png").is_file()
    assert (task_dir / "1.png").is_file()


def test_delete_source_page_rejects_when_pattern_depends_on_it(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "系列角色",
        {
            "raw": "封面",
            "pages": [{"index": 0, "type": "cover", "content": "封面"}],
        },
        task_id="task_conflict",
    )
    task_dir = tmp_path / "task_conflict"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    service.update_record(record_id, images={"task_id": "task_conflict", "generated": ["0.png"]}, status="completed")
    service.append_pattern_image(record_id, "conflict-request", png_bytes(), 0, 104, 104, 12)

    with pytest.raises(HistoryPageDeletionConflictError):
        service.delete_page(record_id, 0)

    record = service.get_record(record_id)
    assert len(record["outline"]["pages"]) == 2
    assert (task_dir / "0.png").is_file()


def test_delete_original_page_reindexes_remaining_pages_and_files(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "两页作品",
        {
            "raw": "第一页\n\n<page>\n\n第二页",
            "pages": [
                {"index": 0, "type": "cover", "content": "第一页"},
                {"index": 1, "type": "content", "content": "第二页"},
            ],
        },
        task_id="task_reindex",
    )
    task_dir = tmp_path / "task_reindex"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    (task_dir / "1.png").write_bytes(png_bytes())
    (task_dir / "thumb_0.png").write_bytes(png_bytes())
    (task_dir / "thumb_1.png").write_bytes(png_bytes())
    service.update_record(record_id, images={"task_id": "task_reindex", "generated": ["0.png", "1.png"]}, status="completed")

    service.delete_page(record_id, 0)
    record = service.get_record(record_id)

    assert [page["index"] for page in record["outline"]["pages"]] == [0]
    assert record["outline"]["pages"][0]["content"] == "第二页"
    assert record["images"]["generated"] == ["0.png"]
    assert "第一页" not in record["outline"]["raw"]
    assert (task_dir / "0.png").is_file()
    assert not (task_dir / "1.png").exists()
    assert (task_dir / "thumb_0.png").is_file()
    assert not (task_dir / "thumb_1.png").exists()

    synced = service.sync_record_images(record_id)
    assert synced["updated"] is False
    assert service.get_record(record_id)["images"]["generated"] == ["0.png"]


def test_delete_middle_pattern_page_reindexes_following_original_images(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "图纸在中间",
        {
            "raw": "第一页\n\n<page>\n\n图纸\n\n<page>\n\n第三页",
            "pages": [
                {"index": 0, "type": "content", "content": "第一页"},
                {"index": 1, "type": "pattern", "content": "图纸", "pattern": {"source_image_index": 0}},
                {"index": 2, "type": "content", "content": "第三页"},
            ],
        },
        task_id="task_middle_pattern",
    )
    task_dir = tmp_path / "task_middle_pattern"
    task_dir.mkdir()
    for filename in ("0.png", "pattern.png", "2.png"):
        (task_dir / filename).write_bytes(png_bytes())
    service.update_record(
        record_id,
        images={"task_id": "task_middle_pattern", "generated": ["0.png", "pattern.png", "2.png"]},
        status="completed",
    )

    service.delete_page(record_id, 1)
    record = service.get_record(record_id)
    assert [page["index"] for page in record["outline"]["pages"]] == [0, 1]
    assert record["images"]["generated"] == ["0.png", "1.png"]
    assert (task_dir / "0.png").is_file()
    assert (task_dir / "1.png").is_file()
    assert not (task_dir / "2.png").exists()
    assert service.sync_record_images(record_id)["updated"] is False


def test_delete_page_route_returns_updated_record_and_conflict_status(tmp_path, monkeypatch):
    service = make_history_service(tmp_path)
    record_id = service.create_record(
        "路由删除",
        {"pages": [{"index": 0, "type": "cover", "content": "封面"}]},
        task_id="task_route_delete",
    )
    task_dir = tmp_path / "task_route_delete"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(png_bytes())
    service.update_record(record_id, images={"task_id": "task_route_delete", "generated": ["0.png"]}, status="completed")
    service.append_pattern_image(record_id, "route-delete-request", png_bytes(), 0, 104, 104, 12)
    monkeypatch.setattr(history_routes, "get_history_service", lambda: service)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_history_blueprint(), url_prefix="/api")
    client = app.test_client()

    conflict = client.delete(f"/api/history/{record_id}/pages/0")
    assert conflict.status_code == 409
    assert "先删除关联的拼豆图纸" in conflict.get_json()["error_message"]

    deleted = client.delete(f"/api/history/{record_id}/pattern-pages/1")
    assert deleted.status_code == 200
    payload = deleted.get_json()
    assert payload["success"] is True
    assert payload["deleted_type"] == "pattern"
    assert len(payload["record"]["outline"]["pages"]) == 1
