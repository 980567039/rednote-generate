import base64
import requests

from backend.generators.image_api_client import ImageApiClient
from backend.generators.image_provider_policy import ImageProviderPolicy
from backend.generators.image_response_extractor import ImageResponseExtractor


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = content
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses=None, get_response=None):
        self.responses = list(responses or [])
        self.get_response = get_response or FakeResponse(content=b"url-image")
        self.posts = []
        self.gets = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "json": dict(json or {})})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self.get_response


def encoded_payload(data=b"image-bytes"):
    return {"data": [{"b64_json": base64.b64encode(data).decode("ascii")}]}


def test_real_models_do_not_send_response_format_by_default():
    for model in ["gpt-image-2", "nano-banana-2", "nano-banana-pro"]:
        session = FakeSession([FakeResponse(payload=encoded_payload())])
        policy = ImageProviderPolicy.from_config({
            "api_key": "test-key",
            "base_url": "https://4sapi.com/v1",
            "model": model,
        })
        client = ImageApiClient(policy, session=session)

        client.generate_via_images({"model": model, "prompt": "test"})

        assert "response_format" not in session.posts[0]["json"]


def test_worker_count_requires_explicit_high_concurrency():
    serial_policy = ImageProviderPolicy.from_config({
        "api_key": "test-key",
        "base_url": "https://4sapi.com/v1",
        "model": "gpt-image-2",
        "max_concurrent": 4,
        "high_concurrency": False,
    })
    parallel_policy = ImageProviderPolicy.from_config({
        "api_key": "test-key",
        "base_url": "https://4sapi.com/v1",
        "model": "gpt-image-2",
        "max_concurrent": 4,
        "high_concurrency": True,
    })

    assert serial_policy.worker_count == 1
    assert parallel_policy.worker_count == 4


def test_explicit_response_format_is_removed_after_unknown_parameter():
    session = FakeSession([
        FakeResponse(
            status_code=400,
            text='{"error":{"message":"Unknown parameter: response_format"}}',
        ),
        FakeResponse(payload=encoded_payload(b"ok")),
    ])
    policy = ImageProviderPolicy.from_config({
        "api_key": "test-key",
        "base_url": "https://4sapi.com/v1",
        "model": "gpt-image-2",
        "response_format": "b64_json",
    })
    client = ImageApiClient(policy, session=session)

    assert client.generate_via_images({"model": "gpt-image-2", "prompt": "test"}) == b"ok"
    assert session.posts[0]["json"]["response_format"] == "b64_json"
    assert "response_format" not in session.posts[1]["json"]


def test_response_extractor_supports_b64_data_url_and_url():
    downloads = []
    extractor = ImageResponseExtractor(lambda url: downloads.append(url) or b"downloaded")

    assert extractor.extract_from_images_response(encoded_payload(b"plain")) == b"plain"
    assert extractor.extract_from_images_response({
        "data": [{"b64_json": "data:image/png;base64," + base64.b64encode(b"data-url").decode("ascii")}]
    }) == b"data-url"
    assert extractor.extract_from_images_response({
        "data": [{"url": "https://example.com/image.png"}]
    }) == b"downloaded"
    assert downloads == ["https://example.com/image.png"]


def test_network_failure_is_not_retried_by_default():
    session = FakeSession([requests.exceptions.SSLError("connection reset")])
    policy = ImageProviderPolicy.from_config({
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "model": "gpt-image-2",
    })
    client = ImageApiClient(policy, session=session)

    try:
        client.generate_via_images({"model": "gpt-image-2", "prompt": "test"})
    except Exception as exc:
        assert "连接失败" in str(exc)
    else:
        raise AssertionError("网络错误应直接返回")
    assert len(session.posts) == 1


def test_network_retry_can_be_enabled_explicitly(monkeypatch):
    session = FakeSession([
        requests.exceptions.ConnectionError("reset"),
        FakeResponse(payload=encoded_payload(b"ok")),
    ])
    policy = ImageProviderPolicy.from_config({
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "model": "gpt-image-2",
        "network_retry_count": 1,
    })
    client = ImageApiClient(policy, session=session)
    monkeypatch.setattr(client, "_sleep_for_retry", lambda *args, **kwargs: None)

    assert client.generate_via_images({"model": "gpt-image-2", "prompt": "test"}) == b"ok"
    assert len(session.posts) == 2
