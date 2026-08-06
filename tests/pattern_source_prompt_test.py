import io
from pathlib import Path

from PIL import Image

from backend.services.history import HistoryService
from backend.services.image import ImageService
from backend.services.image_rate_limiter import ImageRateLimiter


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), (20, 40, 80)).save(output, format="PNG")
    return output.getvalue()


class PromptCaptureGenerator:
    def __init__(self):
        self.kwargs = None

    def generate_image(self, **kwargs):
        self.kwargs = kwargs
        return png_bytes()


def test_character_sheet_uses_clean_square_pattern_source_prompt(tmp_path: Path):
    history = HistoryService.__new__(HistoryService)
    history.history_dir = str(tmp_path)
    history.index_file = str(tmp_path / "index.json")
    history._init_index()
    generator = PromptCaptureGenerator()
    service = ImageService.__new__(ImageService)
    service.generator = generator
    service.provider_config = {"type": "image_api", "default_aspect_ratio": "3:4"}
    service.use_short_prompt = False
    service.prompt_template = "主题：{user_topic}\n页面：{page_content}\n类型：{page_type}"
    service.prompt_template_short = ""
    service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    service.history_service = history
    service._task_states = {}

    task_dir = tmp_path / "task_pattern"
    task_dir.mkdir()
    result = service._generate_single_image(
        {"index": 0, "type": "cover", "content": "精细角色设定图：原创角色"},
        "task_pattern",
        task_dir=str(task_dir),
        series_context="内容方向：精细角色图",
    )

    assert result[1] is True
    assert generator.kwargs["aspect_ratio"] == "1:1"
    assert "禁止任何文字" in generator.kwargs["prompt"]
    assert "干净背景" in generator.kwargs["prompt"]
