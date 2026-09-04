from flask import Flask
import subprocess

from backend.routes.publish_routes import create_publish_blueprint
from tests.publish_service_test import make_service


def make_client(tmp_path, **service_kwargs):
    service = make_service(tmp_path, start_worker=False, **service_kwargs)
    app = Flask(__name__)
    api = create_publish_blueprint(service)
    app.register_blueprint(api, url_prefix="/api")
    app.config["TESTING"] = True
    return app.test_client(), service


def test_publish_config_routes(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/api/publish/config")
    assert response.status_code == 200
    assert response.get_json()["config"]["default_mode"] == "preview"

    response = client.put("/api/publish/config", json={"account": "main", "port": 9333, "headless": False, "default_mode": "auto"})
    assert response.status_code == 200
    assert response.get_json()["config"]["account"] == "main"


def test_publish_task_routes_and_confirmation(tmp_path):
    client, service = make_client(tmp_path)
    response = client.post(
        "/api/history/record_1/publish",
        json={"title": "测试标题", "copywriting": "测试正文", "tags": ["测试"], "mode": "preview", "confirm": True},
    )
    assert response.status_code == 202
    task_id = response.get_json()["task"]["id"]

    response = client.get(f"/api/publish/tasks/{task_id}")
    assert response.status_code == 200
    assert response.get_json()["task"]["status"] == "queued"

    service._set_status(task_id, "ready_for_review")
    response = client.post(f"/api/publish/tasks/{task_id}/confirm", json={})
    assert response.status_code == 202
    assert response.get_json()["task"]["status"] == "submitting"


def test_publish_requires_explicit_confirmation_and_blocks_duplicate(tmp_path):
    client, _ = make_client(tmp_path)
    body = {"title": "测试标题", "copywriting": "测试正文", "tags": [], "mode": "preview", "confirm": False}
    response = client.post("/api/history/record_1/publish", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"

    body["confirm"] = True
    assert client.post("/api/history/record_1/publish", json=body).status_code == 202
    duplicate = client.post("/api/history/record_1/publish", json=body)
    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"]["code"] == "CONFLICT"


def test_publish_cancel_route_stops_queued_task(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.post(
        "/api/history/record_1/publish",
        json={"title": "取消测试", "copywriting": "测试正文", "tags": [], "mode": "preview", "confirm": True},
    )
    assert response.status_code == 202
    task_id = response.get_json()["task"]["id"]

    response = client.post(f"/api/publish/tasks/{task_id}/cancel", json={})

    assert response.status_code == 200
    assert response.get_json()["task"]["status"] == "cancelled"


def test_publish_auth_contract(tmp_path):
    calls = []

    class Result:
        returncode = 1
        stdout = "NOT_LOGGED_IN"
        stderr = ""

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        if "get-login-qrcode" in args:
            result = Result()
            result.returncode = 0
            result.stdout = (
                'GET_LOGIN_QRCODE_RESULT:\n'
                '{"logged_in": false, "qrcode_data_url": "data:image/png;base64,cXI=", "mime_type": "image/png"}'
            )
            return result
        return Result()

    client, _ = make_client(tmp_path, runner=runner)
    response = client.post("/api/publish/auth/check")
    assert response.status_code == 200
    assert response.get_json()["logged_in"] is False
    assert response.get_json()["authenticated"] is False
    assert response.get_json()["message"]

    response = client.post("/api/publish/auth/login")
    assert response.status_code == 200
    assert response.get_json()["login_started"] is True
    assert response.get_json()["login_url"] == "https://creator.xiaohongshu.com/login"
    assert response.get_json()["qrcode_data_url"].startswith("data:image/png;base64,")
    assert response.get_json()["message"]
    assert all(kwargs["shell"] is False for _, kwargs in calls)


def test_publish_auth_routes_keep_domain_error_codes(tmp_path):
    def timeout_runner(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    client, _ = make_client(tmp_path, runner=timeout_runner)
    cases = [
        ("/api/publish/auth/check", "PUBLISH_AUTH_CHECK_TIMEOUT"),
        ("/api/publish/auth/login", "PUBLISH_LOGIN_TIMEOUT"),
    ]

    for endpoint, expected_code in cases:
        response = client.post(endpoint)
        payload = response.get_json()
        assert response.status_code == 504
        assert payload["success"] is False
        assert payload["error"]["code"] == expected_code
        assert payload["error_message"]
        serialized = str(payload).lower()
        assert "topic" not in serialized
        assert "series" not in serialized
        assert "主题候选" not in serialized


def test_missing_publish_task_uses_standard_error_shape(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/api/publish/tasks/missing")
    payload = response.get_json()
    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "NOT_FOUND"
