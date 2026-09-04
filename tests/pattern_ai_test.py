import io
from contextlib import contextmanager

import pytest
from flask import Flask
from PIL import Image

import backend.routes.image_routes as image_routes
import backend.services.pattern_ai as pattern_ai
from backend.routes.image_routes import create_image_blueprint


def image_bytes(
    image_format: str = "PNG",
    size: tuple[int, int] = (20, 16),
    color=(30, 80, 160, 255),
) -> bytes:
    output = io.BytesIO()
    mode = "RGBA" if image_format in {"PNG", "WEBP"} else "RGB"
    image = Image.new(mode, size, color if mode == "RGBA" else color[:3])
    image.save(output, format=image_format)
    return output.getvalue()


class TrackingLimiter:
    def __init__(self):
        self.acquire_count = 0

    @contextmanager
    def acquire(self):
        self.acquire_count += 1
        yield


class FakeGenerator:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else image_bytes("JPEG")
        self.error = error
        self.calls = []

    def generate_image(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class FakeImageService:
    def __init__(self, provider_type="image_api", generator=None):
        self.provider_config = {
            "type": provider_type,
            "model": "test-image-model",
            "temperature": 0.4,
        }
        self.provider_name = "test-provider"
        self.generator = generator or FakeGenerator()
        self.rate_limiter = TrackingLimiter()


def make_client(monkeypatch, service):
    monkeypatch.setattr(image_routes, "get_image_service", lambda: service)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_image_blueprint(), url_prefix="/api")
    return app.test_client()


def request_data(stage="source", source=None, pattern_preview=None, **overrides):
    data = {
        "stage": stage,
        "columns": "104",
        "rows": "104",
        "max_used_colors": "40",
    }
    data.update(overrides)
    if source is not False:
        source_data = source or image_bytes("PNG")
        data["source"] = (io.BytesIO(source_data), "source.png", "image/png")
    if pattern_preview is not None:
        preview_data, filename, mime_type = pattern_preview
        data["pattern_preview"] = (
            io.BytesIO(preview_data),
            filename,
            mime_type,
        )
    return data


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", "other"),
        ("columns", "0"),
        ("columns", "1.5"),
        ("rows", "301"),
        ("max_used_colors", "1"),
        ("max_used_colors", "65"),
    ],
)
def test_route_rejects_invalid_scalar_fields(monkeypatch, field, value):
    client = make_client(monkeypatch, FakeImageService())

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(**{field: value}),
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_route_requires_source_and_pattern_preview(monkeypatch):
    client = make_client(monkeypatch, FakeImageService())

    missing_source = client.post(
        "/api/pattern/ai-refine",
        data=request_data(source=False),
        content_type="multipart/form-data",
    )
    missing_preview = client.post(
        "/api/pattern/ai-refine",
        data=request_data(stage="pattern"),
        content_type="multipart/form-data",
    )

    assert missing_source.status_code == 400
    assert "source" in missing_source.get_json()["error"]["detail"]
    assert missing_preview.status_code == 400
    assert "pattern_preview" in missing_preview.get_json()["error"]["detail"]


@pytest.mark.parametrize(
    "data",
    [
        lambda: {
            **request_data(source=False),
            "source": (io.BytesIO(image_bytes("PNG")), "source.gif", "image/gif"),
        },
        lambda: {
            **request_data(source=False),
            "source": (io.BytesIO(b"broken"), "source.png", "image/png"),
        },
        lambda: request_data(
            stage="pattern",
            pattern_preview=(image_bytes("JPEG"), "preview.jpg", "image/jpeg"),
        ),
    ],
)
def test_route_rejects_wrong_mime_or_damaged_images(monkeypatch, data):
    client = make_client(monkeypatch, FakeImageService())

    response = client.post(
        "/api/pattern/ai-refine",
        data=data(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_route_enforces_source_file_size_without_decoding(monkeypatch):
    client = make_client(monkeypatch, FakeImageService())
    too_large = b"x" * (25 * 1024 * 1024 + 1)

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(source=too_large),
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "25MB" in response.get_json()["error"]["detail"]


def test_image_api_source_stage_uses_one_reference_and_returns_normalized_png(monkeypatch):
    generator = FakeGenerator(result=image_bytes("JPEG"))
    service = FakeImageService("image_api", generator)
    client = make_client(monkeypatch, service)

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(stage="source"),
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Pattern-AI-Stage"] == "source"
    with Image.open(io.BytesIO(response.data)) as output:
        assert output.format == "PNG"
    call = generator.calls[0]
    assert len(call["reference_images"]) == 1
    assert call["direct_reference_prompt"] is True
    assert call["reference_images"][0].startswith(b"\x89PNG")
    assert call["aspect_ratio"] == "1:1"
    assert "唯一角色" in call["prompt"]
    assert "88%–94%" in call["prompt"]
    assert "禁止任何文字" in call["prompt"]
    assert service.rate_limiter.acquire_count == 1


def test_image_api_pattern_stage_uses_two_references_and_strict_prompt(monkeypatch):
    generator = FakeGenerator()
    service = FakeImageService("image_api", generator)
    client = make_client(monkeypatch, service)

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(
            stage="pattern",
            pattern_preview=(image_bytes("PNG"), "preview.png", "image/png"),
        ),
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.headers["X-Pattern-AI-Stage"] == "pattern"
    call = generator.calls[0]
    assert len(call["reference_images"]) == 2
    assert call["direct_reference_prompt"] is True
    assert "五官失真" in call["prompt"]
    assert "断裂线条" in call["prompt"]
    assert "低对比度孤立噪点" in call["prompt"]
    assert "硬边方格像素效果" in call["prompt"]
    assert "Perler" in call["prompt"]


def test_google_pattern_stage_composes_side_by_side_reference(monkeypatch):
    generator = FakeGenerator()
    service = FakeImageService("google_genai", generator)
    client = make_client(monkeypatch, service)

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(
            stage="pattern",
            pattern_preview=(
                image_bytes("PNG", size=(18, 18)),
                "preview.png",
                "image/png",
            ),
        ),
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    call = generator.calls[0]
    assert "reference_images" not in call
    assert call["direct_reference_prompt"] is True
    with Image.open(io.BytesIO(call["reference_image"])) as board:
        assert board.format == "PNG"
        assert board.width > board.height
    assert "左侧是原始角色、右侧是初版图纸" in call["prompt"]


def test_openai_compatible_returns_clear_fallback_error(monkeypatch):
    generator = FakeGenerator()
    client = make_client(
        monkeypatch, FakeImageService("openai_compatible", generator)
    )

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"]["code"] == "PATTERN_AI_REFERENCE_UNSUPPORTED"
    assert "当前图片服务商不支持参考图AI精修" in payload["error"]["detail"]
    assert not generator.calls


@pytest.mark.parametrize(
    "generator",
    [
        FakeGenerator(error=RuntimeError("upstream failed with sk-super-secret")),
        FakeGenerator(result=b"not-an-image"),
    ],
)
def test_ai_errors_are_sanitized_and_invalid_outputs_rejected(monkeypatch, generator):
    client = make_client(monkeypatch, FakeImageService("image_api", generator))

    response = client.post(
        "/api/pattern/ai-refine",
        data=request_data(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "PATTERN_AI_FAILED"
    assert b"sk-super-secret" not in response.data


def test_input_rejects_more_than_forty_million_pixels(monkeypatch):
    monkeypatch.setattr(pattern_ai, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(pattern_ai.PatternAIInputError, match="4000 万"):
        pattern_ai.validate_source_image(
            image_bytes("PNG", size=(11, 10)), "image/png"
        )
