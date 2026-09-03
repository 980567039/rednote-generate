import io
from pathlib import Path

from flask import Flask
from PIL import Image

import backend.routes.history_routes as history_routes
from backend.routes.history_routes import create_history_blueprint
from backend.services.history import HistoryService


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
