from flask import Flask

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


def test_publish_auth_contract(tmp_path):
    calls = []

    class Result:
        returncode = 1
        stdout = "NOT_LOGGED_IN"
        stderr = ""

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        if args[-1] == "login":
            result = Result()
            result.returncode = 0
            result.stdout = "LOGIN_READY"
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
    assert response.get_json()["message"]
    assert all(kwargs["shell"] is False for _, kwargs in calls)


def test_missing_publish_task_uses_standard_error_shape(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get("/api/publish/tasks/missing")
    payload = response.get_json()
    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "NOT_FOUND"
