"""拼豆素材的双阶段 AI 精修服务。"""

from __future__ import annotations

import io
import logging
import warnings
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError


logger = logging.getLogger(__name__)

MAX_IMAGE_PIXELS = 40_000_000
MAX_REFERENCE_DIMENSION = 2048
MAX_COMPOSITE_PANE = 1536
MAX_OUTPUT_BYTES = 25 * 1024 * 1024

_SOURCE_MIME_FORMATS = {
    "image/png": {"PNG"},
    "image/jpeg": {"JPEG"},
    "image/webp": {"WEBP"},
}


class PatternAIInputError(ValueError):
    """请求参数或上传图片不合法。"""


class PatternAIUnsupportedProviderError(RuntimeError):
    """当前图片服务商不能可靠地传递参考图。"""


class PatternAIGenerationError(RuntimeError):
    """上游 AI 生成或返回图片校验失败。"""


@dataclass(frozen=True)
class PatternAIRequest:
    stage: str
    columns: int
    rows: int
    max_used_colors: int


def parse_pattern_ai_request(
    stage: Optional[str],
    columns: Optional[str],
    rows: Optional[str],
    max_used_colors: Optional[str],
) -> PatternAIRequest:
    """解析并校验 multipart 中的标量字段。"""
    normalized_stage = (stage or "").strip().lower()
    if normalized_stage not in {"source", "pattern"}:
        raise PatternAIInputError("stage 必须为 source 或 pattern")

    return PatternAIRequest(
        stage=normalized_stage,
        columns=_parse_bounded_integer("columns", columns, 1, 300),
        rows=_parse_bounded_integer("rows", rows, 1, 300),
        max_used_colors=_parse_bounded_integer(
            "max_used_colors", max_used_colors, 2, 64
        ),
    )


def validate_source_image(data: bytes, mime_type: str) -> bytes:
    """校验源图，并转换为适合发送给图片服务商的 PNG。"""
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    allowed_formats = _SOURCE_MIME_FORMATS.get(normalized_mime)
    if allowed_formats is None:
        raise PatternAIInputError("source 仅支持 PNG、JPEG 或 WebP 图片")
    return _normalize_input_image(data, allowed_formats, "source")


def validate_pattern_preview(data: bytes, mime_type: str) -> bytes:
    """校验初版图纸预览，并转换为规范 PNG。"""
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime != "image/png":
        raise PatternAIInputError("pattern_preview 必须为 PNG 图片")
    return _normalize_input_image(data, {"PNG"}, "pattern_preview")


def build_pattern_ai_prompt(request_data: PatternAIRequest) -> str:
    """生成严格限制角色一致性和拼豆可转换性的精修提示词。"""
    shared = f"""
你是一名拼豆素材精修设计师。参考图是唯一内容依据，请输出一张完整、独立且与目标行列比例一致的素材图。

硬性要求：
1. 画面中只能有原图中的唯一角色；角色身份、面部特征、发型、服装、姿势和道具必须保持，不得替换、增删或重新设定。
2. 主体居中并占画布约 88%–94%，四周保留少量安全边距，任何身体部位和道具都不能被裁切。
3. 背景只能是纯白或透明，不得增加场景、阴影背景、边框和装饰。
4. 禁止任何文字、字母、数字、网格、坐标、色号、图例、Logo 和水印。
5. 使用平涂大色块、清晰硬朗的轮廓和明确的明暗分区；减少渐变、纹理、毛刺、压缩噪点和无意义的碎小色块。
6. 画面将重新转换为 {request_data.columns}×{request_data.rows} 拼豆图纸，最终最多使用 {request_data.max_used_colors} 种 MARD 颜色；请优先保证五官、轮廓、姿势和关键道具在该规格下可辨识。
7. 不要输出解释，只输出精修后的单张图片。
""".strip()

    if request_data.stage == "source":
        return (
            shared
            + "\n\n当前是第一阶段素材精修：保持原画辨识度，将原图整理成适合拼豆量化的干净插画；"
            "不要预先绘制拼豆格或像素网格。"
        )

    return (
        shared
        + "\n\n当前是第二阶段图纸精修。第一张参考图是原始角色，第二张参考图是 Perler 初版图纸；"
        "若收到左右参考板，则左侧是原始角色、右侧是初版图纸。以原始角色校准身份，以初版图纸校准像素布局。"
        "重点修复五官失真、轮廓锯齿、断裂线条和低对比度孤立噪点，但不得新增表情、肢体、道具、文字或装饰。"
        "输出必须呈现硬边方格像素效果，色块边界对齐像素，不绘制网格线、色号或坐标；"
        "结果仍将由 Perler 按指定 MARD 色板和颜色上限重新量化。"
    )


def refine_pattern_image(
    image_service,
    request_data: PatternAIRequest,
    source_png: bytes,
    pattern_preview_png: Optional[bytes] = None,
) -> bytes:
    """调用当前激活图片生成器完成一个阶段，并返回规范 PNG。"""
    if request_data.stage == "pattern" and not pattern_preview_png:
        raise PatternAIInputError("stage=pattern 时必须提供 pattern_preview")

    provider_config = image_service.provider_config or {}
    provider_type = str(
        provider_config.get("type") or getattr(image_service, "provider_name", "")
    ).strip().lower()
    generator = image_service.generator
    prompt = build_pattern_ai_prompt(request_data)
    aspect_ratio = _closest_aspect_ratio(request_data.columns, request_data.rows)

    try:
        with image_service.rate_limiter.acquire():
            if provider_type == "image_api":
                references = [source_png]
                if request_data.stage == "pattern":
                    references.append(pattern_preview_png)
                result = generator.generate_image(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    temperature=provider_config.get("temperature", 1.0),
                    model=provider_config.get("model"),
                    reference_images=references,
                    direct_reference_prompt=True,
                )
            elif provider_type == "google_genai":
                reference = source_png
                if request_data.stage == "pattern":
                    reference = compose_pattern_reference(
                        source_png, pattern_preview_png
                    )
                result = generator.generate_image(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    temperature=provider_config.get("temperature", 1.0),
                    model=provider_config.get(
                        "model", "gemini-3-pro-image-preview"
                    ),
                    reference_image=reference,
                    direct_reference_prompt=True,
                )
            elif provider_type == "openai_compatible":
                raise PatternAIUnsupportedProviderError(
                    "当前图片服务商不支持参考图AI精修"
                )
            else:
                raise PatternAIUnsupportedProviderError(
                    "当前图片服务商不支持参考图AI精修"
                )
    except PatternAIUnsupportedProviderError:
        raise
    except Exception as exc:
        # 不把上游异常文本带到响应或日志，避免第三方错误意外包含密钥。
        logger.warning(
            "拼豆 AI 精修调用失败: provider=%s, stage=%s, error_type=%s",
            provider_type or "unknown",
            request_data.stage,
            type(exc).__name__,
        )
        raise PatternAIGenerationError("AI 图片精修失败，请稍后重试") from None

    try:
        normalized = normalize_generated_png(result)
        if len(normalized) > MAX_OUTPUT_BYTES:
            raise PatternAIInputError("AI 输出图片超过 25MB")
        return normalized
    except PatternAIInputError:
        logger.warning(
            "拼豆 AI 精修返回了无效图片: provider=%s, stage=%s",
            provider_type or "unknown",
            request_data.stage,
        )
        raise PatternAIGenerationError("AI 图片精修未返回有效图片") from None


def compose_pattern_reference(source_png: bytes, pattern_preview_png: bytes) -> bytes:
    """把源图与初版图纸合成 Google GenAI 可接收的单张左右参考板。"""
    source = _open_loaded_image(source_png, {"PNG"}, "source")
    pattern = _open_loaded_image(
        pattern_preview_png, {"PNG"}, "pattern_preview"
    )
    source.thumbnail(
        (MAX_COMPOSITE_PANE, MAX_COMPOSITE_PANE), Image.Resampling.LANCZOS
    )
    pattern.thumbnail(
        (MAX_COMPOSITE_PANE, MAX_COMPOSITE_PANE), Image.Resampling.NEAREST
    )
    source = source.convert("RGBA")
    pattern = pattern.convert("RGBA")

    gap = 24
    canvas_height = max(source.height, pattern.height)
    canvas = Image.new(
        "RGBA", (source.width + gap + pattern.width, canvas_height), "white"
    )
    canvas.alpha_composite(source, (0, (canvas_height - source.height) // 2))
    canvas.alpha_composite(
        pattern, (source.width + gap, (canvas_height - pattern.height) // 2)
    )
    return _save_png(canvas)


def normalize_generated_png(data: bytes) -> bytes:
    """校验 AI 输出的实际图片内容并规范化为 PNG。"""
    image = _open_loaded_image(
        data, {"PNG", "JPEG", "WEBP"}, "AI 输出"
    )
    return _save_png(image)


def _normalize_input_image(
    data: bytes, allowed_formats: set[str], field_name: str
) -> bytes:
    image = _open_loaded_image(data, allowed_formats, field_name)
    image.thumbnail(
        (MAX_REFERENCE_DIMENSION, MAX_REFERENCE_DIMENSION),
        Image.Resampling.LANCZOS,
    )
    return _save_png(image)


def _open_loaded_image(
    data: bytes, allowed_formats: set[str], field_name: str
) -> Image.Image:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise PatternAIInputError(f"{field_name} 不是有效图片")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(bytes(data))) as opened:
                image_format = (opened.format or "").upper()
                if image_format not in allowed_formats:
                    raise PatternAIInputError(
                        f"{field_name} 的实际图片格式与要求不符"
                    )
                width, height = opened.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise PatternAIInputError(
                        f"{field_name} 像素数不能超过 4000 万"
                    )
                opened.load()
                image = ImageOps.exif_transpose(opened)
                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    return image.convert("RGBA")
                return image.convert("RGB")
    except PatternAIInputError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PatternAIInputError(f"{field_name} 图片尺寸过大或疑似解压缩炸弹") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise PatternAIInputError(f"{field_name} 图片已损坏或无法识别") from None


def _save_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _parse_bounded_integer(
    name: str, raw_value: Optional[str], minimum: int, maximum: int
) -> int:
    value = (raw_value or "").strip()
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise PatternAIInputError(
            f"{name} 必须是 {minimum}–{maximum} 的整数"
        ) from None
    if str(parsed) != value and value not in {f"+{parsed}", f"-{abs(parsed)}"}:
        raise PatternAIInputError(
            f"{name} 必须是 {minimum}–{maximum} 的整数"
        )
    if not minimum <= parsed <= maximum:
        raise PatternAIInputError(
            f"{name} 必须在 {minimum}–{maximum} 范围内"
        )
    return parsed


def _closest_aspect_ratio(columns: int, rows: int) -> str:
    candidates = ((1, 1), (2, 3), (3, 2), (3, 4), (4, 3), (4, 5), (5, 4), (9, 16), (16, 9))
    target = columns / rows
    width, height = min(candidates, key=lambda pair: abs(pair[0] / pair[1] - target))
    return f"{width}:{height}"
