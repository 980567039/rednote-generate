"""配置 API 的安全回归测试。"""

import yaml


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_get_config_masks_api_keys(client, monkeypatch, tmp_path):
    from backend.routes import config_routes

    text_path = tmp_path / "text.yaml"
    image_path = tmp_path / "image.yaml"
    secret = "text-secret-value-1234"
    _write_yaml(text_path, {
        "active_provider": "text",
        "providers": {"text": {"type": "openai_compatible", "api_key": secret, "model": "gpt-test"}},
    })
    _write_yaml(image_path, {"active_provider": "image", "providers": {}})
    monkeypatch.setattr(config_routes, "TEXT_CONFIG_PATH", text_path)
    monkeypatch.setattr(config_routes, "IMAGE_CONFIG_PATH", image_path)

    response = client.get("/api/config")
    body = response.get_data(as_text=True)
    data = response.get_json()

    provider = data["config"]["text_generation"]["providers"]["text"]
    assert response.status_code == 200
    assert secret not in body
    assert provider["api_key"] == ""
    assert provider["api_key_masked"].startswith("text")


def test_update_keeps_existing_key_when_editor_leaves_it_blank(client, monkeypatch, tmp_path):
    from backend.routes import config_routes

    text_path = tmp_path / "text.yaml"
    image_path = tmp_path / "image.yaml"
    _write_yaml(text_path, {
        "active_provider": "text",
        "providers": {
            "text": {
                "type": "openai_compatible",
                "api_key": "preserve-this-key",
                "base_url": "https://old.example/v1",
                "model": "old-model",
                "max_output_tokens": 8000,
            }
        },
    })
    _write_yaml(image_path, {"active_provider": "", "providers": {}})
    monkeypatch.setattr(config_routes, "TEXT_CONFIG_PATH", text_path)
    monkeypatch.setattr(config_routes, "IMAGE_CONFIG_PATH", image_path)

    response = client.post("/api/config", json={
        "text_generation": {
            "active_provider": "text",
            "providers": {
                "text": {
                    "type": "openai_compatible",
                    "api_key": "",
                    "api_key_masked": "text********key",
                    "base_url": "https://new.example/v1",
                    "model": "gpt-5.6-sol",
                    "endpoint_type": "/v1/chat/completions",
                }
            },
        }
    })

    saved = yaml.safe_load(text_path.read_text(encoding="utf-8"))
    provider = saved["providers"]["text"]
    assert response.status_code == 200
    assert provider["api_key"] == "preserve-this-key"
    assert provider["model"] == "gpt-5.6-sol"
    assert provider["max_output_tokens"] == 8000
    assert "api_key_masked" not in provider


def test_image_openai_compatible_test_loads_image_provider(client, monkeypatch, tmp_path):
    from backend.routes import config_routes

    text_path = tmp_path / "text.yaml"
    image_path = tmp_path / "image.yaml"
    _write_yaml(text_path, {"active_provider": "", "providers": {}})
    _write_yaml(image_path, {
        "active_provider": "image",
        "providers": {
            "image": {
                "type": "openai_compatible",
                "api_key": "image-only-key",
                "base_url": "https://image.example/v1",
                "model": "gpt-image-2",
                "endpoint_type": "/v1/images/generations",
            }
        },
    })
    monkeypatch.setattr(config_routes, "TEXT_CONFIG_PATH", text_path)
    monkeypatch.setattr(config_routes, "IMAGE_CONFIG_PATH", image_path)
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers

        class Response:
            status_code = 200

        return Response()

    monkeypatch.setattr("requests.get", fake_get)
    response = client.post("/api/config/test", json={
        "category": "image",
        "type": "openai_compatible",
        "provider_name": "image",
    })

    assert response.status_code == 200
    assert captured["url"] == "https://image.example/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer image-only-key"


def test_update_rejects_an_active_provider_that_was_removed(client, monkeypatch, tmp_path):
    from backend.routes import config_routes

    text_path = tmp_path / "text.yaml"
    image_path = tmp_path / "image.yaml"
    _write_yaml(text_path, {"active_provider": "text", "providers": {"text": {"type": "openai_compatible"}}})
    _write_yaml(image_path, {"active_provider": "", "providers": {}})
    monkeypatch.setattr(config_routes, "TEXT_CONFIG_PATH", text_path)
    monkeypatch.setattr(config_routes, "IMAGE_CONFIG_PATH", image_path)

    response = client.post("/api/config", json={
        "text_generation": {
            "active_provider": "text",
            "providers": {},
        }
    })

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"
