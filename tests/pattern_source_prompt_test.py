import io
from pathlib import Path

import pytest
from PIL import Image

from backend.services.history import HistoryService
from backend.services.image import ImageService
from backend.services.image_rate_limiter import ImageRateLimiter


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), (20, 40, 80)).save(output, format="PNG")
    return output.getvalue()


def test_character_sheet_detection_prefers_explicit_content_mode():
    stale_context = "内容方向：精细角色图（单张）"

    assert ImageService._is_character_sheet("character_sheet", stale_context) is True
    assert ImageService._is_character_sheet("story", stale_context) is False
    assert ImageService._is_character_sheet("", stale_context) is True


class PromptCaptureGenerator:
    def __init__(self):
        self.kwargs = None

    def generate_image(self, **kwargs):
        self.kwargs = kwargs
        return png_bytes()


def test_character_sheet_uses_square_aspect_ratio_for_bead_board(tmp_path: Path):
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
        content_mode="character_sheet",
    )

    assert result[1] is True
    assert generator.kwargs["aspect_ratio"] == "1:1"
    generated_prompt = generator.kwargs["prompt"]
    assert generated_prompt.startswith("生成一张 1:1 正方形的高质量二维角色素材图")
    assert "主题：未提供" not in generated_prompt
    assert "页面：精细角色设定图：原创角色" not in generated_prompt
    assert "类型：cover" not in generated_prompt
    assert "【角色转换素材图专用要求｜优先执行】" in generated_prompt
    assert "1:1 正方形" in generated_prompt
    assert "上半身/胸像构图" in generated_prompt
    assert "紧凑的 Q 版全身构图" in generated_prompt
    assert "不要使用细长的成人全身站立构图" in generated_prompt
    assert "主体高度约占画布 85%–95%" in generated_prompt
    # 防止旧版“从头到脚、留大量空白”的构图约束回归；这类细长全身图
    # 在 104×104/200×200 采样后会让脸部和身份细节过小。
    assert "完整显示头部、身体、双腿和鞋子" not in generated_prompt
    assert "角色高度约占画布 80%–90%" not in generated_prompt
    assert "从头到脚留大块空白" in generated_prompt
    assert "不要生成角色名字和描述文字" in generated_prompt
    assert "不要把这些文字绘制到图片中" in generated_prompt
    assert "禁止标题、字幕、标签" in generated_prompt
    assert "纯白或单一浅色背景" in generated_prompt
    assert "【系列图片硬约束】" not in generated_prompt
    assert "【拼豆源图硬约束】" not in generated_prompt


def test_character_sheet_prompt_replaces_generic_cover_framing_with_compact_square_layout():
    prompt = ImageService._build_character_sheet_prompt(
        "生成一张竖版 3:4 的高质量社交媒体配图。\n"
        "本页素材（用于理解主题、事实和视觉场景；并非都要写进图片）：\n"
        "---\n{page_content}\n---\n"
        "封面最多保留主标题（最多 14 个汉字）和可选副标题（最多 12 个汉字）。",
        "角色：原创角色\n发型：粉紫色短发\n服装：蓝色外套",
    )

    assert prompt.startswith("生成一张 1:1 正方形的高质量二维角色素材图")
    assert "上半身/胸像细节" in prompt
    assert "紧凑的 Q 版全身构图" in prompt
    assert "104×104 和 200×200" in prompt
    assert "竖版 3:4" not in prompt
    assert "主标题" not in prompt


@pytest.mark.parametrize(
    ("provider_type", "dimension_key", "expected_dimension"),
    [
        ("google_genai", "aspect_ratio", "1:1"),
        ("openai_compatible", "size", "1024x1024"),
    ],
)
def test_character_sheet_forces_square_dimensions_for_other_providers(
    tmp_path: Path,
    provider_type: str,
    dimension_key: str,
    expected_dimension: str,
):
    """角色图必须覆盖服务商的全局竖图默认值，确保可直接采样到方形拼豆板。"""
    history = HistoryService.__new__(HistoryService)
    history.history_dir = str(tmp_path)
    history.index_file = str(tmp_path / "index.json")
    history._init_index()
    generator = PromptCaptureGenerator()
    service = ImageService.__new__(ImageService)
    service.generator = generator
    service.provider_config = {
        "type": provider_type,
        "default_aspect_ratio": "3:4",
        "default_size": "1024x1536",
    }
    service.use_short_prompt = False
    service.prompt_template = "{page_content}"
    service.prompt_template_short = ""
    service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    service.history_service = history
    service._task_states = {}

    task_dir = tmp_path / provider_type
    task_dir.mkdir()
    result = service._generate_single_image(
        {"index": 0, "type": "cover", "content": "精细角色设定图：原创角色"},
        f"task_{provider_type}",
        task_dir=str(task_dir),
        content_mode="character_sheet",
    )

    assert result[1] is True
    assert generator.kwargs[dimension_key] == expected_dimension


def test_character_sheet_guidance_is_not_added_to_story_images(tmp_path: Path):
    history = HistoryService.__new__(HistoryService)
    history.history_dir = str(tmp_path)
    history.index_file = str(tmp_path / "index.json")
    history._init_index()
    generator = PromptCaptureGenerator()
    service = ImageService.__new__(ImageService)
    service.generator = generator
    service.provider_config = {"type": "image_api", "default_aspect_ratio": "3:4"}
    service.use_short_prompt = False
    service.prompt_template = "{page_content}"
    service.prompt_template_short = ""
    service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    service.history_service = history
    service._task_states = {}

    task_dir = tmp_path / "task_story"
    task_dir.mkdir()
    result = service._generate_single_image(
        {"index": 0, "type": "cover", "content": "海边的夏日故事"},
        "task_story",
        task_dir=str(task_dir),
        series_context="内容方向：剧情小故事",
        content_mode="story",
    )

    assert result[1] is True
    assert "【拼豆角色素材图专用要求｜优先执行】" not in generator.kwargs["prompt"]


def test_character_sheet_retry_removes_legacy_pixel_layout_hint(tmp_path: Path):
    history = HistoryService.__new__(HistoryService)
    history.history_dir = str(tmp_path)
    history.index_file = str(tmp_path / "index.json")
    history._init_index()
    generator = PromptCaptureGenerator()
    service = ImageService.__new__(ImageService)
    service.generator = generator
    service.provider_config = {"type": "image_api", "default_aspect_ratio": "3:4"}
    service.use_short_prompt = False
    service.prompt_template = "{page_content}"
    service.prompt_template_short = ""
    service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    service.history_service = history
    service._task_states = {}

    task_dir = tmp_path / "task_legacy_character"
    task_dir.mkdir()
    result = service._generate_single_image(
        {
            "index": 0,
            "type": "cover",
            "content": (
                "精细角色设定图：后藤一里；采用系列固定像素风与色板，单张 3:4 竖版构图；"
                "保留粉紫色长发和紫色眼睛。"
            ),
        },
        "task_legacy_character",
        task_dir=str(task_dir),
        content_mode="character_sheet",
    )

    assert result[1] is True
    assert "采用系列固定像素风" not in generator.kwargs["prompt"]
    assert "3:4 竖版构图" not in generator.kwargs["prompt"]
    assert "粉紫色长发" in generator.kwargs["prompt"]


def test_character_sheet_cleanup_preserves_pixel_identity_descriptions(tmp_path: Path):
    """普通角色特征中的像素/渐变词不能被旧规则清理误删。"""
    cleaned = ImageService._clean_character_sheet_page_content(
        "角色：原创角色\n发型：粉紫渐变长发\n服装颜色：蓝紫色像素风制服"
    )
    assert "发型：粉紫渐变长发" in cleaned
    assert "服装颜色：蓝紫色像素风制服" in cleaned

    history = HistoryService.__new__(HistoryService)
    history.history_dir = str(tmp_path)
    history.index_file = str(tmp_path / "index.json")
    history._init_index()
    generator = PromptCaptureGenerator()
    service = ImageService.__new__(ImageService)
    service.generator = generator
    service.provider_config = {"type": "image_api", "default_aspect_ratio": "3:4"}
    service.use_short_prompt = False
    service.prompt_template = "{page_content}"
    service.prompt_template_short = ""
    service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    service.history_service = history
    service._task_states = {}

    task_dir = tmp_path / "task_identity_terms"
    task_dir.mkdir()
    result = service._generate_single_image(
        {
            "index": 0,
            "type": "cover",
            "content": "角色：原创像素角色；粉紫渐变长发；服装颜色为蓝紫色。",
        },
        "task_identity_terms",
        task_dir=str(task_dir),
        content_mode="character_sheet",
    )

    assert result[1] is True
    assert "像素角色" in generator.kwargs["prompt"]
    assert "粉紫渐变长发" in generator.kwargs["prompt"]
    assert "蓝紫色" in generator.kwargs["prompt"]


def test_character_sheet_retry_strips_legacy_full_bead_template_but_keeps_identity(tmp_path: Path):
    history = HistoryService.__new__(HistoryService)
    history.history_dir = str(tmp_path)
    history.index_file = str(tmp_path / "index.json")
    history._init_index()
    generator = PromptCaptureGenerator()
    service = ImageService.__new__(ImageService)
    service.generator = generator
    service.provider_config = {"type": "image_api", "default_aspect_ratio": "3:4"}
    service.use_short_prompt = False
    service.prompt_template = "{page_content}"
    service.prompt_template_short = ""
    service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    service.history_service = history
    service._task_states = {}

    legacy_prompt = (
        "【当前唯一角色】\n"
        "角色：后藤一里\n"
        "作品：孤独摇滚！\n"
        "粉紫色长发，黄色发夹，紫色眼睛，校服。\n"
        "【最重要：严格拼豆网格】\n"
        "最终图案必须严格按照 104 × 104 个正方形网格设计，共 10816 个格子。\n"
        "每一个格子只能有一种颜色，不允许渐变、抗锯齿、半格或真实拼豆颗粒。"
    )
    task_dir = tmp_path / "task_legacy_full_prompt"
    task_dir.mkdir()
    result = service._generate_single_image(
        {"index": 0, "type": "cover", "content": legacy_prompt},
        "task_legacy_full_prompt",
        task_dir=str(task_dir),
        content_mode="character_sheet",
    )

    assert result[1] is True
    generated_prompt = generator.kwargs["prompt"]
    assert "后藤一里" in generated_prompt
    assert "孤独摇滚" in generated_prompt
    assert "粉紫色长发" in generated_prompt
    assert "拼豆生产输出" not in generated_prompt
    assert "严格拼豆网格" not in generated_prompt
    assert "104 × 104" not in generated_prompt
    assert "10816" not in generated_prompt
    assert "每一个格子只能" not in generated_prompt
    assert "拼豆施工图" not in generated_prompt
    assert "拼豆制作" not in generated_prompt
    assert "抗锯齿" not in generated_prompt


def test_pattern_source_keeps_explicit_source_constraints(tmp_path: Path):
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

    task_dir = tmp_path / "task_source"
    task_dir.mkdir()
    result = service._generate_single_image(
        {"index": 0, "type": "pattern_source", "content": "主体素材"},
        "task_source",
        task_dir=str(task_dir),
    )

    assert result[1] is True
    assert generator.kwargs["aspect_ratio"] == "1:1"
    assert "【拼豆源图硬约束】" in generator.kwargs["prompt"]
